"""
Exercises the PostgreSQL persistence path (db.py + chatlog-over-db +
session persistence in service.py) against a throwaway SQLite file, so it runs
in CI with no database server.
"""

import pytest

pytest.importorskip("sqlalchemy")

import config  # noqa: E402
from api import db  # noqa: E402
from core import chatlog, engine  # noqa: E402
from core.chatlog import ConversationRecord  # noqa: E402


@pytest.fixture
def pg(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'sugbodoc.db').as_posix()}"
    monkeypatch.setattr(config, "DATABASE_URL", url, raising=False)
    db.reset()
    db.init_db()
    yield
    db.reset()


def _rec(**kw) -> ConversationRecord:
    base = dict(
        conversation_id="c", started_at="2026-08-01T00:00:00+00:00",
        ended_at="2026-08-01T00:05:00+00:00", outcome="resolved",
        question_count=1, messages=[{"role": "user", "content": "hi"}],
    )
    base.update(kw)
    return ConversationRecord(**base)


def test_chat_log_round_trip_via_db(pg):
    chatlog.append(_rec(conversation_id="c1"))
    chatlog.append(_rec(conversation_id="c2", outcome="ticket_filed",
                        failure_signals=["refused"], ticket_id="KAN-9",
                        triage_label="docs_gap"))
    loaded = chatlog.load_all()
    assert [c.conversation_id for c in loaded] == ["c1", "c2"]
    assert loaded[1].ticket_id == "KAN-9"
    assert loaded[1].failed
    assert loaded[1].triage_label == "docs_gap"


def test_reset_store_clears_the_table(pg):
    chatlog.append(_rec(conversation_id="c1"))
    chatlog.reset_store()
    assert chatlog.load_all() == []


def test_analytics_kpis_reads_from_db(pg, monkeypatch, capsys):
    from analytics import analytics_kpis
    monkeypatch.setattr("sys.argv", ["analytics_kpis.py"])
    chatlog.append(_rec(conversation_id="c1", thumbs="up"))
    chatlog.append(_rec(conversation_id="c2", outcome="ticket_filed",
                        question_count=3, failure_signals=["refused"],
                        triage_label="docs_gap", ticket_id="KAN-2"))
    analytics_kpis.main()
    assert "KPIs over 2 conversations" in capsys.readouterr().out


def test_conversation_persistence_round_trip(pg):
    conv = engine.start("conv-1")
    conv.messages.append({"role": "user", "content": "hello"})
    conv.chat.history.append({"role": "user", "text": "hello"})
    conv.question_count = 1
    conv.stage = "feedback"
    conv.failure_signals = ["refused"]

    db.save_conversation(conversation_id=conv.id, stage=conv.stage,
                         started_at=conv.started_at, question_count=1,
                         state=engine.serialize(conv))

    back = engine.deserialize(db.load_conversation("conv-1"))
    assert back.id == "conv-1"
    assert back.stage == "feedback"
    assert back.question_count == 1
    assert back.chat.history == [{"role": "user", "text": "hello"}]
    assert back.messages[-1]["content"] == "hello"
    assert back.failure_signals == ["refused"]

    assert db.count_conversations() == 1
    assert db.delete_conversation("conv-1") is True
    assert db.load_conversation("conv-1") is None


def test_service_persists_sessions_to_db(pg, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from api import service

    monkeypatch.setattr(service.jira_client, "jira_configured", lambda: True)
    monkeypatch.setattr(service.jira_client, "create_issue", lambda **kw: "KAN-999")
    monkeypatch.setattr(service.jira_client, "browse_url", lambda k: f"https://x/browse/{k}")
    monkeypatch.setattr(service.engine.jira_dedup, "find_duplicate", lambda *a, **k: None)

    with TestClient(service.app) as c:  # lifespan runs db.init_db()
        r = c.post("/chat", json={"message": "How do I void a payment?"}).json()
        cid = r["conversation_id"]
        assert db.load_conversation(cid) is not None       # persisted mid-conversation

        h = c.get("/healthz").json()
        assert h["session_store"] == "postgres" and h["active_sessions"] == 1

        c.post("/feedback", json={"conversation_id": cid, "helpful": True})
        assert db.load_conversation(cid) is None           # dropped on terminal stage
        assert chatlog.load_all()[-1].conversation_id == cid  # written to chat_logs
