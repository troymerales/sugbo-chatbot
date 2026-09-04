"""
LLM self-review of a generated SOAP note against its source transcript. Catches
the main failure mode of note generation: confidently written Objective /
Assessment lines the conversation never actually supported.
"""

from __future__ import annotations

from stt.gemini import generate_structured
from stt.schemas import GroundingReview, SoapNote

_PROMPT = """You are a meticulous clinical-documentation auditor. Compare a SOAP \
note to the transcript it was generated from.

The transcript is ASR output of a Bisaya/Cebuano consult, so allow for wording \
differences and minor transcription noise -- judge meaning, not exact words.

Return:
- grounding_score (1-5): 5 = every statement in the note is supported by the \
transcript; 1 = the note is largely fabricated.
- completeness_score (1-5): 5 = the note captures everything clinically \
relevant in the transcript; 1 = major content is missing.
- unsupported_statements: specific claims in the note not backed by the \
transcript (quote or paraphrase each). Empty list if none.
- missing_elements: clinically relevant things in the transcript the note left \
out. Empty list if none.
- summary: one or two sentences of overall judgement.

Transcript:
\"\"\"
{transcript}
\"\"\"

SOAP note:
Subjective: {subjective}
Objective: {objective}
Assessment: {assessment}
Plan: {plan}
"""


def review_soap_note(transcript: str, note: SoapNote, *,
                     model: str | None = None) -> GroundingReview:
    prompt = _PROMPT.format(
        transcript=transcript.strip(),
        subjective=note.subjective or "(empty)",
        objective=note.objective or "(empty)",
        assessment=note.assessment or "(empty)",
        plan=note.plan or "(empty)",
    )
    return generate_structured(prompt, GroundingReview, model=model, temperature=0.1)
