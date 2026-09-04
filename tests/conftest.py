"""
Shared test setup.

Every test runs against the offline mock backend with a throwaway cache and log
directory, so the suite needs no API key, spends no quota, and never touches
logs/ or the real llm_cache.sqlite.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from core import llm  # noqa: E402


def _reset_db() -> None:
    try:
        from core import chatlog_db as db
    except ImportError:
        return
    db.reset()


def _reset_retrieval() -> None:
    from core import retrieval

    retrieval.reset_index()


def _reset_stt() -> None:
    try:
        from stt import config as stt_config
    except ImportError:
        return
    stt_config.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LLM_BACKEND", "mock")
    monkeypatch.setattr(config, "LLM_CACHE", True)
    monkeypatch.setattr(config, "LLM_OFFLINE", False)
    monkeypatch.setattr(config, "USE_RAG", False)
    monkeypatch.setattr(config, "LLM_CACHE_PATH", tmp_path / "cache.sqlite")
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "CHAT_LOG_PATH", tmp_path / "chats.jsonl")
    monkeypatch.setattr(config, "CHAT_LOG_CSV_PATH", tmp_path / "chats.csv")
    # Default: no database -> chatlog uses the JSONL file.
    monkeypatch.setattr(config, "DATABASE_URL", None, raising=False)
    monkeypatch.setattr(llm, "_conn", None)  # force a fresh cache connection
    # STT side: throwaway notes DB, mock ASR/SOAP (via config.LLM_BACKEND above).
    monkeypatch.setenv("BISAYA_DB_PATH", str(tmp_path / "soap_notes.db"))
    # Never let a page's load_secrets() pull the real .streamlit/secrets.toml
    # into os.environ during tests — the suite controls its own env.
    try:
        import assistant.bootstrap as _bootstrap

        monkeypatch.setattr(_bootstrap, "_DONE", True, raising=False)
    except ImportError:
        pass
    _reset_db()
    _reset_retrieval()
    _reset_stt()
    yield
    monkeypatch.setattr(llm, "_conn", None)
    _reset_db()
    _reset_retrieval()
    _reset_stt()
