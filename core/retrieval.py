"""
Section-level retrieval for RAG mode (`config.USE_RAG`).

When RAG is on, the answer model no longer sees the whole documentation — only
the top-K most relevant `##` / `###` sections for the current question, ranked
by embedding cosine similarity. The verification pass (`grounding.verify`) and
the eval judge still read the full docs, so both modes stay drop-in compatible.

The embeddings live in a persistent ChromaDB collection under
`config.VECTOR_DIR`: built once, reused across restarts, and queried for K
neighbours instead of scored against every section. `VECTOR_BACKEND=memory`
swaps in the original in-process linear scan, which is what the test suite runs.

A stamped `config.EMBEDDINGS_SEED_PATH` supplies the section vectors when it
matches, so a cold start builds the index without spending embedding quota.

The collection is stamped with a fingerprint of (docs, LLM backend, embed
model). Change any of those and the index is dropped and rebuilt — that is what
stops a 256-dim mock index from being queried with a 3072-dim Gemini vector.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging

import config
from core import knowledge, llm

log = logging.getLogger(__name__)

_COLLECTION = "sections"


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _embed_text(sec: knowledge.Section) -> str:
    return f"{sec.title}\n\n{sec.body}"


def fingerprint() -> str:
    """What an index was built from. Any change to these invalidates it."""
    h = hashlib.sha256()
    for part in (config.LLM_BACKEND, config.EMBED_MODEL, knowledge.load_docs()):
        h.update(part.encode())
        h.update(b"\0")
    return h.hexdigest()[:16]


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #

def _seed_vectors(
    secs: tuple[knowledge.Section, ...], fp: str
) -> list[list[float]] | None:
    """Pre-computed embeddings for exactly these sections, or None.

    The seed file records the fingerprint it was generated under, so edited
    docs or a different embedding model fall through to embedding again rather
    than silently indexing stale vectors.
    """
    path = config.EMBEDDINGS_SEED_PATH
    if not path or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload["fingerprint"] != fp:
            log.info("%s was built for other docs/model; re-embedding.", path.name)
            return None
        vectors = payload["vectors"]
        return [vectors[sec.slug] for sec in secs]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.warning("ignoring embedding seed %s: %s", path, exc)
        return None


@functools.lru_cache(maxsize=1)
def _memory_index() -> tuple[tuple[knowledge.Section, tuple[float, ...]], ...]:
    """Every content section paired with its embedding. Built once per process."""
    secs = knowledge.content_sections()
    vecs = _seed_vectors(secs, fingerprint())
    if vecs is None:
        vecs = llm.embed([_embed_text(s) for s in secs])
    return tuple((sec, tuple(vec)) for sec, vec in zip(secs, vecs))


_collection_cache: tuple[str, object] | None = None  # (fingerprint, collection)


def _collection():
    """The Chroma collection of section embeddings, indexed on first use."""
    global _collection_cache
    fp = fingerprint()
    if _collection_cache is not None and _collection_cache[0] == fp:
        return _collection_cache[1]

    import chromadb

    config.VECTOR_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(config.VECTOR_DIR))
    coll = client.get_or_create_collection(name=_COLLECTION)

    if (coll.metadata or {}).get("fingerprint") != fp or coll.count() == 0:
        client.delete_collection(_COLLECTION)
        coll = client.create_collection(
            name=_COLLECTION,
            metadata={"hnsw:space": "cosine", "fingerprint": fp},
        )
        secs = knowledge.content_sections()
        vecs = _seed_vectors(secs, fp)
        if vecs is None:
            vecs = llm.embed([_embed_text(s) for s in secs])
        # Ordinal ids rather than slugs: two headings can slugify identically,
        # and the fingerprint already pins this ordering to this exact doc text.
        coll.add(
            ids=[str(i) for i in range(len(secs))],
            embeddings=vecs,
            metadatas=[{"title": s.title, "slug": s.slug} for s in secs],
        )

    _collection_cache = (fp, coll)
    return coll


def _search(qvec: list[float], k: int) -> list[tuple[knowledge.Section, float]]:
    """The k best sections for an already-embedded query, most relevant first."""
    secs = knowledge.content_sections()
    k = max(1, min(k, len(secs)))

    if config.VECTOR_BACKEND == "memory":
        scored = [(sec, _cosine(qvec, list(vec))) for sec, vec in _memory_index()]
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:k]

    res = _collection().query(
        query_embeddings=[qvec], n_results=k, include=["distances"]
    )
    # Chroma returns nearest-first cosine *distance*; similarity is 1 - distance.
    return [
        (secs[int(i)], 1.0 - dist)
        for i, dist in zip(res["ids"][0], res["distances"][0])
    ]


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def reset_index() -> None:
    """Drop the cached section index (call after changing backend/docs)."""
    global _collection_cache
    _memory_index.cache_clear()
    _collection_cache = None


def rank_sections(query: str) -> list[tuple[knowledge.Section, float]]:
    """All sections, most relevant first, with their cosine score."""
    return _search(llm.embed([query])[0], len(knowledge.content_sections()))


def top_sections(query: str, k: int | None = None) -> list[knowledge.Section]:
    k = k or config.RAG_TOP_K
    return [sec for sec, _ in _search(llm.embed([query])[0], k)]
