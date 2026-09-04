"""stt.gemini — retry/backoff, JSON coercion, mock fixtures, missing-key path."""

from __future__ import annotations

import pytest

import config
from stt import config as stt_config
from stt import gemini
from stt.gemini import LLMUnavailableError, _loads_forgiving, generate_structured
from stt.schemas import ClinicalExtract, GroundingReview, SoapNote


def test_loads_forgiving():
    assert _loads_forgiving('{"a": 1}') == {"a": 1}
    assert _loads_forgiving('```json\n{"a": 1}\n```') == {"a": 1}
    assert _loads_forgiving('```\n{"b": 2}\n```') == {"b": 2}


def test_retry_delay_parses_hints():
    from stt.gemini import _retry_delay

    assert _retry_delay(Exception("Please retry in 8.8s"), 0) == pytest.approx(9.3)
    assert _retry_delay(Exception("... 'retryDelay': '5s' ..."), 0) == pytest.approx(5.5)
    assert _retry_delay(Exception("boom"), 3) == pytest.approx(8.5)


def test_call_with_retry_reraises_non_429():
    from google.genai import errors

    def boom():
        raise errors.ClientError(400, {"error": {"message": "bad request"}})

    with pytest.raises(errors.ClientError):
        gemini._call_with_retry(boom)


def test_call_with_retry_gives_up_on_429(monkeypatch):
    from google.genai import errors

    monkeypatch.setattr(gemini.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise errors.ClientError(429, {"error": {"message": "RESOURCE_EXHAUSTED"}})

    with pytest.raises(gemini.LLMQuotaError):
        gemini._call_with_retry(boom)
    assert calls["n"] == 3


def test_call_with_retry_recovers(monkeypatch):
    from google.genai import errors

    monkeypatch.setattr(gemini.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise errors.ClientError(429, {"error": {"message": "slow down"}})
        return "ok"

    assert gemini._call_with_retry(flaky) == "ok"


def test_mock_backend_returns_typed_fixtures():
    # conftest forces config.LLM_BACKEND = "mock"
    assert isinstance(generate_structured("x", SoapNote), SoapNote)
    assert isinstance(generate_structured("x", ClinicalExtract), ClinicalExtract)
    assert isinstance(generate_structured("x", GroundingReview), GroundingReview)


def test_mock_asr_returns_a_transcript():
    from stt.asr import transcribe

    r = transcribe(b"RIFFxxxx", "audio/wav")
    assert r.text and "mock" in r.text.lower()


def test_missing_key_raises_when_not_mock(monkeypatch):
    monkeypatch.setattr(config, "LLM_BACKEND", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    stt_config.get_settings.cache_clear()
    with pytest.raises(LLMUnavailableError):
        generate_structured("hi", SoapNote)


def test_soap_unavailable_alias():
    assert gemini.SoapUnavailableError is LLMUnavailableError
