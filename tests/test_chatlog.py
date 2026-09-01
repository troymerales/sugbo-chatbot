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
                        failure_signals=["refused"], ticket_id="KAN-9"))
    loaded = chatlog.load_all()
    assert [c.conversation_id for c in loaded] == ["conv-1", "conv-2"]
    assert loaded[1].ticket_id == "KAN-9"


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
