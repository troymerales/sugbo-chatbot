"""
Failure capture (§2 of the architecture doc).

Two jobs:
  1. detect_failures()  — rule-based signals that a chat has gone wrong.
     Rules first, model later: the bot's own refusal and a thumbs-down cover
     most cases with zero ML. A classifier is only worth training once the logs
     show the rules missing failures.
  2. triage()           — one model call: is this a docs gap, a product bug, or
     out of scope? Decides whether to offer a ticket and where the failure goes
     in the docs-maintenance queue.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from typing import Literal

import config
from llm import LLMError, QuotaError, generate

TriageLabel = Literal["docs_gap", "product_bug", "out_of_scope"]

_NEGATIVE_PHRASES = (
    "not helpful", "didn't help", "doesn't help", "that's wrong", "thats wrong",
    "still not working", "not what i asked", "you're wrong", "incorrect",
    "that is not right", "nope", "no that's not it", "useless",
)


@dataclass
class FailureSignals:
    refused: bool = False              # bot emitted the refusal marker
    grounding_failed: bool = False     # verification pass rejected an answer
    thumbs_down: bool = False          # user pressed 👎
    repeated_question: bool = False    # user re-asked the same thing
    negative_feedback: bool = False    # user typed a "this is wrong" phrase
    reasons: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(
            (self.refused, self.grounding_failed, self.thumbs_down,
             self.repeated_question, self.negative_feedback)
        )

    def as_list(self) -> list[str]:
        names = []
        for name in ("refused", "grounding_failed", "thumbs_down",
                     "repeated_question", "negative_feedback"):
            if getattr(self, name):
                names.append(name)
        return names


def _user_turns(messages: list[dict]) -> list[str]:
    return [m["content"] for m in messages if m["role"] == "user"]


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def detect_failures(
    messages: list[dict],
    *,
    thumbs_down: bool = False,
    grounding_failed: bool = False,
) -> FailureSignals:
    """Inspect the conversation so far and return which failure signals fired."""
    sig = FailureSignals(thumbs_down=thumbs_down, grounding_failed=grounding_failed)

    if thumbs_down:
        sig.reasons.append("user pressed thumbs-down")
    if grounding_failed:
        sig.reasons.append("verification pass rejected an answer")

    for m in messages:
        if m["role"] == "assistant" and config.REFUSAL_MARKER.lower() in m["content"].lower():
            sig.refused = True
            sig.reasons.append("bot could not answer from the docs")
            break

    users = _user_turns(messages)
    for i in range(len(users)):
        for j in range(i + 1, len(users)):
            if _similar(users[i], users[j]) >= 0.8:
                sig.repeated_question = True
                sig.reasons.append("user re-asked the same question")
                break
        if sig.repeated_question:
            break

    last_user = users[-1].lower() if users else ""
    if any(p in last_user for p in _NEGATIVE_PHRASES):
        sig.negative_feedback = True
        sig.reasons.append("user said the answer was wrong / unhelpful")

    return sig


# --------------------------------------------------------------------------- #
# Triage
# --------------------------------------------------------------------------- #

_TRIAGE_RUBRIC = """You triage failed support conversations for SugboDoc, a
clinic management SaaS.

Classify the conversation into exactly one of:
- "docs_gap": the product probably does what the user wants, but the
  documentation doesn't explain it (or explains it unclearly).
- "product_bug": the user describes something broken — an error, a missing
  button that should be there, a feature not behaving as documented.
- "out_of_scope": the request is not about using SugboDoc (billing disputes,
  legal questions, integrations that don't exist, general medical advice).

Reply with JSON only: {"label": "...", "confidence": 0.0-1.0, "rationale": "one sentence"}"""


@dataclass(frozen=True)
class TriageResult:
    label: TriageLabel
    confidence: float
    rationale: str

    @property
    def should_offer_ticket(self) -> bool:
        return self.label in ("product_bug", "docs_gap")


def triage(transcript: str) -> TriageResult:
    try:
        raw = generate(
            f"CONVERSATION:\n{transcript}",
            system=_TRIAGE_RUBRIC,
            model=config.UTILITY_MODEL,
            temperature=0.0,
            json_mode=True,
        )
        data = json.loads(raw)
        label = data.get("label", "docs_gap")
        if label not in ("docs_gap", "product_bug", "out_of_scope"):
            label = "docs_gap"
        return TriageResult(
            label=label,  # type: ignore[arg-type]
            confidence=float(data.get("confidence", 0.5)),
            rationale=str(data.get("rationale", "")),
        )
    except (LLMError, QuotaError, json.JSONDecodeError, TypeError, ValueError):
        # Safe default: treat as a docs gap so it still gets logged and queued.
        return TriageResult("docs_gap", 0.0, "triage unavailable — defaulted")
