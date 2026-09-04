"""
Pydantic models shared by the STT LLM layer. They serve three jobs at once: the
``response_schema`` handed to Gemini for structured output, validation of what
comes back, and the typed shape the Streamlit pages render.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

SECTIONS = ["Subjective", "Objective", "Assessment", "Plan"]
NOT_ENOUGH = "Not enough information in the conversation."


class SoapNote(BaseModel):
    subjective: str = ""
    objective: str = ""
    assessment: str = ""
    plan: str = ""

    def as_sections(self) -> dict[str, str]:
        return {
            "Subjective": self.subjective,
            "Objective": self.objective,
            "Assessment": self.assessment,
            "Plan": self.plan,
        }

    @classmethod
    def from_sections(cls, data: dict[str, str]) -> "SoapNote":
        lower = {k.lower(): (v or "") for k, v in data.items()}
        return cls(
            subjective=lower.get("subjective", ""),
            objective=lower.get("objective", ""),
            assessment=lower.get("assessment", ""),
            plan=lower.get("plan", ""),
        )

    def is_empty(self) -> bool:
        return not any(v.strip() for v in self.as_sections().values())


class Vital(BaseModel):
    name: str
    value: str


class ClinicalExtract(BaseModel):
    chief_complaint: str = ""
    onset: str = ""
    duration: str = ""
    severity: str = ""
    associated_symptoms: list[str] = Field(default_factory=list)
    pertinent_negatives: list[str] = Field(default_factory=list)
    vitals: list[Vital] = Field(default_factory=list)
    medications: list[str] = Field(default_factory=list)
    diagnoses: list[str] = Field(default_factory=list)
    follow_up: str = ""
    red_flags: list[str] = Field(default_factory=list)


class GroundingReview(BaseModel):
    grounding_score: int = Field(ge=1, le=5, default=3)
    completeness_score: int = Field(ge=1, le=5, default=3)
    unsupported_statements: list[str] = Field(default_factory=list)
    missing_elements: list[str] = Field(default_factory=list)
    summary: str = ""
