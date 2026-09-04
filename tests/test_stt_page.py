"""
The STT Streamlit pages, driven through AppTest with the mock backend. AppTest
can't inject an uploaded file, so transcription is exercised via stt.evaluation
in test_stt_core.py; here we seed a transcript and drive SOAP / save.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from streamlit.testing.v1 import AppTest

_PAGES = Path(__file__).parents[1] / "pages"
_TRANSCRIPT = str(_PAGES / "1_Consultation_Transcript.py")
_PAST = str(_PAGES / "2_Past_Notes.py")
_EVAL = str(_PAGES / "3_Evaluation.py")


@pytest.fixture(autouse=True)
def _gemini_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    from stt import config as sc

    sc.get_settings.cache_clear()
    yield
    sc.get_settings.cache_clear()


def _btn(at, label):
    return next(b for b in at.button if b.label == label)


def test_consultation_page_renders():
    at = AppTest.from_file(_TRANSCRIPT, default_timeout=60).run()
    assert not at.exception
    assert any("Consultation Transcript" in h.value for h in at.title)


def test_generate_soap_then_save_creates_a_note():
    at = AppTest.from_file(_TRANSCRIPT, default_timeout=60)
    at.session_state["work"] = {
        "transcript": "Doctor: Unsa man imong gibati? Patient: Sakit akong ulo sukad gahapon.",
        "soap": {"Subjective": "", "Objective": "", "Assessment": "", "Plan": ""},
        "extract": {}, "review": {}, "audio_filename": "a.wav",
        "duration_s": 6.0, "saved_id": None, "warnings": [],
    }
    at.run()
    assert not at.exception

    _btn(at, "Generate SOAP").click().run()
    assert not at.exception
    assert at.session_state["work"]["soap"]["Subjective"]      # mock filled it

    _btn(at, "Extract structured data").click().run()
    assert at.session_state["work"]["extract"].get("chief_complaint")

    _btn(at, "Save to database").click().run()
    assert not at.exception

    from stt import notes_db
    assert notes_db.count_notes() == 1
    assert at.session_state["work"]["saved_id"] is not None


def test_past_notes_empty_state():
    at = AppTest.from_file(_PAST, default_timeout=60).run()
    assert not at.exception


def test_past_notes_shows_a_saved_note():
    from stt import notes_db

    notes_db.init_db()
    notes_db.create_note(title="Cough consult", transcript="ubo tulo ka adlaw",
                         soap={"Assessment": "URTI"})
    at = AppTest.from_file(_PAST, default_timeout=60).run()
    assert not at.exception
    assert any("Cough consult" in str(df.value.to_dict()) for df in at.dataframe)


def test_evaluation_page_renders():
    at = AppTest.from_file(_EVAL, default_timeout=60).run()
    assert not at.exception
    assert any("reference clips" in str(m.value) for m in at.markdown)
