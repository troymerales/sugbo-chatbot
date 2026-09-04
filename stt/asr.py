"""
Speech-to-text using the fine-tuned Whisper checkpoint
``troxyz1268/whisper-small-bisaya``.

The model is loaded from the Hugging Face Hub and inference runs locally
using transformers. No Hugging Face Inference API or dedicated Inference
Endpoint is required.

The model is cached locally after the first download.

Needs:
    transformers
    torch
    librosa
    soundfile

The Hugging Face model can be overridden with:
    BISAYA_WHISPER_MODEL_ID

Example:
    BISAYA_WHISPER_MODEL_ID=troxyz1268/whisper-small-bisaya
"""

from __future__ import annotations

import os
import tempfile

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
    # Load Whisper lazily
    # ---------------------------------------------------------------

    pipe = _load_pipeline()

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
