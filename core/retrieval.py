"""
Section-level retrieval for RAG mode (`config.USE_RAG`).

When RAG is on, the answer model no longer sees the whole documentation — only
the top-K most relevant `##` / `###` sections for the current question, ranked
by embedding cosine similarity. The verification pass (`grounding.verify`) and
the eval judge still read the full docs, so both modes stay drop-in compatible.

Zero extra dependencies: it reuses `llm.embed()` (which is itself cached to
SQLite) plus a plain Python cosine. `ChromaDB` / `FAISS` would be the next step
if the doc set grew past a few hundred sections; at ~40 sections a linear scan
is instant.
"""

from __future__ import annotations

import functools

import config
from core import knowledge, llm


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


@functools.lru_cache(maxsize=1)
def _section_index() -> tuple[tuple[knowledge.Section, tuple[float, ...]], ...]:
    """Every content section paired with its embedding. Built once per process."""
    secs = knowledge.content_sections()
    vecs = llm.embed([f"{s.title}\n\n{s.body}" for s in secs])
    return tuple((sec, tuple(vec)) for sec, vec in zip(secs, vecs))


def reset_index() -> None:
    """Drop the cached section embeddings (call after changing backend/docs)."""
    _section_index.cache_clear()


def rank_sections(query: str) -> list[tuple[knowledge.Section, float]]:
    """All sections, most relevant first, with their cosine score."""
    qvec = llm.embed([query])[0]
    scored = [(sec, _cosine(qvec, list(vec))) for sec, vec in _section_index()]
    scored.sort(key=lambda t: t[1], reverse=True)
    return scored


def top_sections(query: str, k: int | None = None) -> list[knowledge.Section]:
    k = k or config.RAG_TOP_K
    return [sec for sec, _ in rank_sections(query)[:k]]
