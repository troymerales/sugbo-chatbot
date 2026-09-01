import types

import pytest

from core import jira_client


def _resp(status, text="", js=None):
    r = types.SimpleNamespace()
    r.status_code = status
    r.text = text
    r.json = lambda: (js if js is not None else {})
    return r


@pytest.fixture
def jira(monkeypatch):
    """Jira 'configured', no user lookups, no custom fields — the base for the
    create_issue tests; individual tests override what they need."""
    monkeypatch.setattr(jira_client, "jira_configured", lambda: True)
    monkeypatch.setattr(jira_client, "resolve_account_id", lambda q: None)
    monkeypatch.setattr(jira_client, "_field_id", lambda name: None)
    return monkeypatch


def test_adf_paragraph_per_line():
    doc = jira_client._adf("line one\nline two")
    assert doc["type"] == "doc" and doc["version"] == 1
    texts = [p["content"][0]["text"] for p in doc["content"] if p.get("content")]
    assert texts == ["line one", "line two"]


def test_adf_blank_line_is_spacer():
    doc = jira_client._adf("a\n\nb")
    assert doc["content"][1] == {"type": "paragraph"}


def test_adf_empty_input_has_placeholder():
    doc = jira_client._adf("   \n  ")
    assert doc["content"][0]["content"][0]["text"] == "(no details)"


def test_build_description_includes_all_fields():
    d = jira_client.build_description(
        summary="cannot void", category="Billing", contact="a@b.com",
        question_count=3, transcript="User: hi\nAssistant: hello",
        submitter_name="Jane Cruz", due_date="2026-09-04", urgency="high",
    )
    assert "cannot void" in d
    assert "Submitter: Jane Cruz" in d
    assert "Submitter email: a@b.com" in d
    assert "Suggested category: Billing" in d
    assert "Target date: 2026-09-04" in d
    assert "Requested urgency: high" in d
    assert "Questions asked before ticket: 3" in d
    assert "Conversation transcript" in d and "User: hi" in d


def test_create_issue_maps_duedate_and_urgency(jira):
    jira.setattr(jira_client, "resolve_account_id", lambda q: "acct-42")
    sent = []
    jira.setattr(jira_client.requests, "post",
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
    assert "Target date: 2026-09-04" in jira_client._plain_text_from_adf(f["description"])


def test_create_issue_name_goes_to_submitter_field_not_reporter(jira):
    # the email resolves to a Jira user; the name never feeds `reporter`
    jira.setattr(jira_client, "resolve_account_id",
                 lambda q: "acct-99" if q == "jane@clinic.ph" else None)
    jira.setattr(jira_client, "_field_id", lambda name: {
        "Submitter": "customfield_10046",
        "Submitter Email": "customfield_10047",
        "Subject": "customfield_10044",
    }.get(name))
    sent = []
    jira.setattr(jira_client.requests, "post",
                 lambda url, json=None, **kw: sent.append(json) or _resp(201, js={"key": "KAN-8"}))

    jira_client.create_issue(
        subject="Cannot export claims", category="Billing", summary="s",
        contact="jane@clinic.ph", transcript="t", question_count=1,
        submitter_name="Jane Cruz",
    )
    f = sent[0]["fields"]
    assert f["reporter"] == {"id": "acct-99"}                 # from the EMAIL only
    assert f["customfield_10046"] == "Jane Cruz"              # Submitter
    assert f["customfield_10047"] == "jane@clinic.ph"         # Submitter Email
    assert f["customfield_10044"] == "Cannot export claims"   # Subject
    body = jira_client._plain_text_from_adf(f["description"])
    assert "Submitter: Jane Cruz" in body and "Submitter email: jane@clinic.ph" in body


def test_create_issue_reporter_stays_default_for_external_submitter(jira):
    # nobody resolves -> `reporter` not set -> Jira keeps the API-token user
    jira.setattr(jira_client, "_field_id",
                 lambda name: "customfield_10046" if name == "Submitter" else None)
    sent = []
    jira.setattr(jira_client.requests, "post",
                 lambda url, json=None, **kw: sent.append(json) or _resp(201, js={"key": "KAN-8b"}))
    jira_client.create_issue(
        subject="x", category="Other", summary="s", contact="patient@gmail.com",
        transcript="t", question_count=1, submitter_name="A Patient",
    )
    f = sent[0]["fields"]
    assert "reporter" not in f
    assert f["customfield_10046"] == "A Patient"


def test_create_issue_retries_dropping_rejected_reporter_and_customfield(jira):
    jira.setattr(jira_client, "resolve_account_id", lambda q: "acct-42")
    jira.setattr(jira_client, "_field_id",
                 lambda name: "customfield_10046" if name == "Submitter" else None)
    seq = iter([
        _resp(400, text='{"errors":{"reporter":"cannot be set","customfield_10046":"unknown"}}'),
        _resp(201, js={"key": "KAN-9"}),
    ])
    sent = []
    jira.setattr(jira_client.requests, "post",
                 lambda url, json=None, **kw: sent.append(dict(json["fields"])) or next(seq))

    key = jira_client.create_issue(
        subject="x", category="Other", summary="s", contact="u@example.com",
        transcript="t", question_count=1, submitter_name="Jane", due_date="2026-09-04",
    )
    assert key == "KAN-9"
    assert "reporter" in sent[0] and "customfield_10046" in sent[0]
    assert "reporter" not in sent[1] and "customfield_10046" not in sent[1]
    assert sent[1]["duedate"] == "2026-09-04"                 # unrelated field kept


def test_create_issue_skips_malformed_duedate(jira):
    sent = []
    jira.setattr(jira_client.requests, "post",
                 lambda url, json=None, **kw: sent.append(json) or _resp(201, js={"key": "KAN-1"}))
    jira_client.create_issue(
        subject="x", category="Other", summary="s", contact="u@e.com",
        transcript="t", question_count=1, due_date="next Friday",
    )
    assert "duedate" not in sent[0]["fields"]


def test_resolve_account_id_none_without_jira(monkeypatch):
    monkeypatch.setattr(jira_client, "jira_configured", lambda: False)
    jira_client._ACCOUNT_ID_CACHE.clear()
    assert jira_client.resolve_account_id("nobody@example.com") is None
    assert jira_client.resolve_account_id("Some Name") is None
