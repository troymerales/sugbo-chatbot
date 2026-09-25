"""
The support chatbot as JSON, over `core/engine.py`.

Every response is the full conversation state (`engine._state`), including the
whole `messages` list — the client renders new messages by diffing against what
it has already shown, so it never has to model the state machine itself.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import config
from api import db
from core import engine
from core.llm import QuotaError

router = APIRouter(tags=["assistant"])

# In-process fallback when DATABASE_URL is unset. Single-process only.
_MEM: dict[str, engine.Conversation] = {}

# --------------------------------------------------------------------------- #
# Session store  (Postgres via db.py, or the _MEM dict)
# --------------------------------------------------------------------------- #

def _load(conversation_id: str | None) -> engine.Conversation | None:
    if not conversation_id:
        return None
    if db.enabled():
        data = db.load_conversation(conversation_id)
        return engine.deserialize(data) if data else None
    return _MEM.get(conversation_id)


def _save(conv: engine.Conversation) -> None:
    # A finished conversation lives in chat_logs now — don't keep a live row.
    if conv.stage == "done":
        _drop(conv.id)
        return
    if db.enabled():
        db.save_conversation(
            conversation_id=conv.id, stage=conv.stage, started_at=conv.started_at,
            question_count=conv.question_count, state=engine.serialize(conv),
        )
    else:
        _MEM[conv.id] = conv


def _drop(conversation_id: str) -> bool:
    if db.enabled():
        return db.delete_conversation(conversation_id)
    return _MEM.pop(conversation_id, None) is not None


def _count() -> int:
    return db.count_conversations() if db.enabled() else len(_MEM)


def _get(conversation_id: str) -> engine.Conversation:
    conv = _load(conversation_id)
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
    name: str = ""               # submitter's name → Jira reporter / custom field
    category: str = "Other"
    needed_by: str = ""          # "when do you need this?" — YYYY-MM-DD from the date picker, or ""


@router.post("/chat")
def chat(body: ChatIn) -> dict:
    conv = _load(body.conversation_id) or engine.start(body.conversation_id)
    try:
        return engine.ask(conv, body.message)
    except QuotaError as exc:
        raise HTTPException(503, str(exc))
    finally:
        _save(conv)


@router.post("/feedback")
def feedback(body: FeedbackIn) -> dict:
    conv = _get(body.conversation_id)
    try:
        return engine.feedback(conv, body.helpful)
    finally:
        _save(conv)


@router.post("/tell-me-more")
def tell_me_more(body: ConvIn) -> dict:
    conv = _get(body.conversation_id)
    try:
        return engine.tell_me_more(conv)
    finally:
        _save(conv)


@router.get("/ticket/draft")
def ticket_draft(conversation_id: str) -> dict:
    conv = _get(conversation_id)
    try:
        return engine.ticket_draft(conv)
    finally:
        _save(conv)


@router.post("/ticket")
def ticket(body: TicketIn) -> dict:
    conv = _get(body.conversation_id)
    if not (body.email.strip() and body.subject.strip() and body.summary.strip()):
        raise HTTPException(422, "email, subject and summary are required")
    try:
        return engine.submit_ticket(
            conv, email=body.email.strip(), subject=body.subject.strip(),
            summary=body.summary.strip(), category=body.category,
            needed_by=body.needed_by.strip(), name=body.name.strip(),
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    finally:
        _save(conv)


@router.post("/ticket/link-duplicate")
def link_duplicate(body: ConvIn) -> dict:
    conv = _get(body.conversation_id)
    try:
        return engine.link_duplicate(conv)
    finally:
        _save(conv)


@router.get("/session/{conversation_id}")
def get_session(conversation_id: str) -> dict:
    """Return the current state of a live conversation so the widget can resume
    it after a page reload. 404 once the conversation has ended."""
    conv = _get(conversation_id)
    return engine._state(conv)


@router.delete("/session/{conversation_id}")
def end_session(conversation_id: str) -> dict:
    conv = _load(conversation_id)
    if conv:
        engine.log_abandoned(conv)
        _drop(conversation_id)
    return {"ended": bool(conv)}




def session_count() -> int:
    """Live conversations, for the readiness probe in service.py."""
    return _count()
