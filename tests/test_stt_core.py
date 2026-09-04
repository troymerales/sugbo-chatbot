"""
STT -> SOAP pure-logic tests: config, schemas, SOAP text parsing, transcript
quality signals, the notes DB, export rendering, and evaluation scoring against
the real trial/ fixtures. All offline (mock backend via conftest).
"""

from __future__ import annotations

import pytest

from stt import config as stt_config
from stt import evaluation, export
from stt import notes_db as db
from stt.evaluation import ClipResult, _normalize, _strip_speaker_tags
from stt.quality import NO_SPEECH, TranscriptionResult
from stt.schemas import SoapNote
from stt.soap import parse_soap_text


# --------------------------------------------------------------- config ---

def test_config_defaults(monkeypatch):
    for var in ("BISAYA_WHISPER_MODEL_ID", "BISAYA_SOAP_MODEL_ID", "GEMINI_MODEL",
                "BISAYA_ASR_LANGUAGE", "HF_TOKEN", "HUGGINGFACE_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    s = stt_config.reload_settings()
    assert s.whisper_model_id == stt_config.DEFAULT_WHISPER_MODEL
    assert s.soap_model_id == stt_config.DEFAULT_SOAP_MODEL
    assert s.asr_language == "tl"
    assert s.asr_available is False


def test_config_env_override(monkeypatch):
    monkeypatch.setenv("BISAYA_WHISPER_MODEL_ID", "me/model")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-x")
    monkeypatch.setenv("HF_TOKEN", "hf_abc")
    s = stt_config.reload_settings()
    assert s.whisper_model_id == "me/model"
    assert s.soap_model_id == "gemini-x"
    assert s.asr_available is True


def test_availability_flags(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert stt_config.reload_settings().llm_available is False
    monkeypatch.setenv("GEMINI_API_KEY", "abc")
    assert stt_config.reload_settings().llm_available is True


# --------------------------------------------------------------- schemas ---

def test_soapnote_sections_roundtrip():
    note = SoapNote(subjective="a", objective="b", assessment="c", plan="d")
    assert note.as_sections() == {"Subjective": "a", "Objective": "b",
                                  "Assessment": "c", "Plan": "d"}
    assert SoapNote.from_sections(note.as_sections()) == note


def test_soapnote_from_sections_case_insensitive():
    note = SoapNote.from_sections({"subjective": "x", "PLAN": "y"})
    assert note.subjective == "x" and note.plan == "y" and note.objective == ""


def test_soapnote_is_empty():
    assert SoapNote().is_empty()
    assert not SoapNote(plan="do something").is_empty()


def test_parse_soap_text_with_and_without_colons():
    parsed = parse_soap_text("Subjective:\nHeadache.\nPlan:\nRest.\n")
    assert parsed["Subjective"] == "Headache." and parsed["Plan"] == "Rest."
    parsed = parse_soap_text("SUBJECTIVE\nCough x3d\n\nobjective\nLungs clear\n")
    assert parsed["Subjective"] == "Cough x3d" and parsed["Objective"] == "Lungs clear"
    assert parse_soap_text("") == {k: "" for k in
                                   ["Subjective", "Objective", "Assessment", "Plan"]}


# ----------------------------------------------------- transcript quality ---

def test_quality_no_speech_and_short():
    assert TranscriptionResult(text=NO_SPEECH).quality_warnings() == [
        "No speech was recognized in this audio."
    ]
    warns = TranscriptionResult(text="sakit ulo", duration_s=1.0).quality_warnings()
    assert any("short" in w.lower() for w in warns)


def test_quality_repetition_and_sparse():
    loop = TranscriptionResult(text=" ".join(["ubo"] * 40), duration_s=30).quality_warnings()
    assert any("repetitive" in w.lower() for w in loop)
    sparse = TranscriptionResult(text="usa duha tulo", duration_s=60).quality_warnings()
    assert any("silence" in w.lower() or "little text" in w.lower() for w in sparse)


def test_quality_clean_transcript_no_warnings():
    text = ("Sakit akong ulo sukad gahapon. Wala hilanat pero kapoy kaayo ko. "
            "Normal ra imong blood pressure ug temperature.")
    assert TranscriptionResult(text=text, duration_s=15).quality_warnings() == []


# --------------------------------------------------------------- notes DB ---

def test_notes_db_roundtrip_and_search():
    db.init_db()
    nid = db.create_note(title="Cough case", transcript="ubo tulo ka adlaw",
                         soap={"Assessment": "URTI"}, extract={"chief_complaint": "cough"})
    note = db.get_note(nid)
    assert note["title"] == "Cough case"
    assert note["soap"]["Assessment"] == "URTI"
    assert note["extract"]["chief_complaint"] == "cough"

    db.create_note(title="Headache case", transcript="sakit ulo")
    assert db.count_notes() == 2
    assert [n["title"] for n in db.list_notes(search="cough")] == ["Cough case"]

    db.update_note(nid, title="Renamed")
    assert db.get_note(nid)["title"] == "Renamed"
    db.delete_note(nid)
    assert db.get_note(nid) is None


# --------------------------------------------------------------- export ---

_NOTE = {
    "id": 7, "title": "Cough consult",
    "created_at": "2026-08-28T10:00:00+00:00", "updated_at": "2026-08-28T10:05:00+00:00",
    "duration_s": 42.0, "transcript": "ubo tulo ka adlaw",
    "soap": {"Subjective": "3-day cough", "Objective": "Lungs clear",
             "Assessment": "Likely viral URTI", "Plan": "Hydration"},
    "extract": {"chief_complaint": "cough"},
    "review": {"grounding_score": 5, "completeness_score": 4, "summary": "Well grounded."},
}


def test_export_markdown_and_text():
    md = export.to_markdown(_NOTE)
    assert "# Cough consult" in md and "### Assessment" in md
    assert "Likely viral URTI" in md and "Grounding score: 5/5" in md and md.endswith("\n")
    txt = export.to_text(_NOTE)
    assert "#" not in txt and "**" not in txt and "Likely viral URTI" in txt


def test_export_empty_note_ok():
    assert "SOAP Note #1" in export.to_markdown({"id": 1, "soap": {}, "extract": {}, "review": {}})


# --------------------------------------------------------------- evaluation ---

def test_eval_helpers():
    out = _strip_speaker_tags("Doktor: Unsa? Pasyente: Sakit akong ulo, Dok.")
    assert "Doktor" not in out and "Sakit akong ulo" in out
    assert _normalize("  Sakit,  AKONG   ulo!  ") == "sakit akong ulo"


def test_eval_score_transcription():
    wer, _ = evaluation.score_transcription("sakit akong ulo", "Sakit akong ulo.")
    assert wer == 0.0
    wer, cer = evaluation.score_transcription("sakit akong ulo", "wala akong ubo")
    assert 0.0 < wer <= 1.0 and cer > 0.0
    assert evaluation.score_transcription("", "anything") == (0.0, 0.0)


def test_eval_loads_real_trial_fixtures():
    clips = evaluation.load_reference_clips()
    assert len(clips) == 10
    assert {c.clip_id for c in clips} == {f"1_{i}" for i in range(1, 6)} | {f"2_{i}" for i in range(1, 6)}
    for c in clips:
        assert c.audio_path.exists() and c.reference_text and "Doktor:" not in c.reference_text


def test_eval_aggregate():
    clips = evaluation.load_reference_clips()[:2]
    results = [
        ClipResult(clip=clips[0], wer=0.2, cer=0.1, grounding_score=4, completeness_score=5),
        ClipResult(clip=clips[1], wer=0.4, cer=0.3),
        ClipResult(clip=clips[0], error="boom"),
    ]
    agg = evaluation.aggregate(results)
    assert agg["clips"] == 3 and agg["scored"] == 2 and agg["errors"] == 1
    assert abs(agg["mean_wer"] - 0.3) < 1e-9 and agg["mean_grounding"] == 4


def test_eval_clip_end_to_end_with_mock():
    clip = evaluation.load_reference_clips()[0]
    res = evaluation.evaluate_clip(clip, run_soap=True, run_review=True)
    assert res.error is None
    assert res.hypothesis and res.wer is not None
    assert res.soap and res.grounding_score is not None
