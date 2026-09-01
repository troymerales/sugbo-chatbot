import json

import pytest

import config
import llm


def test_generate_is_cached():
    p = "unique prompt for cache test 123"
    a = llm.generate(p)
    assert llm.cache_stats()["by_kind"].get("generate") == 1
    b = llm.generate(p)          # served from cache
    assert a == b
    assert llm.cache_stats()["by_kind"].get("generate") == 1


def test_offline_raises_on_miss(monkeypatch):
    monkeypatch.setattr(config, "LLM_OFFLINE", True)
    with pytest.raises(llm.OfflineCacheMiss):
        llm.generate("never seen before prompt xyz")


def test_offline_serves_a_warm_entry(monkeypatch):
    llm.generate("warm me up")                       # online, cached
    monkeypatch.setattr(config, "LLM_OFFLINE", True)
    assert llm.generate("warm me up")                # cache hit, no error


def test_chat_tracks_history():
    chat = llm.new_chat("system", model="m")
    chat.send("first")
    chat.send("second")
    roles = [h["role"] for h in chat.history]
    assert roles == ["user", "model", "user", "model"]
    assert chat.history[0]["text"] == "first"


def test_embed_shape_and_determinism():
    v1 = llm.embed(["hello world"])
    v2 = llm.embed(["hello world"])
    assert len(v1) == 1 and len(v1[0]) == 256
    assert v1 == v2


def test_json_mode_utility_call_parses():
    out = llm.generate("CONVERSATION:\nUser: is there an API",
                       system="You triage failed support conversations",
                       json_mode=True)
    data = json.loads(out)
    assert data["label"] in ("docs_gap", "product_bug", "out_of_scope")
