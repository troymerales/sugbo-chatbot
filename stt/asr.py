"""
Speech-to-text using the fine-tuned Whisper checkpoint
``troxyz1268/whisper-small-bisaya``.

Two backends, picked automatically:

  * **local** — if ``transformers`` is importable, the model runs in-process
    (fast, no per-call network hop; good for local dev). Needs ``transformers``,
    ``torch``, ``librosa``, ``soundfile``.
  * **Hugging Face Inference API** — the fallback when ``transformers`` is not
    installed. This is the deployed path: Streamlit Community Cloud has no
    torch, so ``requirements.txt`` omits it and transcription is a hosted call
    to ``HF_INFERENCE_URL`` + the model id, authorised with ``HF_TOKEN``.

The model is cached locally after the first download (local backend only).

The Hugging Face model can be overridden with:
    BISAYA_WHISPER_MODEL_ID

Example:
    BISAYA_WHISPER_MODEL_ID=troxyz1268/whisper-small-bisaya
"""

from __future__ import annotations

import importlib.util
import os
import tempfile
import time

import config  # chatbot root — for LLM_BACKEND (mock in tests)
from stt.config import get_settings
from stt.quality import NO_SPEECH, TranscriptionResult


_MOCK_TRANSCRIPT = (
    "Unsa man imong gibati karon? Sakit akong ulo sukad gahapon, Dok. "
    "Naay hilanat? Wala, pero kapoy kaayo ko. [mock transcript]"
)


# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------

MODEL_ID = os.environ.get(
    "BISAYA_WHISPER_MODEL_ID",
    "troxyz1268/whisper-small-bisaya",
)

# Whisper's closest language code for Bisaya/Cebuano.
# This matches the language setting used during training/evaluation.
LANGUAGE = "tl"


_pipe = None
_load_error = None


def _load_pipeline():
    """
    Lazily load the Whisper pipeline.

    The model is loaded only when transcription is first requested rather
    than when the Streamlit application starts.
    """
    global _pipe, _load_error

    if _load_error is not None:
        raise RuntimeError(_load_error)

    if _pipe is not None:
        return _pipe

    # No torch/transformers in this environment (the deployed case) -> signal the
    # caller to use the HF Inference API instead of failing.
    if importlib.util.find_spec("transformers") is None:
        return None

    try:
        from transformers import pipeline

        _pipe = pipeline(
            "automatic-speech-recognition",
            model=MODEL_ID,
            chunk_length_s=30,
            stride_length_s=5,
        )

        return _pipe

    except Exception as e:
        _load_error = (
            f"Failed to load Whisper model ({MODEL_ID}): {e}"
        )
        raise RuntimeError(_load_error) from e


def is_available() -> bool:
    """
    Check whether Whisper is available.

    The model is loaded lazily, so this returns True unless a previous
    loading attempt has already failed.
    """
    return _load_error is None


def transcribe(
    audio_bytes: bytes,
    mime_type: str,
    *,
    duration_s: float | None = None,
) -> TranscriptionResult:
    """
    Transcribe audio bytes using the locally loaded fine-tuned Whisper model.

    Parameters
    ----------
    audio_bytes:
        Raw audio data.

    mime_type:
        MIME type of the audio, e.g. ``audio/wav`` or ``audio/webm``.
        The MIME type is currently used only to determine a reasonable
        temporary file suffix.

    duration_s:
        Optional duration of the recording in seconds.

    Returns
    -------
    TranscriptionResult
        Structured transcription result used by the rest of the application.
    """

    s = get_settings()

    # ---------------------------------------------------------------
    # Mock mode
    # ---------------------------------------------------------------

    if getattr(config, "LLM_BACKEND", "gemini") == "mock":
        return TranscriptionResult(
            text=_MOCK_TRANSCRIPT,
            duration_s=duration_s,
            model_id=MODEL_ID,
            language=LANGUAGE,
        )

    if not audio_bytes:
        return TranscriptionResult(
            text=NO_SPEECH,
            duration_s=duration_s,
            model_id=MODEL_ID,
            language=LANGUAGE,
        )

    # ---------------------------------------------------------------
    # Load Whisper lazily — or fall back to the HF Inference API
    # ---------------------------------------------------------------

    pipe = _load_pipeline()
    if pipe is None:
        return _transcribe_via_api(audio_bytes, mime_type, duration_s=duration_s)

    # ---------------------------------------------------------------
    # Write the uploaded/recorded audio to a temporary file
    # ---------------------------------------------------------------
    #
    # transformers' ASR pipeline accepts a local audio path.
    #
    # Streamlit's uploaded/recorded audio arrives here as bytes, so we
    # temporarily write those bytes to disk and pass the path to Whisper.
    #

    suffix = _get_audio_suffix(mime_type)

    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(
            suffix=suffix,
            delete=False,
        ) as temp_file:
            temp_file.write(audio_bytes)
            temp_path = temp_file.name

        # -----------------------------------------------------------
        # Run Whisper
        # -----------------------------------------------------------

        result = pipe(
            temp_path,
            generate_kwargs={
                "language": LANGUAGE,
                "task": "transcribe",
            },
        )

        text = ""

        if isinstance(result, dict):
            text = result.get("text", "") or ""

        text = text.strip()

        return TranscriptionResult(
            text=text or NO_SPEECH,
            duration_s=duration_s,
            model_id=MODEL_ID,
            language=LANGUAGE,
        )

    except Exception as e:
        raise RuntimeError(
            f"Whisper transcription failed ({MODEL_ID}): {e}"
        ) from e

    finally:
        # Always remove the temporary audio file.
        if temp_path is not None:
            try:
                os.remove(temp_path)
            except OSError:
                pass


_API_TIMEOUT_S = 120
_API_MAX_ATTEMPTS = 8
_API_COLD_WAIT_CAP_S = 20


def _transcribe_via_api(
    audio_bytes: bytes,
    mime_type: str,
    *,
    duration_s: float | None = None,
) -> TranscriptionResult:
    """Transcribe by POSTing the raw audio to a hosted endpoint.

    Used when ``transformers`` isn't installed (the deployed environment).
    Prefers ``ASR_API_URL`` — the HF Space in ``deploy/asr-space/``, which
    answers ``{"text": ...}`` at ``/transcribe`` — and falls back to the legacy
    ``HF_INFERENCE_URL`` + model-id path. A sleeping Space or a cold model
    returns 5xx / a non-JSON "starting" page for a bit, so we retry.
    """
    import requests  # in requirements.txt; transformers is not

    s = get_settings()
    content_type = (mime_type or "").split(";")[0].strip() or "audio/webm"

    if s.asr_api_url:
        url = s.asr_api_url
        token = s.asr_auth_token or s.hf_token
        headers = {"Content-Type": content_type, "Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        source = "ASR endpoint"
    elif s.hf_token:
        url = s.hf_inference_url.rstrip("/") + "/" + s.whisper_model_id
        headers = {
            "Authorization": f"Bearer {s.hf_token}",
            "Content-Type": content_type,
            "Accept": "application/json",
            "X-Wait-For-Model": "true",
        }
        source = "HF Inference API"
    else:
        raise RuntimeError(
            "No transcription backend in this environment: set ASR_API_URL "
            "(a Whisper endpoint) or install `transformers` for local Whisper."
        )

    last_detail = "no response"
    for attempt in range(_API_MAX_ATTEMPTS):
        try:
            resp = requests.post(url, headers=headers, data=audio_bytes,
                                 timeout=_API_TIMEOUT_S)
        except requests.RequestException as e:
            last_detail = f"request error: {e}"
            time.sleep(min(3 * (attempt + 1), _API_COLD_WAIT_CAP_S))
            continue

        # 503 with estimated_time = HF model loading; 5xx / 429 = Space waking
        # or rate limited — all worth another try after a wait.
        if resp.status_code in (429, 500, 502, 503, 504):
            wait = 5.0
            try:
                wait = float(resp.json().get("estimated_time", wait))
            except Exception:  # noqa: BLE001
                pass
            last_detail = f"{resp.status_code} (retrying)"
            time.sleep(min(wait, _API_COLD_WAIT_CAP_S))
            continue
        if not resp.ok:
            raise RuntimeError(
                f"{source} returned {resp.status_code}: {resp.text[:300]}"
            )

        text, ok = _parse_api_text(resp)
        if not ok:
            last_detail = "non-JSON response (endpoint still starting?)"
            time.sleep(_API_COLD_WAIT_CAP_S)
            continue
        return TranscriptionResult(
            text=text or NO_SPEECH,
            duration_s=duration_s,
            model_id=s.whisper_model_id,
            language=LANGUAGE,
        )

    raise RuntimeError(
        f"{source} did not return a transcript after "
        f"{_API_MAX_ATTEMPTS} attempts ({last_detail})."
    )


def _parse_api_text(resp) -> tuple[str, bool]:
    """``(text, ok)`` from an ASR response.

    ``{"text": "..."}`` (our Space) or a one-element list of the same (some HF
    pipelines). ``ok`` is False when the body isn't JSON at all — usually a
    Space that hasn't finished booting.
    """
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        return "", False
    if isinstance(body, list) and body:
        body = body[0]
    if isinstance(body, dict):
        return str(body.get("text", "")).strip(), True
    return "", True


def _get_audio_suffix(mime_type: str) -> str:
    """
    Convert an audio MIME type into a reasonable temporary file extension.

    This matters because microphone recordings from browsers are often
    WebM/Opus rather than WAV.
    """

    mime_type = (mime_type or "").lower().split(";")[0].strip()

    suffixes = {
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/wave": ".wav",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/mp4": ".m4a",
        "audio/x-m4a": ".m4a",
        "audio/ogg": ".ogg",
        "audio/opus": ".opus",
        "audio/webm": ".webm",
        "audio/webm;codecs=opus": ".webm",
    }

    return suffixes.get(mime_type, ".wav")
