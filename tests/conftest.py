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
        from api import db
    except ImportError:
        return
    db.reset()


def _reset_retrieval() -> None:
    from core import retrieval

    retrieval.reset_index()


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
    monkeypatch.setattr(config, "DOC_GAP_QUEUE_PATH", tmp_path / "doc_gap_queue.json")
    # Default: no database -> chatlog uses the JSONL file, service uses _MEM.
    # tests/test_db.py overrides DATABASE_URL with a throwaway SQLite file.
    monkeypatch.setattr(config, "DATABASE_URL", None, raising=False)
    monkeypatch.setattr(llm, "_conn", None)  # force a fresh cache connection
    _reset_db()
    _reset_retrieval()
    yield
    monkeypatch.setattr(llm, "_conn", None)
    _reset_db()
    _reset_retrieval()
