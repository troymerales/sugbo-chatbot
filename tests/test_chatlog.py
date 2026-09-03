from core import chatlog
from core.chatlog import ConversationRecord


def _rec(**kw):
    base = dict(
        conversation_id="conv-x", started_at="2026-08-01T00:00:00+00:00",
        ended_at="2026-08-01T00:05:00+00:00", outcome="resolved",
        question_count=1, messages=[{"role": "user", "content": "how do I add a patient"}],
    )
    base.update(kw)
    return ConversationRecord(**base)


def test_round_trip():
    chatlog.append(_rec(conversation_id="conv-1"))
    chatlog.append(_rec(conversation_id="conv-2", outcome="ticket_filed",
                        failure_signals=["refused"],
                        failure_reasons=["bot could not answer from the docs"],
                        ticket_id="KAN-9"))
    loaded = chatlog.load_all()
    assert [c.conversation_id for c in loaded] == ["conv-1", "conv-2"]
    assert loaded[1].ticket_id == "KAN-9"
    assert loaded[1].failure_reasons == ["bot could not answer from the docs"]


def test_failure_reasons_in_csv_mirror():
    chatlog.append(_rec(conversation_id="conv-r", failure_signals=["refused", "repeated_question"],
                        failure_reasons=["bot could not answer from the docs",
                                         "user re-asked the same question"]))
    import config
    text = config.CHAT_LOG_CSV_PATH.read_text(encoding="utf-8-sig")
    assert "failure_reasons" in text.splitlines()[0]
    assert "bot could not answer from the docs|user re-asked the same question" in text


def test_failed_flag_and_failed_questions():
    ok = _rec()
    assert not ok.failed and ok.failed_user_questions() == []

    bad = _rec(failure_signals=["refused"],
               messages=[{"role": "user", "content": "delete patient"},
                         {"role": "assistant", "content": "no"},
                         {"role": "user", "content": "really?"}])
    assert bad.failed
    assert bad.failed_user_questions() == ["delete patient", "really?"]


def test_load_all_empty_when_no_file():
    assert chatlog.load_all() == []


def test_append_upserts_on_conversation_id():
    chatlog.append(_rec(conversation_id="c1", outcome="unresolved",
                        failure_signals=["thumbs_down"]))
    chatlog.append(_rec(conversation_id="c2", outcome="unresolved"))
    chatlog.append(_rec(conversation_id="c1", outcome="ticket_filed",
                        failure_signals=["thumbs_down"], ticket_id="KAN-9"))

    loaded = chatlog.load_all()
    assert [c.conversation_id for c in loaded] == ["c1", "c2"]   # order kept
    assert loaded[0].outcome == "ticket_filed"                   # row updated in place
    assert loaded[0].ticket_id == "KAN-9"

    # CSV mirror reflects the update, not a second c1 row
    import config
    body = config.CHAT_LOG_CSV_PATH.read_text(encoding="utf-8-sig")
    assert body.count("\nc1,") == 1
    assert "ticket_filed" in body
