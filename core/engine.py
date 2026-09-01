"""
The conversation state machine, independent of any UI.

`service.py` (the FastAPI backend) drives a `Conversation` through these
functions. `app.py` (the Streamlit demo) implements the same flow inline against
`st.session_state` — it predates this module and could be refactored onto it.

Stages:  chat  ->  feedback  ->  offer_ticket  ->  done
The only model work per conversation is the answer + the verification pass
(bot.py / grounding.py). Failure detection is rule-based; the ticket draft is a
deterministic default — both to keep LLM cost down.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import config
from core import (
    bot,
    chatlog,
    failure_capture,
    jira_client,
    jira_dedup,
    llm,
    ticketing,
)


@dataclass
class Conversation:
    id: str
    chat: llm.Chat
    started_at: str
    messages: list[dict] = field(default_factory=list)
    question_count: int = 0
    stage: str = "chat"                       # chat | feedback | offer_ticket | done
    grounding_checks: list[dict] = field(default_factory=list)
    failure_signals: list[str] = field(default_factory=list)
    thumbs: str | None = None
    ticket_id: str | None = None
    ticket_category: str | None = None
    needed_by: str | None = None          # the "when do you need this?" date (YYYY-MM-DD)
    due_date: str | None = None           # same value, kept for the chat log column
    duplicate_of: str | None = None
    logged: bool = False

    def transcript(self) -> str:
        return "\n".join(
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in self.messages
        )


GREETING = (
    "Hi! I'm the SugboDoc support assistant. Ask me about scheduling, patients, "
    "encounters, billing or immunizations."
)


def start(conversation_id: str | None = None) -> Conversation:
    conv = Conversation(
        id=conversation_id or chatlog.new_conversation_id(),
        chat=bot.fresh_chat(),
        started_at=chatlog.now_iso(),
    )
    conv.messages.append({"role": "assistant", "content": GREETING})
    return conv


def ask(conv: Conversation, text: str) -> dict:
    conv.messages.append({"role": "user", "content": text})
    conv.question_count += 1

    result = bot.respond(conv.chat, text)
    conv.messages.append({"role": "assistant", "content": result.text})
    conv.grounding_checks.append(result.log_entry(text))

    if result.refused or result.grounding.is_refusal_worthy:
        _enter_failure(conv, grounding_failed=result.grounding.is_refusal_worthy)
    elif conv.question_count >= config.QUESTIONS_BEFORE_TICKET:
        _enter_failure(conv)  # "taking a while" — offer a ticket proactively
    else:
        conv.stage = "feedback"

    return _state(conv, extra={"reply": result.text, "refused": result.refused,
                               "grounding": result.log_entry(text)})


def feedback(conv: Conversation, helpful: bool) -> dict:
    if helpful:
        conv.thumbs = "up"
        conv.messages.append({"role": "assistant", "content": "Great — glad I could help!"})
        conv.stage = "done"
        _log(conv, "resolved")
    else:
        conv.thumbs = "down"
        _enter_failure(conv, thumbs_down=True)
    return _state(conv)


def tell_me_more(conv: Conversation) -> dict:
    conv.stage = "chat"
    conv.messages.append(
        {"role": "assistant", "content": "Okay — what else can you tell me about the issue?"}
    )
    return _state(conv)


def _enter_failure(conv: Conversation, *, grounding_failed: bool = False,
                   thumbs_down: bool = False) -> None:
    sig = failure_capture.detect_failures(
        conv.messages, thumbs_down=thumbs_down, grounding_failed=grounding_failed
    )
    conv.failure_signals = sorted(set(conv.failure_signals) | set(sig.as_list()))
    conv.stage = "offer_ticket"


# --------------------------------------------------------------------------- #
# Ticket
# --------------------------------------------------------------------------- #

def ticket_draft(conv: Conversation) -> dict:
    draft = ticketing.default_draft(conv.transcript())   # no model call
    dup = jira_dedup.find_duplicate(draft.subject, draft.summary)
    conv.duplicate_of = dup.key if dup else None
    return {
        "subject": draft.subject,
        "category": draft.category,
        "summary": draft.summary,
        "duplicate": (
            {"key": dup.key, "summary": dup.summary, "similarity": round(dup.similarity, 3)}
            if dup else None
        ),
    }


def submit_ticket(conv: Conversation, *, email: str, subject: str, summary: str,
                  category: str = "Other", needed_by: str = "", name: str = "") -> dict:
    if not jira_client.jira_configured():
        raise RuntimeError("Jira is not configured (JIRA_* env vars).")

    due_date = ticketing.as_iso_date(needed_by)
    urgency = ticketing.urgency_for_date(due_date)
    conv.needed_by = due_date
    conv.due_date = due_date

    key = jira_client.create_issue(
        subject=subject, category=category, summary=summary, contact=email,
        transcript=conv.transcript(), question_count=conv.question_count,
        submitter_name=name, due_date=due_date, urgency=urgency,
    )
    conv.ticket_id = key
    conv.ticket_category = category
    url = jira_client.browse_url(key)

    when = f" Target date **{due_date}**." if due_date else ""
    conv.messages.append({
        "role": "assistant",
        "content": (
            f"✅ Ticket **{key}** created in Jira — [open it]({url}).{when} "
            f"Our team will follow up at **{email}**."
        ),
    })
    conv.stage = "done"
    _log(conv, "ticket_filed")
    return _state(conv, extra={"ticket_id": key, "url": url})


def link_duplicate(conv: Conversation) -> dict:
    ref = f" **{conv.duplicate_of}**" if conv.duplicate_of else ""
    conv.messages.append({
        "role": "assistant",
        "content": f"Linked you to the existing ticket{ref} — the team is already tracking it.",
    })
    conv.stage = "done"
    _log(conv, "linked_duplicate")
    return _state(conv)


# --------------------------------------------------------------------------- #
# Serialisation / logging
# --------------------------------------------------------------------------- #

def _state(conv: Conversation, *, extra: dict | None = None) -> dict:
    out = {
        "conversation_id": conv.id,
        "stage": conv.stage,
        "question_count": conv.question_count,
        "messages": conv.messages,
        "failure_signals": conv.failure_signals,
        "offer_ticket": conv.stage == "offer_ticket",
        "ticket_id": conv.ticket_id,
    }
    if extra:
        out.update(extra)
    return out


def _log(conv: Conversation, outcome: str) -> None:
    if conv.logged:
        return
    chatlog.append(chatlog.ConversationRecord(
        conversation_id=conv.id,
        started_at=conv.started_at,
        ended_at=chatlog.now_iso(),
        outcome=outcome,
        question_count=conv.question_count,
        messages=list(conv.messages),
        failure_signals=list(conv.failure_signals),
        grounding_checks=list(conv.grounding_checks),
        thumbs=conv.thumbs,
        ticket_id=conv.ticket_id,
        ticket_category=conv.ticket_category,
        needed_by=conv.needed_by,
        due_date=conv.due_date,
        duplicate_of=conv.duplicate_of,
    ))
    conv.logged = True


def log_abandoned(conv: Conversation) -> None:
    if not conv.logged and conv.question_count > 0:
        _log(conv, "abandoned")


# --------------------------------------------------------------------------- #
# Persistence  (service.py stores this blob in the `conversations` table when a
# DATABASE_URL is configured — everything here is plain JSON-able data)
# --------------------------------------------------------------------------- #

def serialize(conv: Conversation) -> dict:
    return {
        "id": conv.id,
        "chat": {
            "system": conv.chat.system,
            "model": conv.chat.model,
            "temperature": conv.chat.temperature,
            "history": conv.chat.history,
        },
        "started_at": conv.started_at,
        "messages": conv.messages,
        "question_count": conv.question_count,
        "stage": conv.stage,
        "grounding_checks": conv.grounding_checks,
        "failure_signals": conv.failure_signals,
        "thumbs": conv.thumbs,
        "ticket_id": conv.ticket_id,
        "ticket_category": conv.ticket_category,
        "needed_by": conv.needed_by,
        "due_date": conv.due_date,
        "duplicate_of": conv.duplicate_of,
        "logged": conv.logged,
    }


def deserialize(data: dict) -> Conversation:
    c = data["chat"]
    return Conversation(
        id=data["id"],
        chat=llm.Chat(system=c["system"], model=c["model"],
                      temperature=c.get("temperature", 0.2),
                      history=list(c.get("history", []))),
        started_at=data["started_at"],
        messages=list(data.get("messages", [])),
        question_count=data.get("question_count", 0),
        stage=data.get("stage", "chat"),
        grounding_checks=list(data.get("grounding_checks", [])),
        failure_signals=list(data.get("failure_signals", [])),
        thumbs=data.get("thumbs"),
        ticket_id=data.get("ticket_id"),
        ticket_category=data.get("ticket_category"),
        needed_by=data.get("needed_by"),
        due_date=data.get("due_date"),
        duplicate_of=data.get("duplicate_of"),
        logged=data.get("logged", False),
    )
