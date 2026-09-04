"""
SOAP-note generation from a (possibly noisy) Bisaya/Cebuano transcript. The note
is always written in English -- standard practice for clinical documentation in
the Philippines even when the consult itself was in Bisaya/Cebuano.
"""

from __future__ import annotations

import re

from stt.gemini import generate_structured
from stt.schemas import NOT_ENOUGH, SECTIONS, SoapNote

__all__ = ["SECTIONS", "SoapNote", "generate_soap", "generate_soap_note", "parse_soap_text"]


_SYSTEM = """You are an experienced clinical scribe working in an outpatient \
clinic in the Philippines. You will be given a transcript of a doctor-patient \
conversation conducted in Bisaya/Cebuano and produced by automatic speech \
recognition, so it may contain word errors, missing words, or mis-splits.

Write a concise SOAP note in English.

The transcript may be labelled with speaker roles ("Doctor:" / "Patient:"). \
When it is, use those labels to attribute statements -- the patient's lines \
drive Subjective, the doctor's lines drive Objective / Assessment / Plan. When \
it is not labelled, infer the roles from context.

Rules:
- Subjective: what the patient reports -- symptoms, history, timeline, relevant \
context. First person accounts become third person ("patient reports ...").
- Objective: only findings the clinician states out loud in the transcript \
(vitals, exam findings, results). Do NOT invent measurements or normal exam \
lines that were not mentioned.
- Assessment: the clinician's impression / working diagnosis. If the clinician \
did not commit to one, summarize the most likely differential they implied.
- Plan: management, prescriptions, advice, follow-up, and return precautions.
- Never contradict the transcript and never add clinical facts that are not \
supported by it. It is better to be brief than to speculate.
- If a section genuinely cannot be filled from the conversation, use exactly: \
"{not_enough}"
""".format(not_enough=NOT_ENOUGH)

_USER = """{context}Transcript:
\"\"\"
{transcript}
\"\"\"
"""


def _build_prompt(transcript: str, context: str | None) -> str:
    ctx = ""
    if context and context.strip():
        ctx = (
            "Known patient context (use only if consistent with the transcript):\n"
            f"{context.strip()}\n\n"
        )
    return _SYSTEM + "\n\n" + _USER.format(context=ctx, transcript=transcript.strip())


def generate_soap_note(transcript: str, *, context: str | None = None,
                       model: str | None = None) -> SoapNote:
    if not transcript or not transcript.strip():
        return SoapNote(
            subjective=NOT_ENOUGH, objective=NOT_ENOUGH,
            assessment=NOT_ENOUGH, plan=NOT_ENOUGH,
        )
    return generate_structured(
        _build_prompt(transcript, context), SoapNote, model=model, temperature=0.2
    )


def generate_soap(transcript: str, *, context: str | None = None,
                  model: str | None = None) -> dict[str, str]:
    """Back-compat shim: returns ``{"Subjective": ..., ...}``."""
    return generate_soap_note(transcript, context=context, model=model).as_sections()


def parse_soap_text(text: str) -> dict[str, str]:
    """Parse a plain-text SOAP note (headers on their own line, with or without a
    trailing colon). Retained for pasted/legacy notes and as a fallback."""
    pattern = r"(?im)^\s*(" + "|".join(SECTIONS) + r")\s*:?\s*$"
    parts = re.split(pattern, text or "")
    parsed = {name: "" for name in SECTIONS}
    for i in range(1, len(parts) - 1, 2):
        name = parts[i].strip().title()
        if name in parsed:
            parsed[name] = parts[i + 1].strip()
    return parsed
