"""
Verification pass (§1 of the architecture doc).

After the answer model replies, a second, independent model call checks the draft
answer against the docs: is every factual claim supported? This catches the
hallucinations the answer model won't catch about its own output.

Returns a `GroundingVerdict`. The app shows the answer only if `supported` is
True; otherwise it swaps in the refusal and moves to failure capture.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import config
import knowledge
from llm import LLMError, generate

_RUBRIC = """You are a strict fact-checker for a support assistant.

You are given: the product DOCUMENTATION, the user's QUESTION, and the assistant's
DRAFT ANSWER.

Decide whether every factual claim in the DRAFT ANSWER (UI labels, menu paths,
field names, steps, capabilities) is directly supported by the DOCUMENTATION.

Rules:
- A claim is "supported" only if you can point to the sentence in the docs.
- Generic pleasantries and offers to help are fine, ignore them.
- If the draft answer already says it doesn't have the information, that is
  "supported" (it is a correct refusal) unless it then contradicts itself.
- Paraphrasing is fine; inventing specifics is not.

Reply with a JSON object, nothing else:
{"supported": true|false,
 "unsupported_claims": ["..."],
 "reason": "one sentence"}"""


@dataclass(frozen=True)
class GroundingVerdict:
    supported: bool
    unsupported_claims: tuple[str, ...]
    reason: str
    checked: bool  # False if the verification call itself failed

    @property
    def is_refusal_worthy(self) -> bool:
        return self.checked and not self.supported


def verify(question: str, draft_answer: str) -> GroundingVerdict:
    # A draft that is already the canonical refusal needs no check.
    if config.REFUSAL_MARKER.lower() in draft_answer.lower():
        return GroundingVerdict(True, (), "assistant refused, which is allowed", True)

    prompt = (
        f"DOCUMENTATION:\n{knowledge.load_docs()}\n\n"
        f"QUESTION:\n{question}\n\n"
        f"DRAFT ANSWER:\n{draft_answer}"
    )
    try:
        raw = generate(
            prompt,
            system=_RUBRIC,
            model=config.UTILITY_MODEL,
            temperature=0.0,
            json_mode=True,
        )
        data = json.loads(raw)
    except (LLMError, json.JSONDecodeError, TypeError) as exc:
        # Fail open but flag it — don't block answers because the checker broke.
        return GroundingVerdict(True, (), f"verification unavailable: {exc}", False)

    return GroundingVerdict(
        supported=bool(data.get("supported", True)),
        unsupported_claims=tuple(data.get("unsupported_claims", []) or []),
        reason=str(data.get("reason", "")),
        checked=True,
    )
