"""
Settings for the STT -> SOAP pipeline. Self-contained: reads only ``os.environ``
(which ``assistant.bootstrap.load_secrets`` populates from ``st.secrets``), so it
stays decoupled from the chatbot's root ``config.py``.

Transcription is the fine-tuned Whisper checkpoint via the Hugging Face
Inference API (no torch, no Gemini). Gemini is used only for the SOAP note /
extract / review steps.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_WHISPER_MODEL = "troxyz1268/whisper-small-bisaya"
DEFAULT_SOAP_MODEL = "gemini-3.6-flash"
DEFAULT_HF_INFERENCE_URL = "https://api-inference.huggingface.co/models/"


@dataclass(frozen=True)
class Settings:
    whisper_model_id: str       # the fine-tuned checkpoint (HF)
    hf_inference_url: str        # base URL for the HF Inference API (override for endpoints)
    hf_token: str | None
    soap_model_id: str          # Gemini model for SOAP / extract / review
    gemini_api_key: str | None
    asr_language: str
    db_path: Path
    trial_dir: Path

    @property
    def llm_available(self) -> bool:
        """Gemini configured — SOAP / extract / review are usable."""
        return bool(self.gemini_api_key)

    @property
    def asr_available(self) -> bool:
        """HF token configured — transcription is usable."""
        return bool(self.hf_token)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        whisper_model_id=os.environ.get("BISAYA_WHISPER_MODEL_ID") or DEFAULT_WHISPER_MODEL,
        hf_inference_url=(os.environ.get("HF_INFERENCE_URL")
                          or DEFAULT_HF_INFERENCE_URL).rstrip("/") + "/",
        hf_token=(os.environ.get("HF_TOKEN")
                  or os.environ.get("HUGGINGFACE_TOKEN") or "").strip() or None,
        soap_model_id=(os.environ.get("BISAYA_SOAP_MODEL_ID")
                       or os.environ.get("GEMINI_MODEL") or DEFAULT_SOAP_MODEL),
        gemini_api_key=(os.environ.get("GEMINI_API_KEY") or "").strip() or None,
        # "tl" (Tagalog) is Whisper's closest code to Bisaya/Cebuano and how the
        # checkpoint was fine-tuned.
        asr_language=(os.environ.get("BISAYA_ASR_LANGUAGE") or "tl").strip(),
        db_path=Path(os.environ.get("BISAYA_DB_PATH") or (ROOT / "soap_notes.db")),
        trial_dir=Path(os.environ.get("BISAYA_TRIAL_DIR") or (ROOT / "trial")),
    )


def reload_settings() -> Settings:
    """Drop the cache and re-read the environment — used by the sidebar control
    that lets a user paste an API key at runtime."""
    get_settings.cache_clear()
    return get_settings()
