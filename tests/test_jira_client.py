import types

from core import jira_client


def _resp(status, text="", js=None):
    r = types.SimpleNamespace()
    r.status_code = status
    r.text = text
    r.json = lambda: (js if js is not None else {})
    return r


def test_adf_paragraph_per_line():
    doc = jira_client._adf("line one\nline two")
    assert doc["type"] == "doc" and doc["version"] == 1
    texts = [p["content"][0]["text"] for p in doc["content"] if p.get("content")]
    assert texts == ["line one", "line two"]


def test_adf_blank_line_is_spacer():
    doc = jira_client._adf("a\n\nb")
    assert doc["content"][1] == {"type": "paragraph"}  # empty spacer between a and b


def test_adf_empty_input_has_placeholder():
    doc = jira_client._adf("   \n  ")
    assert doc["content"][0]["content"][0]["text"] == "(no details)"


def test_build_description_includes_all_fields():
    d = jira_client.build_description(
        summary="cannot void", category="Billing", contact="a@b.com",
        question_count=3, transcript="User: hi\nAssistant: hello",
        due_date="2026-09-04", urgency="high",
    )
    assert "cannot void" in d
    assert "Reporter email: a@b.com" in d
    assert "Suggested category: Billing" in d
    assert "Target date: 2026-09-04" in d
    assert "Requested urgency: high" in d
    assert "Questions asked before ticket: 3" in d
    assert "Conversation transcript" in d and "User: hi" in d


def test_create_issue_maps_duedate_reporter_and_urgency(monkeypatch):
    monkeypatch.setattr(jira_client, "jira_configured", lambda: True)
    monkeypatch.setattr(jira_client, "resolve_account_id", lambda e: "acct-42")
    sent = []
    monkeypatch.setattr(jira_client.requests, "post",
                        lambda url, json=None, **kw: sent.append(json) or _resp(201, js={"key": "KAN-7"}))

    key = jira_client.create_issue(
        subject="x", category="Billing", summary="s", contact="u@example.com",
        transcript="t", question_count=1, due_date="2026-09-04", urgency="high",
    )
    assert key == "KAN-7"
    f = sent[0]["fields"]
    assert f["duedate"] == "2026-09-04"
    assert f["reporter"] == {"id": "acct-42"}
    assert "urgency-high" in f["labels"]
    body = jira_client._plain_text_from_adf(f["description"])
    assert "Target date: 2026-09-04" in body


def test_create_issue_retries_without_rejected_reporter(monkeypatch):
    monkeypatch.setattr(jira_client, "jira_configured", lambda: True)
    monkeypatch.setattr(jira_client, "resolve_account_id", lambda e: "acct-42")
    seq = iter([
        _resp(400, text='{"errors":{"reporter":"Field \'reporter\' cannot be set"}}'),
        _resp(201, js={"key": "KAN-9"}),
    ])
    sent = []
    monkeypatch.setattr(jira_client.requests, "post",
                        lambda url, json=None, **kw: sent.append(dict(json["fields"])) or next(seq))

    key = jira_client.create_issue(
        subject="x", category="Other", summary="s", contact="u@example.com",
        transcript="t", question_count=1, due_date="2026-09-04",
    )
    assert key == "KAN-9"
    assert "reporter" in sent[0] and "reporter" not in sent[1]  # dropped on retry
    assert sent[1]["duedate"] == "2026-09-04"                   # unrelated field kept


def test_create_issue_skips_malformed_duedate(monkeypatch):
    monkeypatch.setattr(jira_client, "jira_configured", lambda: True)
    monkeypatch.setattr(jira_client, "resolve_account_id", lambda e: None)
    sent = []
    monkeypatch.setattr(jira_client.requests, "post",
                        lambda url, json=None, **kw: sent.append(json) or _resp(201, js={"key": "KAN-1"}))
    jira_client.create_issue(
        subject="x", category="Other", summary="s", contact="u@e.com",
        transcript="t", question_count=1, due_date="next Friday",  # not YYYY-MM-DD
    )
    assert "duedate" not in sent[0]["fields"]


def test_resolve_account_id_none_without_jira(monkeypatch):
    monkeypatch.setattr(jira_client, "jira_configured", lambda: False)
    jira_client._ACCOUNT_ID_CACHE.clear()
    assert jira_client.resolve_account_id("nobody@example.com") is None
