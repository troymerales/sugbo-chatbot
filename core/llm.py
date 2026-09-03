"""
The one interface every component uses to talk to a language model.

Three things sit behind these functions:
  1. a backend  — `gemini` (real API) or `mock` (_mock_backend.py, offline).
  2. a cache    — every response is stored in logs/llm_cache.sqlite keyed by a
                  hash of the request; re-runs on unchanged input cost nothing.
  3. offline    — config.LLM_OFFLINE makes a cache miss raise instead of calling
                  out, so you can work against a warm cache with zero quota.

config.LLM_BACKEND / LLM_CACHE / LLM_OFFLINE are read on *every* call, so a script
can flip them at runtime (see eval_run.py --offline / --mock).

Public API:
    generate(prompt, system=?, model=?, temperature=?, json_mode=?) -> str
    new_chat(system, model=?, temperature=?) -> Chat        # Chat.send(text) -> str
    embed(texts, model=?) -> list[list[float]]
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass, field

import config


class LLMError(RuntimeError):
    """Any failure talking to the model, normalised so callers catch one type."""


class QuotaError(RuntimeError):
    """A 429 that looks like a daily quota — retrying within the run won't help.

    Deliberately NOT an LLMError: it propagates past per-call `except LLMError`
    handlers and stops the whole run with a clear message.
    """


class OfflineCacheMiss(LLMError):
    """config.LLM_OFFLINE is set and the request was not in the cache."""


# --------------------------------------------------------------------------- #
# Retry (used by the gemini backend)
# --------------------------------------------------------------------------- #

def _retry_delay_from(msg: str) -> float | None:
    m = re.search(r"retry(?:Delay)?['\"]?[:\s]+['\"]?(\d+(?:\.\d+)?)s", msg)
    if m:
        return float(m.group(1))
    m = re.search(r"retry in (\d+(?:\.\d+)?)s", msg)
    return float(m.group(1)) if m else None


def retry(fn, *, tries: int = 4, base_delay: float = 2.0):
    last = None
    for attempt in range(tries):
        try:
            return fn()
        except (QuotaError, OfflineCacheMiss):
            raise
        except Exception as exc:  # noqa: BLE001
            last = exc
            msg = str(exc)
            if "PerDay" in msg or "RequestsPerDay" in msg:
                raise QuotaError(
                    "Daily Gemini quota exhausted for this model. Enable billing, "
                    "switch GEMINI_MODEL/GEMINI_JUDGE_MODEL to a model with quota "
                    "left, run with --mock, or resume tomorrow.\n" + msg[:300]
                ) from exc
            if attempt < tries - 1:
                wait = _retry_delay_from(msg)
                time.sleep(min(wait, 60) if wait else base_delay * (attempt + 1))
    raise LLMError(str(last)) from last


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #

_conn: sqlite3.Connection | None = None


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(config.LLM_CACHE_PATH, check_same_thread=False)
        _conn.execute(
            "CREATE TABLE IF NOT EXISTS cache "
            "(key TEXT PRIMARY KEY, kind TEXT, backend TEXT, value TEXT, created REAL)"
        )
        _conn.commit()
    return _conn


def _key(kind: str, payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(f"{kind}\x00{blob}".encode()).hexdigest()


def _cache_get(key: str):
    row = _db().execute("SELECT value FROM cache WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def _cache_put(key: str, kind: str, value) -> None:
    _db().execute(
        "INSERT OR REPLACE INTO cache VALUES (?, ?, ?, ?, ?)",
        (key, kind, config.LLM_BACKEND, json.dumps(value, ensure_ascii=False), time.time()),
    )
    _db().commit()


def cache_stats() -> dict:
    cur = _db().execute("SELECT kind, COUNT(*) FROM cache GROUP BY kind")
    by_kind = dict(cur.fetchall())
    return {"path": str(config.LLM_CACHE_PATH), "total": sum(by_kind.values()), "by_kind": by_kind}


def clear_cache() -> int:
    n = _db().execute("SELECT COUNT(*) FROM cache").fetchone()[0]
    _db().execute("DELETE FROM cache")
    _db().commit()
    return n


def _cached(kind: str, payload: dict, produce):
    """Shared cache/offline/produce flow for generate() and embed()."""
    key = _key(kind, {**payload, "backend": config.LLM_BACKEND})
    if config.LLM_CACHE:
        hit = _cache_get(key)
        if hit is not None:
            return hit
    if config.LLM_OFFLINE:
        raise OfflineCacheMiss(
            f"offline: no cached {kind} response for this request. "
            "Run once online (or with --mock) to warm the cache."
        )
    value = produce()
    if config.LLM_CACHE:
        _cache_put(key, kind, value)
    return value


# --------------------------------------------------------------------------- #
# Backend dispatch
# --------------------------------------------------------------------------- #

def _backend_generate(*, contents: list[dict], system: str | None, model: str,
                      temperature: float, json_mode: bool) -> str:
    if config.LLM_BACKEND == "mock":
        from core import _mock_backend
        return _mock_backend.generate(contents=contents, system=system, json_mode=json_mode)
    from core import _gemini_backend
    return retry(lambda: _gemini_backend.generate(
        contents=contents, system=system, model=model,
        temperature=temperature, json_mode=json_mode,
    ))


def _backend_generate_stream(*, contents: list[dict], system: str | None,
                             model: str, temperature: float):
    """Yield answer text chunks. No retry() wrapper: a mid-stream failure can't
    be retried cleanly, so it is normalised to LLMError and raised to the caller
    (the widget shows a fallback line; verification still runs on what arrived)."""
    if config.LLM_BACKEND == "mock":
        from core import _mock_backend
        yield from _mock_backend.generate_stream(contents=contents, system=system)
        return
    from core import _gemini_backend
    try:
        yield from _gemini_backend.generate_stream(
            contents=contents, system=system, model=model, temperature=temperature,
        )
    except Exception as exc:  # noqa: BLE001 - normalise like retry() does
        msg = str(exc)
        if "PerDay" in msg or "RequestsPerDay" in msg:
            raise QuotaError("Daily Gemini quota exhausted.\n" + msg[:300]) from exc
        raise LLMError(msg) from exc


def _backend_embed(texts: list[str], model: str) -> list[list[float]]:
    if config.LLM_BACKEND == "mock":
        from core import _mock_backend
        return _mock_backend.embed(texts)
    from core import _gemini_backend
    return retry(lambda: _gemini_backend.embed(texts, model))


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def generate(prompt: str, *, system: str | None = None, model: str | None = None,
             temperature: float = 0.2, json_mode: bool = False) -> str:
    model = model or config.ANSWER_MODEL
    contents = [{"role": "user", "text": prompt}]
    payload = {"contents": contents, "system": system, "model": model,
               "temperature": temperature, "json_mode": json_mode}
    return _cached("generate", payload, lambda: _backend_generate(
        contents=contents, system=system, model=model,
        temperature=temperature, json_mode=json_mode,
    ))


@dataclass
class Chat:
    """A multi-turn conversation. History is plain data so it caches and pickles."""
    system: str
    model: str
    temperature: float = 0.2
    history: list[dict] = field(default_factory=list)  # [{"role": "user"|"model", "text": ...}]

    def send(self, text: str) -> str:
        self.history.append({"role": "user", "text": text})
        payload = {"contents": self.history, "system": self.system,
                   "model": self.model, "temperature": self.temperature}
        reply = _cached("generate", {**payload, "json_mode": False},
                        lambda: _backend_generate(
                            contents=self.history, system=self.system, model=self.model,
                            temperature=self.temperature, json_mode=False,
                        ))
        self.history.append({"role": "model", "text": reply})
        return reply

    def send_stream(self, text: str):
        """Streaming sibling of send(): yield reply chunks as they arrive, then
        record the full reply in history and the cache. A cache hit is replayed
        as one chunk. Keyed identically to send() so the two share cache entries.
        """
        self.history.append({"role": "user", "text": text})
        key = _key("generate", {
            "contents": self.history, "system": self.system, "model": self.model,
            "temperature": self.temperature, "json_mode": False,
            "backend": config.LLM_BACKEND,
        })
        if config.LLM_CACHE:
            hit = _cache_get(key)
            if hit is not None:
                self.history.append({"role": "model", "text": hit})
                yield hit
                return
        if config.LLM_OFFLINE:
            raise OfflineCacheMiss(
                "offline: no cached response for this message. Warm the cache "
                "with a live (or --mock) run first."
            )
        chunks: list[str] = []
        for piece in _backend_generate_stream(
            contents=self.history, system=self.system,
            model=self.model, temperature=self.temperature,
        ):
            chunks.append(piece)
            yield piece
        reply = "".join(chunks)
        self.history.append({"role": "model", "text": reply})
        if config.LLM_CACHE and reply:
            _cache_put(key, "generate", reply)


def new_chat(system: str, *, model: str | None = None, temperature: float = 0.2) -> Chat:
    return Chat(system=system, model=model or config.ANSWER_MODEL, temperature=temperature)


def embed(texts: list[str], *, model: str | None = None) -> list[list[float]]:
    if not texts:
        return []
    model = model or config.EMBED_MODEL
    return _cached("embed", {"texts": texts, "model": model},
                   lambda: _backend_embed(texts, model))
