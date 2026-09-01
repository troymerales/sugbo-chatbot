from core import chatlog, jira_dedup
from core.chatlog import ConversationRecord


def test_cosine_properties():
    a = [1.0, 0.0, 0.0]
    assert jira_dedup._cosine(a, a) == 1.0
    assert jira_dedup._cosine(a, [0.0, 1.0, 0.0]) == 0.0
    assert jira_dedup._cosine(a, [0.0, 0.0, 0.0]) == 0.0


def test_find_duplicate_none_without_jira(monkeypatch):
    monkeypatch.setattr(jira_dedup.jira_client, "jira_configured", lambda: False)
    assert jira_dedup.find_duplicate("subj", "summary") is None


def test_find_duplicate_matches_similar_ticket(monkeypatch):
    monkeypatch.setattr(jira_dedup.jira_client, "jira_configured", lambda: True)
    monkeypatch.setattr(
        jira_dedup.jira_client, "list_recent_open_issues",
        lambda *a, **k: [{"key": "KAN-1",
                          "summary": "cannot delete a patient record",
                          "description": "user wants to remove a patient"}],
    )
    m = jira_dedup.find_duplicate("delete a patient record",
                                  "the user cannot remove a patient")
    assert m is not None and m.key == "KAN-1"


def test_kpis_run_on_seeded_log(capsys, monkeypatch):
    from analytics import analytics_kpis
    monkeypatch.setattr("sys.argv", ["analytics_kpis.py"])
    chatlog.append(ConversationRecord(
        conversation_id="c1", started_at="2026-08-01T00:00:00+00:00",
        ended_at="2026-08-01T00:01:00+00:00", outcome="resolved",
        question_count=1, messages=[{"role": "user", "content": "hi"}], thumbs="up"))
    chatlog.append(ConversationRecord(
        conversation_id="c2", started_at="2026-08-02T00:00:00+00:00",
        ended_at="2026-08-02T00:01:00+00:00", outcome="ticket_filed",
        question_count=3, messages=[{"role": "user", "content": "delete patient"}],
        failure_signals=["refused"], triage_label="docs_gap", ticket_id="KAN-2"))
    analytics_kpis.main()
    out = capsys.readouterr().out
    assert "KPIs over 2 conversations" in out
    assert "containment" in out
