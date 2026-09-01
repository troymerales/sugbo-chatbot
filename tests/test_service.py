import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from api import service  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    service._MEM.clear()
    monkeypatch.setattr(service.jira_client, "jira_configured", lambda: True)
    monkeypatch.setattr(
        service.jira_client, "create_issue",
        lambda **kw: "KAN-999",
    )
    monkeypatch.setattr(service.jira_client, "browse_url", lambda k: f"https://x/browse/{k}")
    monkeypatch.setattr(service.engine.jira_dedup, "find_duplicate", lambda *a, **k: None)
    return TestClient(service.app)


def test_healthz(client):
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["backend"] == "mock"


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


def test_unknown_conversation_id_404(client):
    r = client.post("/feedback", json={"conversation_id": "nope", "helpful": True})
    assert r.status_code == 404


def test_ticket_requires_fields(client):
    r = client.post("/chat", json={"message": "nonsense"}).json()
    bad = client.post("/ticket", json={
        "conversation_id": r["conversation_id"], "email": "", "subject": "", "summary": ""})
    assert bad.status_code == 422
