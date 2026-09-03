import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from api import service  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    service._MEM.clear()
    service._HITS.clear()
    monkeypatch.setattr(service.jira_client, "jira_configured", lambda: True)
    monkeypatch.setattr(
        service.jira_client, "create_issue",
        lambda **kw: "KAN-999",
    )
    monkeypatch.setattr(service.jira_client, "browse_url", lambda k: f"https://x/browse/{k}")
    monkeypatch.setattr(service.engine.jira_dedup, "find_duplicate", lambda *a, **k: None)
    return TestClient(service.app)


def test_healthz_is_liveness_only(client):
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["backend"] == "mock"
    assert "active_sessions" not in body        # no DB touch in a liveness probe


def test_readyz_reports_disabled_db_as_ready(client):
    r = client.get("/readyz")
    assert r.status_code == 200                 # no DATABASE_URL in tests
    assert r.json()["database"] == "disabled"
    assert r.json()["status"] == "ready"


def test_rate_limit_returns_429_over_the_cap(client, monkeypatch):
    monkeypatch.setattr(service.config, "RATE_LIMIT_PER_MIN", 3)
    codes = [client.post("/chat", json={"message": "How do I void a payment?"}).status_code
             for _ in range(5)]
    assert codes[:3] == [200, 200, 200]
    assert codes[-1] == 429


def test_unhandled_error_is_a_safe_500(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret internal detail")
    monkeypatch.setattr(service.engine, "ask", boom)
    r = client.post("/chat", json={"message": "hi"})
    assert r.status_code == 500
    assert r.json() == {"detail": "internal error"}   # no stack trace leaked


def test_answer_flow(client):
    r = client.post("/chat", json={"message": "How do I void a payment?"}).json()
    assert r["conversation_id"]
    assert "Void a payment" in r["reply"]
    assert r["stage"] == "feedback"
    # the greeting is message[0] so the widget can show it on open
    assert r["messages"][0]["role"] == "assistant"
    assert "SugboDoc support assistant" in r["messages"][0]["content"]

    done = client.post("/feedback", json={
        "conversation_id": r["conversation_id"], "helpful": True}).json()
    assert done["stage"] == "done"
    # the terminal reply must be in `messages` (widget renders from there)
    assert done["messages"][-1]["content"] == "Great — glad I could help!"


def test_widget_config_serves_the_greeting(client):
    cfg = client.get("/widget/config").json()
    assert cfg["greeting"] == service.engine.GREETING
    assert cfg["documentation_url"] == "/documentation"


def test_get_session_resumes_then_404s_after_done(client):
    r = client.post("/chat", json={"message": "How do I void a payment?"}).json()
    cid = r["conversation_id"]

    resumed = client.get(f"/session/{cid}")
    assert resumed.status_code == 200
    assert resumed.json()["messages"] == r["messages"]

    client.post("/feedback", json={"conversation_id": cid, "helpful": True})
    assert client.get(f"/session/{cid}").status_code == 404


def test_documentation_page_has_nav_and_content(client):
    body = client.get("/documentation").text
    assert "<nav id=\"toc\">" in body
    assert 'href="#void-a-payment"' in body
    assert "SugboDoc Documentation" in body


def test_refusal_leads_to_ticket_offer_and_creation(client):
    r = client.post("/chat", json={"message": "totally unrelated nonsense question"}).json()
    cid = r["conversation_id"]
    assert r["refused"] is True
    assert r["stage"] == "offer_ticket"

    draft = client.get(f"/ticket/draft?conversation_id={cid}").json()
    assert "subject" in draft and "summary" in draft

    res = client.post("/ticket", json={
        "conversation_id": cid, "email": "qa@example.com",
        "subject": draft["subject"] or "help", "summary": draft["summary"] or "stuck",
        "category": draft["category"],
    }).json()
    assert res["ticket_id"] == "KAN-999"


def test_thumbs_down_is_logged_even_without_a_ticket(client):
    from core import chatlog

    r = client.post("/chat", json={"message": "How do I void a payment?"}).json()
    cid = r["conversation_id"]
    client.post("/feedback", json={"conversation_id": cid, "helpful": False})

    logged = [c for c in chatlog.load_all() if c.conversation_id == cid]
    assert len(logged) == 1
    assert logged[0].outcome == "unresolved"
    assert logged[0].thumbs == "down"
    assert "thumbs_down" in logged[0].failure_signals


def test_unresolved_row_is_updated_in_place_when_a_ticket_is_filed(client):
    from core import chatlog

    r = client.post("/chat", json={"message": "totally unrelated nonsense"}).json()
    cid = r["conversation_id"]                       # refusal -> logged "unresolved"
    assert [c.outcome for c in chatlog.load_all() if c.conversation_id == cid] == ["unresolved"]

    client.post("/ticket", json={
        "conversation_id": cid, "email": "qa@example.com",
        "subject": "help", "summary": "stuck", "category": "Other",
    })
    rows = [c for c in chatlog.load_all() if c.conversation_id == cid]
    assert len(rows) == 1 and rows[0].outcome == "ticket_filed"


def test_ticket_passes_name_email_and_due_date(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(service.jira_client, "create_issue",
                        lambda **kw: captured.update(kw) or "KAN-777")

    r = client.post("/chat", json={"message": "totally unrelated nonsense"}).json()
    res = client.post("/ticket", json={
        "conversation_id": r["conversation_id"],
        "name": "Jane Dela Cruz", "email": "user@clinic.ph",
        "subject": "s", "summary": "y", "category": "Other",
        "needed_by": "2099-01-15",                      # from the date picker
    }).json()

    assert res["ticket_id"] == "KAN-777"
    assert captured["submitter_name"] == "Jane Dela Cruz"
    assert captured["contact"] == "user@clinic.ph"
    assert captured["due_date"] == "2099-01-15"
    assert captured["urgency"] == "low"                 # far in the future
    assert "Target date" in res["messages"][-1]["content"]
    assert "needed_by" not in captured                  # no free-text field anymore


def test_ticket_ignores_a_bad_date(client, monkeypatch):
    captured = {}
    monkeypatch.setattr(service.jira_client, "create_issue",
                        lambda **kw: captured.update(kw) or "KAN-778")
    r = client.post("/chat", json={"message": "totally unrelated nonsense"}).json()
    client.post("/ticket", json={
        "conversation_id": r["conversation_id"], "email": "u@e.com",
        "subject": "s", "summary": "y", "needed_by": "sometime soon",
    })
    assert captured["due_date"] is None
    assert captured["urgency"] == "medium"


def test_unknown_conversation_id_404(client):
    r = client.post("/feedback", json={"conversation_id": "nope", "helpful": True})
    assert r.status_code == 404


def test_ticket_requires_fields(client):
    r = client.post("/chat", json={"message": "nonsense"}).json()
    bad = client.post("/ticket", json={
        "conversation_id": r["conversation_id"], "email": "", "subject": "", "summary": ""})
    assert bad.status_code == 422
