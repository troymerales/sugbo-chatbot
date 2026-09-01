"""
FastAPI backend — the same conversation flow as app.py, exposed as JSON so it can
sit behind an existing website instead of Streamlit.

    pip install fastapi uvicorn
    uvicorn service:app --reload
    #  open http://127.0.0.1:8000  for the bundled demo widget

Endpoints:
    GET  /healthz
    POST /chat            {conversation_id?, message}        -> state + reply
    POST /feedback        {conversation_id, helpful}         -> state
    POST /tell-me-more    {conversation_id}                  -> state
    GET  /ticket/draft?conversation_id=...                   -> {subject, category, summary, duplicate?}
    POST /ticket          {conversation_id, email, subject, summary, category?}
    POST /ticket/link-duplicate   {conversation_id}
    DELETE /session/{conversation_id}

Session store is an in-memory dict — fine for one process / a demo. For real
deployment swap `SESSIONS` for Redis or a DB table keyed by conversation_id
(everything stored is plain JSON-able data except `Conversation.chat`, whose
`.history` list is what you'd persist).
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

import config
import engine
import jira_client
from llm import QuotaError

app = FastAPI(title="SugboDoc Support API")

# Demo-open CORS. Lock `allow_origins` to your site's origin before shipping.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSIONS: dict[str, engine.Conversation] = {}


def _get(conversation_id: str) -> engine.Conversation:
    conv = SESSIONS.get(conversation_id)
    if conv is None:
        raise HTTPException(404, "unknown conversation_id (it may have expired)")
    return conv


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #

class ChatIn(BaseModel):
    conversation_id: str | None = None
    message: str


class FeedbackIn(BaseModel):
    conversation_id: str
    helpful: bool


class ConvIn(BaseModel):
    conversation_id: str


class TicketIn(BaseModel):
    conversation_id: str
    email: str
    subject: str
    summary: str
    category: str = "Other"


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

@app.get("/healthz")
def healthz() -> dict:
    return {
        "status": "ok",
        "backend": config.LLM_BACKEND,
        "answer_model": config.ANSWER_MODEL,
        "jira_configured": jira_client.jira_configured(),
        "active_sessions": len(SESSIONS),
    }


@app.post("/chat")
def chat(body: ChatIn) -> dict:
    if body.conversation_id and body.conversation_id in SESSIONS:
        conv = SESSIONS[body.conversation_id]
    else:
        conv = engine.start(body.conversation_id)
        SESSIONS[conv.id] = conv
    try:
        return engine.ask(conv, body.message)
    except QuotaError as exc:
        raise HTTPException(503, str(exc))


@app.post("/feedback")
def feedback(body: FeedbackIn) -> dict:
    return engine.feedback(_get(body.conversation_id), body.helpful)


@app.post("/tell-me-more")
def tell_me_more(body: ConvIn) -> dict:
    return engine.tell_me_more(_get(body.conversation_id))


@app.get("/ticket/draft")
def ticket_draft(conversation_id: str) -> dict:
    return engine.ticket_draft(_get(conversation_id))


@app.post("/ticket")
def ticket(body: TicketIn) -> dict:
    conv = _get(body.conversation_id)
    if not (body.email.strip() and body.subject.strip() and body.summary.strip()):
        raise HTTPException(422, "email, subject and summary are required")
    try:
        return engine.submit_ticket(
            conv, email=body.email.strip(), subject=body.subject.strip(),
            summary=body.summary.strip(), category=body.category,
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))


@app.post("/ticket/link-duplicate")
def link_duplicate(body: ConvIn) -> dict:
    return engine.link_duplicate(_get(body.conversation_id))


@app.delete("/session/{conversation_id}")
def end_session(conversation_id: str) -> dict:
    conv = SESSIONS.pop(conversation_id, None)
    if conv:
        engine.log_abandoned(conv)
    return {"ended": bool(conv)}


# --------------------------------------------------------------------------- #
# Bundled demo widget
# --------------------------------------------------------------------------- #

_WIDGET = (config.ROOT / "web" / "index.html")


@app.get("/", response_class=HTMLResponse)
def widget() -> str:
    if _WIDGET.exists():
        return _WIDGET.read_text(encoding="utf-8")
    return "<p>Demo widget missing. The API is still up at <code>/docs</code>.</p>"
