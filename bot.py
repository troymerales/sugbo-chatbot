"""
The inference pipeline (§1 of the architecture doc).

respond() is the single code path for producing an answer: ask the answer model,
run the verification pass, and downgrade to a refusal if the answer isn't
grounded. The Streamlit app and the eval harness both go through here so they
measure the same thing.
"""

from __future__ import annotations

from dataclasses import dataclass

import config
import knowledge
import llm
from grounding import GroundingVerdict, verify

_REFUSAL_REPLY = (
    f"{config.REFUSAL_MARKER}. You can submit a support ticket and our team "
    "will follow up."
)


@dataclass
class AnswerResult:
    text: str                       # what the user sees (may be the refusal)
    draft: str                      # the answer model's raw first reply
    refused: bool                   # final answer is a refusal
    grounding: GroundingVerdict

    def log_entry(self, question: str) -> dict:
        return {
            "question": question,
            "refused": self.refused,
            "grounding_checked": self.grounding.checked,
            "grounding_supported": self.grounding.supported,
            "grounding_reason": self.grounding.reason,
            "unsupported_claims": list(self.grounding.unsupported_claims),
        }


def fresh_chat():
    """A new multi-turn chat session primed with the full docs."""
    return llm.new_chat(knowledge.system_prompt(), model=config.ANSWER_MODEL)


def respond(chat: llm.Chat, question: str) -> AnswerResult:
    try:
        draft = chat.send(question)
    except llm.LLMError as exc:
        verdict = GroundingVerdict(True, (), f"answer model error: {exc}", False)
        return AnswerResult(
            text=f"Sorry — I couldn't reach the model just now ({exc}).",
            draft="", refused=False, grounding=verdict,
        )

    verdict = verify(question, draft)
    if verdict.is_refusal_worthy:
        return AnswerResult(_REFUSAL_REPLY, draft, True, verdict)

    refused = config.REFUSAL_MARKER.lower() in draft.lower()
    return AnswerResult(draft, draft, refused, verdict)
