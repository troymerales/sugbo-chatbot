"""RAG toggle: retrieval ranks sections, and the pipeline works in both modes."""

import config
from core import bot, knowledge, retrieval


def test_full_context_prompt_has_everything():
    sp = knowledge.system_prompt()  # USE_RAG is False in the fixture
    assert "SUGBODOC DOCUMENTATION" in sp
    assert "Void a payment" in sp and "Add a new patient" in sp
    assert config.REFUSAL_MARKER in sp


def test_rag_prompt_is_a_subset(monkeypatch):
    monkeypatch.setattr(config, "USE_RAG", True)
    monkeypatch.setattr(config, "RAG_TOP_K", 5)
    retrieval.reset_index()

    full = knowledge.system_prompt()
    rag = knowledge.system_prompt(query="How do I void a payment?")

    assert len(rag) < len(full)                      # fewer sections injected
    assert config.REFUSAL_MARKER in rag              # persona preserved
    assert "Retrieved the 5 sections" in rag


def test_rank_sections_finds_the_relevant_one(monkeypatch):
    monkeypatch.setattr(config, "USE_RAG", True)
    retrieval.reset_index()
    ranked = [s.title for s, _ in retrieval.rank_sections("void a payment deposit")]
    # the mock backend's lexical embeddings are weak, but the target section
    # should still land well inside the top of the ranking
    assert "Void a payment" in ranked[:8]


def test_bot_respond_works_with_rag_on(monkeypatch):
    monkeypatch.setattr(config, "USE_RAG", True)
    retrieval.reset_index()
    res = bot.respond(bot.fresh_chat(), "How do I void a payment?")
    assert not res.refused
    assert "Void a payment" in res.text


def test_bot_still_refuses_with_rag_on(monkeypatch):
    monkeypatch.setattr(config, "USE_RAG", True)
    retrieval.reset_index()
    res = bot.respond(bot.fresh_chat(), "What is the airspeed velocity of a swallow?")
    assert res.refused
