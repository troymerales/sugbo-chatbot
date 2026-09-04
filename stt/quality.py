"""
``TranscriptionResult`` and cheap quality signals so a page can warn on a bad
recording before anyone edits a note.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

NO_SPEECH = "(no speech recognized)"


@dataclass
class TranscriptionResult:
    text: str
    duration_s: float | None = None
    model_id: str = ""
    language: str = ""
    warnings_extra: list[str] = field(default_factory=list)

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    @property
    def words_per_second(self) -> float | None:
        if not self.duration_s:
            return None
        return self.word_count / self.duration_s if self.duration_s else None

    @property
    def repetition_ratio(self) -> float:
        """1 - (unique tokens / total tokens). High values usually mean the ASR
        model got stuck in a loop on noisy/silent audio."""
        toks = re.findall(r"\w+", self.text.lower())
        if not toks:
            return 0.0
        return 1.0 - len(set(toks)) / len(toks)

    def quality_warnings(self) -> list[str]:
        warnings: list[str] = list(self.warnings_extra)
        if not self.text.strip() or self.text.strip() == NO_SPEECH:
            return ["No speech was recognized in this audio.", *warnings]
        if self.word_count < 8:
            warnings.append(f"Very short transcript ({self.word_count} words) -- check the recording.")
        if self.repetition_ratio > 0.6 and self.word_count > 20:
            warnings.append("Highly repetitive output -- the model may have looped on noise or silence.")
        wps = self.words_per_second
        if wps is not None and self.duration_s and self.duration_s > 5 and wps < 0.4:
            warnings.append("Long audio but little text transcribed -- audio may be mostly silence or non-speech.")
        return warnings
