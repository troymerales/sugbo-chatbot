"""
Gemini wrapper for the STT side: structured SOAP / extract / review output.
(Transcription does NOT go through here — see ``stt.asr``.) One place for the
missing-key case, 429 retry/backoff, and JSON coercion.

Shares the chatbot's Gemini client (one key, one client) and honours
``config.LLM_BACKEND == "mock"`` so the whole test-suite + AppTests run offline.
"""

from __future__ import annotations

import json
import re
import time
from typing import Callable, TypeVar

from pydantic import BaseModel

import config  # chatbot root config — for LLM_BACKEND
from stt.config import get_settings
from stt.schemas import ClinicalExtract, GroundingReview, NOT_ENOUGH, SoapNote

T = TypeVar("T", bound=BaseModel)

_MAX_RETRIES = 3
_MAX_BACKOFF_S = 30.0

LLM_EXHAUSTED_MESSAGE = "LLM is exhausted today. Please try again in 24 hours."


class LLMUnavailableError(Exception):
    """No API key — the call can't even be attempted."""


class LLMQuotaError(Exception):
    """Repeated 429s (rate limit / quota) — the Gemini free tier is ~20 req/day per model."""


# Back-compat alias (old code raised ``soap_infer.SoapUnavailableError``).
SoapUnavailableError = LLMUnavailableError


def _mock() -> bool:
    return getattr(config, "LLM_BACKEND", "gemini") == "mock"


def _client():
    settings = get_settings()
    if not settings.gemini_api_key:
        raise LLMUnavailableError(
            "GEMINI_API_KEY is not set -- add it to .streamlit/secrets.toml (or .env), "
            "or paste one in the sidebar."
        )
    # Reuse the chatbot's cached client so the whole app shares one key/client.
    from core._gemini_backend import _client as _shared_client

    return _shared_client()


def _retry_delay(exc: Exception, attempt: int) -> float:
    m = re.search(r"retry in ([0-9.]+)s", str(exc), re.IGNORECASE)
    if not m:
        m = re.search(r"'retryDelay': '([0-9.]+)s'", str(exc))
    hint = float(m.group(1)) if m else 2.0 ** attempt
    return min(hint + 0.5, _MAX_BACKOFF_S)


def _call_with_retry(fn: Callable[[], T]) -> T:
    from google.genai import errors

    last: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            return fn()
        except errors.ClientError as e:
            last = e
            if getattr(e, "code", None) != 429:
                raise
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_retry_delay(e, attempt))
    raise LLMQuotaError(
        "Gemini quota / rate limit exceeded (HTTP 429). The free tier allows only "
        "~20 requests/day per model -- wait, switch the model, or enable billing."
    ) from last


def _loads_forgiving(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return json.loads(text)


# --------------------------------------------------------------------------- #
# Mock fixtures (offline test path)
# --------------------------------------------------------------------------- #

def _mock_structured(model: type[T]) -> T:
    if model is SoapNote:
        return SoapNote(  # type: ignore[return-value]
            subjective="Patient reports headache since yesterday, with fatigue. [mock]",
            objective=NOT_ENOUGH,
            assessment="Likely tension headache. [mock]",
            plan="Rest, hydration, return if symptoms worsen. [mock]",
        )
    if model is ClinicalExtract:
        return ClinicalExtract(  # type: ignore[return-value]
            chief_complaint="headache [mock]", duration="1 day",
            associated_symptoms=["fatigue"], diagnoses=["tension headache"],
        )
    if model is GroundingReview:
        return GroundingReview(  # type: ignore[return-value]
            grounding_score=4, completeness_score=4,
            summary="Mostly grounded in the transcript. [mock]",
        )
    return model()


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def generate_text(prompt: str, *, model: str | None = None, temperature: float = 0.3) -> str:
    if _mock():
        return "(mock text)"
    from google.genai import types

    client = _client()

    def _do():
        return client.models.generate_content(
            model=model or get_settings().soap_model_id,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=temperature),
        )

    return (_call_with_retry(_do).text or "").strip()


def generate_structured(prompt: str, response_model: type[T], *,
                        model: str | None = None, temperature: float = 0.2) -> T:
    """Call Gemini in JSON mode and validate against ``response_model``."""
    if _mock():
        return _mock_structured(response_model)
    from google.genai import types

    client = _client()

    def _do():
        return client.models.generate_content(
            model=model or get_settings().soap_model_id,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=temperature,
                response_mime_type="application/json",
                response_schema=response_model,
            ),
        )

    resp = _call_with_retry(_do)
    parsed = getattr(resp, "parsed", None)
    if isinstance(parsed, response_model):
        return parsed
    if isinstance(parsed, dict):
        return response_model.model_validate(parsed)
    return response_model.model_validate(_loads_forgiving((resp.text or "").strip()))
