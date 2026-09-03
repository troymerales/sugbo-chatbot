"""
The Streamlit floating-widget state machine (`assistant/session.py`), driven
through an AppTest harness. Same offline mock backend + tmp paths as the rest of
the suite (see conftest.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from streamlit.testing.v1 import AppTest

from assistant import session
from core import chatlog

_HARNESS = str(Path(__file__).parent / "_assistant_app.py")


def _app() -> AppTest:
    return AppTest.from_file(_HARNESS, default_timeout=30).run()


def _stage(at: AppTest) -> str:
    return at.session_state["asst_stage"]


def _assistant_texts(at: AppTest) -> list[str]:
    return [m["content"] for m in at.session_state["asst_messages"]
            if m["role"] == "assistant"]


def _ask(at: AppTest, question: str) -> AppTest:
    at.text_input(key="msg").set_value(question)
    at.button(key="send").click().run()
    return at


# --------------------------------------------------------------------------- #

def test_greeting_only_at_start():
    at = _app()
    assert _stage(at) == "chat"
    assert at.session_state["asst_messages"] == [
        {"role": "assistant", "content": session.GREETING}
    ]
    assert at.session_state["asst_question_count"] == 0


def test_documented_question_streams_and_asks_for_feedback():
    at = _ask(_app(), "How do I void a payment?")
    assert _stage(at) == "feedback"
    assert at.session_state["asst_question_count"] == 1
    assert any("Void a payment" in t for t in _assistant_texts(at))


def test_unanswerable_question_offers_a_ticket():
    at = _ask(_app(), "What is the airspeed velocity of an unladen swallow?")
    assert _stage(at) == "offer_ticket"
    assert "refused" in at.session_state["asst_failure_signals"]


def test_thumbs_down_logs_unresolved_without_a_ticket():
    at = _ask(_app(), "How do I void a payment?")
    at.button(key="down").click().run()
    assert _stage(at) == "offer_ticket"
    rows = chatlog.load_all()
    assert len(rows) == 1
    assert rows[0].outcome == "unresolved"
    assert rows[0].thumbs == "down"


def test_thumbs_up_resolves_and_logs_once():
    at = _ask(_app(), "How do I void a payment?")
    at.button(key="up").click().run()
    assert _stage(at) == "done"
    rows = chatlog.load_all()
    assert len(rows) == 1 and rows[0].outcome == "resolved"


def test_taking_a_while_auto_offers_after_three_questions():
    at = _app()
    for _ in range(3):
        _ask(at, "How do I void a payment?")
    assert _stage(at) == "offer_ticket"
    assert at.session_state["asst_question_count"] == 3


def test_tell_me_more_returns_to_chat():
    at = _ask(_app(), "What is the airspeed velocity of an unladen swallow?")
    assert _stage(at) == "offer_ticket"
    at.button(key="more").click().run()
    assert _stage(at) == "chat"


def test_ticket_filed_updates_the_same_row(monkeypatch):
    from core import jira_client, jira_dedup

    monkeypatch.setattr(jira_client, "jira_configured", lambda: True)
    monkeypatch.setattr(jira_dedup, "find_duplicate", lambda *a, **k: None)
    created = {}

    def _fake_create(**kwargs):
        created.update(kwargs)
        return "KAN-777"

    monkeypatch.setattr(jira_client, "create_issue", _fake_create)

    at = _ask(_app(), "What is the airspeed velocity of an unladen swallow?")
    assert _stage(at) == "offer_ticket"
    at.button(key="file_ticket").click().run()

    assert _stage(at) == "done"
    assert at.session_state["asst_ticket_id"] == "KAN-777"
    assert created["contact"] == "jane@example.com"

    rows = chatlog.load_all()
    assert len(rows) == 1                       # upserted, not a second row
    assert rows[0].outcome == "ticket_filed"
    assert rows[0].ticket_id == "KAN-777"


def test_link_duplicate_closes_the_chat(monkeypatch):
    from core import jira_client

    monkeypatch.setattr(jira_client, "jira_configured", lambda: True)
    at = _ask(_app(), "What is the airspeed velocity of an unladen swallow?")
    at.session_state["asst_duplicate_of"] = {
        "key": "KAN-12", "summary": "swallow speed", "similarity": 0.9,
    }
    at.button(key="link_dup").click().run()
    assert _stage(at) == "done"
    rows = chatlog.load_all()
    assert rows[0].outcome == "linked_duplicate"
    assert rows[0].duplicate_of == "KAN-12"


def test_reset_starts_a_fresh_conversation():
    at = _ask(_app(), "How do I void a payment?")
    first_id = at.session_state["asst_conversation_id"]
    at.button(key="reset").click().run()
    assert at.session_state["asst_conversation_id"] != first_id
    assert at.session_state["asst_question_count"] == 0
    assert _stage(at) == "chat"
