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
import llm  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LLM_BACKEND", "mock")
    monkeypatch.setattr(config, "LLM_CACHE", True)
    monkeypatch.setattr(config, "LLM_OFFLINE", False)
    monkeypatch.setattr(config, "LLM_CACHE_PATH", tmp_path / "cache.sqlite")
    monkeypatch.setattr(config, "LOG_DIR", tmp_path)
    monkeypatch.setattr(config, "CHAT_LOG_PATH", tmp_path / "chats.jsonl")
    monkeypatch.setattr(config, "DOC_GAP_QUEUE_PATH", tmp_path / "doc_gap_queue.json")
    monkeypatch.setattr(llm, "_conn", None)  # force a fresh cache connection
    yield
    monkeypatch.setattr(llm, "_conn", None)
