"""
Offline evaluation against the synthetic ``trial/`` set.

``trial/script.txt`` holds two Python-list literals -- doctor+patient dialogues
and doctor-only narration -- and ``trial/audio_output/`` holds Google-TTS
renderings named ``2_<i>.mp3`` (dialogue) and ``1_<i>.mp3`` (narration). Since we
know the exact text each clip was synthesized from, we can measure ASR word
error rate directly, and optionally score the SOAP notes with the grounding
reviewer.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from stt.config import get_settings
from stt.gemini import LLM_EXHAUSTED_MESSAGE, LLMQuotaError


@dataclass
class RefClip:
    clip_id: str          # "1_3" / "2_1"
    kind: str             # "narration" / "dialogue"
    audio_path: Path
    reference_text: str


@dataclass
class ClipResult:
    clip: RefClip
    hypothesis: str = ""
    wer: float | None = None
    cer: float | None = None
    soap: dict | None = None
    grounding_score: int | None = None
    completeness_score: int | None = None
    error: str | None = None
    extras: dict = field(default_factory=dict)


def _strip_speaker_tags(text: str) -> str:
    for tag in ("Doktor:", "Pasyente:", "Doctor:", "Patient:"):
        text = text.replace(tag, " ")
    return " ".join(text.split())


def load_reference_clips(trial_dir: Path | None = None) -> list[RefClip]:
    root = Path(trial_dir or get_settings().trial_dir)
    script = root / "script.txt"
    audio_dir = root / "audio_output"
    if not script.exists():
        return []

    content = script.read_text(encoding="utf-8")
    two_way, doctor_only = ast.literal_eval("(" + content + ")")

    clips: list[RefClip] = []
    for i, line in enumerate(doctor_only, start=1):
        path = audio_dir / f"1_{i}.mp3"
        if path.exists():
            clips.append(RefClip(f"1_{i}", "narration", path, _strip_speaker_tags(line)))
    for i, line in enumerate(two_way, start=1):
        path = audio_dir / f"2_{i}.mp3"
        if path.exists():
            clips.append(RefClip(f"2_{i}", "dialogue", path, _strip_speaker_tags(line)))
    return clips


def _normalize(text: str) -> str:
    import re

    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def score_transcription(reference: str, hypothesis: str) -> tuple[float, float]:
    import jiwer

    ref, hyp = _normalize(reference), _normalize(hypothesis)
    if not ref:
        return (0.0, 0.0)
    return (float(jiwer.wer(ref, hyp)), float(jiwer.cer(ref, hyp)))


def evaluate_clip(clip: RefClip, *, run_soap: bool = False,
                  run_review: bool = False) -> ClipResult:
    from stt.asr import transcribe

    res = ClipResult(clip=clip)
    try:
        tr = transcribe(clip.audio_path.read_bytes(), "audio/mpeg")
        res.hypothesis = tr.text
        res.wer, res.cer = score_transcription(clip.reference_text, tr.text)

        if run_soap:
            from stt.soap import generate_soap_note

            note = generate_soap_note(tr.text)
            res.soap = note.as_sections()
            if run_review:
                from stt.review import review_soap_note

                review = review_soap_note(tr.text, note)
                res.grounding_score = review.grounding_score
                res.completeness_score = review.completeness_score
                res.extras["review_summary"] = review.summary
    except LLMQuotaError:
        res.error = LLM_EXHAUSTED_MESSAGE
    except Exception as e:  # keep the batch going
        res.error = f"{type(e).__name__}: {e}"
    return res


def aggregate(results: list[ClipResult]) -> dict:
    scored = [r for r in results if r.wer is not None]
    n = len(scored)
    out = {
        "clips": len(results),
        "scored": n,
        "errors": sum(1 for r in results if r.error),
        "mean_wer": sum(r.wer for r in scored) / n if n else None,
        "mean_cer": sum(r.cer for r in scored) / n if n else None,
    }
    g = [r.grounding_score for r in results if r.grounding_score is not None]
    c = [r.completeness_score for r in results if r.completeness_score is not None]
    if g:
        out["mean_grounding"] = sum(g) / len(g)
    if c:
        out["mean_completeness"] = sum(c) / len(c)
    return out
