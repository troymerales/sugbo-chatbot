"""
Structured clinical-fact extraction: pull discrete fields out of the transcript
so notes can be queried, aggregated, and quality-checked, not just read.
"""

from __future__ import annotations

from stt.gemini import generate_structured
from stt.schemas import ClinicalExtract

_PROMPT = """You are a clinical information extractor. Below is an ASR transcript \
of a Bisaya/Cebuano doctor-patient consult (it may contain transcription errors).

Extract the following as structured data, in English. Use only what the \
transcript supports; leave a field empty ("" or []) rather than guessing.

- chief_complaint: the main problem, in a few words
- onset / duration / severity: as described by the patient
- associated_symptoms: symptoms the patient reports having
- pertinent_negatives: symptoms explicitly denied ("wala", "dili")
- vitals: any vital signs or measurements the clinician mentions (name + value; \
if the clinician only says "normal", record value "normal")
- medications: drugs mentioned as current or newly prescribed
- diagnoses: the clinician's stated impression(s)
- follow_up: follow-up interval or condition for returning
- red_flags: any symptom or finding that would warrant urgent re-evaluation, \
whether or not the clinician flagged it

Transcript:
\"\"\"
{transcript}
\"\"\"
"""


def extract_clinical_facts(transcript: str, *, model: str | None = None) -> ClinicalExtract:
    if not transcript or not transcript.strip():
        return ClinicalExtract()
    return generate_structured(
        _PROMPT.format(transcript=transcript.strip()),
        ClinicalExtract,
        model=model,
        temperature=0.1,
    )
