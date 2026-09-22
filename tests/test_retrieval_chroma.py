"""The Chroma-backed index: ranks like the scan, persists, and self-heals.

Skipped when chromadb isn't installed. The rest of the suite runs on
VECTOR_BACKEND=memory (see conftest), so this is the only place the real
vector store is exercised.
"""

import json

import pytest

import config
from core import knowledge, llm, retrieval

pytest.importorskip("chromadb")

QUERY = "How do I void a payment?"


@pytest.fixture
def chroma(tmp_path, monkeypatch):
    """Opt this test back into Chroma, against a throwaway directory."""
    monkeypatch.setattr(config, "VECTOR_BACKEND", "chroma")
    monkeypatch.setattr(config, "VECTOR_DIR", tmp_path / "chroma")
    retrieval.reset_index()
    yield
    retrieval.reset_index()


def test_chroma_ranks_like_the_memory_scan(chroma, monkeypatch):
    from_chroma = [s.title for s in retrieval.top_sections(QUERY, k=5)]

    monkeypatch.setattr(config, "VECTOR_BACKEND", "memory")
    retrieval.reset_index()
    from_scan = [s.title for s in retrieval.top_sections(QUERY, k=5)]

    assert from_chroma == from_scan


def test_scores_are_cosine_similarities(chroma):
    ranked = retrieval.rank_sections(QUERY)

    assert len(ranked) == len(knowledge.content_sections())
    assert all(-1.0001 <= score <= 1.0001 for _, score in ranked)
    assert [s for _, s in ranked] == sorted((s for _, s in ranked), reverse=True)


def test_index_survives_a_restart_without_re_embedding(chroma, monkeypatch):
    retrieval.top_sections(QUERY, k=3)  # builds and persists the collection

    batches: list[int] = []
    real_embed = llm.embed

    def counting_embed(texts, **kw):
        batches.append(len(texts))
        return real_embed(texts, **kw)

    monkeypatch.setattr(llm, "embed", counting_embed)
    retrieval.reset_index()  # as if the process had restarted
    retrieval.top_sections(QUERY, k=3)

    # Only the query was embedded; every section came back off disk.
    assert batches == [1]


def test_switching_backend_rebuilds_the_index(chroma, monkeypatch):
    retrieval.top_sections(QUERY, k=3)  # indexed at the mock backend's 256 dims

    # The mock -> Gemini switch: a new fingerprint, and 3072-dim vectors that
    # the existing 256-dim collection could not accept.
    monkeypatch.setattr(config, "LLM_BACKEND", "gemini")
    monkeypatch.setattr(llm, "embed", lambda texts, **kw: [[0.1] * 3072 for _ in texts])
    retrieval.reset_index()

    # Without the fingerprint rebuild this raises:
    #   InvalidArgumentError: expecting embedding with dimension of 256, got 3072
    assert len(retrieval.top_sections(QUERY, k=3)) == 3


def _write_seed(fingerprint: str) -> None:
    """A stamped seed covering every content section, at the backend's own dim."""
    secs = knowledge.content_sections()
    dim = len(llm.embed(["probe"])[0])
    vectors = {}
    for i, sec in enumerate(secs):
        vec = [0.0] * dim
        vec[i % dim] = 1.0
        vectors[sec.slug] = vec
    config.EMBEDDINGS_SEED_PATH.write_text(
        json.dumps({"fingerprint": fingerprint, "vectors": vectors}), encoding="utf-8"
    )


def _embed_batches(monkeypatch) -> list[int]:
    sizes: list[int] = []
    real = llm.embed

    def counting(texts, **kw):
        sizes.append(len(texts))
        return real(texts, **kw)

    monkeypatch.setattr(llm, "embed", counting)
    return sizes


def test_a_matching_seed_builds_the_index_without_embedding(chroma, monkeypatch):
    _write_seed(retrieval.fingerprint())

    batches = _embed_batches(monkeypatch)
    retrieval.top_sections(QUERY, k=3)

    # Only the query hit the API; the sections came out of the seed file.
    assert batches == [1]


def test_a_stale_seed_is_ignored(chroma, monkeypatch):
    _write_seed("not-the-current-fingerprint")

    batches = _embed_batches(monkeypatch)
    retrieval.top_sections(QUERY, k=3)

    # The sections were embedded after all, rather than indexed from stale vectors.
    assert len(knowledge.content_sections()) in batches
