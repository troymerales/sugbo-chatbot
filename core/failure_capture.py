"""
Failure capture (§2 of the architecture doc).

`detect_failures()` — rule-based signals that a chat has gone wrong. Rules only,
zero ML: the bot's own refusal, a thumbs-down, a re-asked question, or a "this
is wrong" phrase. A classifier is only worth training once the logs show these
rules missing failures.

(An LLM `triage()` call — docs-gap / product-bug / out-of-scope — used to run
here too; it was removed to cut per-conversation model cost.)
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

import config

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
