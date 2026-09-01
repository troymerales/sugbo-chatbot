import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

import service  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    service.SESSIONS.clear()
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

    done = client.post("/feedback", json={
        "conversation_id": r["conversation_id"], "helpful": True}).json()
    assert done["stage"] == "done"


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
