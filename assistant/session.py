"""
The widget's conversation state machine, over `st.session_state`.

This is the Streamlit sibling of `core/engine.py` (which drives the FastAPI
backend). It exists separately for the same reason `app.py` has its own inline
version: a Streamlit widget wants plain session-state mutations and a streaming
answer, not `engine`'s return-a-dict-of-state shape. All the actual work —
answering, verification, failure detection, Jira, logging — is delegated to
`core/`.

Stages:  chat -> feedback -> offer_ticket -> done   (same as engine.py)

Every `st.session_state` key this module owns is prefixed `asst_` so the widget
drops onto an umbrella page without colliding with that page's own state.
"""

from __future__ import annotations

import logging

import streamlit as st

import config
from core import (
    bot,
    chatlog,
    failure_capture,
    jira_client,
    jira_dedup,
    ticketing,
)

log = logging.getLogger("sugbodoc.assistant")

GREETING = (
    "Hi! I'm the SugboDoc support assistant. Ask me about scheduling, patients, "
    "encounters, billing or immunizations."
)

# The message prepended when the verification pass walks back a streamed draft.
_CORRECTION = (
    "⚠️ **Correction:** I can't fully ground that in the documentation, so please "
    "disregard the previous message. "
)


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #

def init() -> None:
    """Create a fresh conversation in session state, once."""
    ss = st.session_state
    if ss.get("asst_ready"):
        return
    ss.asst_conversation_id = chatlog.new_conversation_id()
    ss.asst_started_at = chatlog.now_iso()
    ss.asst_messages = [{"role": "assistant", "content": GREETING}]
    ss.asst_question_count = 0
    ss.asst_stage = "chat"                       # chat | feedback | offer_ticket | done
    ss.asst_grounding_checks = []
    ss.asst_failure_signals = []
    ss.asst_failure_reasons = []
    ss.asst_thumbs = None
    ss.asst_ticket_id = None
    ss.asst_ticket_draft = None                  # (subject, category, summary)
    ss.asst_duplicate_of = None                  # {key, summary, similarity}
    ss.asst_dup_dismissed = False
    ss.asst_needed_by = None
    ss.asst_due_date = None
    ss.asst_logged = False
    ss.asst_pending = None                       # True while an answer is streaming
    ss.asst_pending_q = None
    ss.asst_chat = bot.fresh_chat()
    ss.asst_ready = True


def reset(*, log_abandoned: bool = True) -> None:
    """Drop the conversation and start a new one. Logs an `abandoned` record for
    a chat that asked at least one question and never reached a terminal state."""
    ss = st.session_state
    if (log_abandoned and not ss.get("asst_logged")
            and ss.get("asst_question_count", 0) > 0):
        log_conversation("abandoned")
    for key in [k for k in ss.keys() if k.startswith("asst_")]:
        del ss[key]
    init()


def transcript() -> str:
    return "\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
        for m in st.session_state.asst_messages
    )


# --------------------------------------------------------------------------- #
# Turn: ask -> stream -> resolve
# --------------------------------------------------------------------------- #

def ask(text: str) -> None:
    """Record a user question and mark an answer as pending. The widget then
    streams `stream_reply()` and calls `resolve_pending()`."""
    ss = st.session_state
    ss.asst_messages.append({"role": "user", "content": text})
    ss.asst_question_count += 1
    ss.asst_pending = True
    ss.asst_pending_q = text


def stream_reply():
    """Generator of answer text chunks for `st.write_stream`. Verification runs
    afterwards in `resolve_pending`, not here (stream-then-correct)."""
    ss = st.session_state
    question = ss.get("asst_pending_q") or ""
    yield from bot.respond_stream(ss.asst_chat, question)


def resolve_pending(draft: str) -> None:
    """Run the verification pass over the streamed `draft`, append the final
    assistant message(s), and advance the stage. Mirrors `engine.ask`'s tail."""
    ss = st.session_state
    question = ss.get("asst_pending_q") or ""
    ss.asst_pending = None
    ss.asst_pending_q = None

    result = bot.finalize_answer(question, draft)
    ss.asst_grounding_checks.append(result.log_entry(question))

    ss.asst_messages.append({"role": "assistant", "content": draft})
    walked_back = result.grounding.is_refusal_worthy and result.text != draft
    if walked_back:
        ss.asst_messages.append(
            {"role": "assistant", "content": _CORRECTION + result.text}
        )

    if result.refused or result.grounding.is_refusal_worthy:
        _enter_failure(grounding_failed=result.grounding.is_refusal_worthy)
    elif ss.asst_question_count >= config.QUESTIONS_BEFORE_TICKET:
        _enter_failure()                     # "taking a while" — offer a ticket
    else:
        ss.asst_stage = "feedback"


# --------------------------------------------------------------------------- #
# Feedback / failure
# --------------------------------------------------------------------------- #

def feedback(helpful: bool) -> None:
    ss = st.session_state
    if helpful:
        ss.asst_thumbs = "up"
        ss.asst_messages.append(
            {"role": "assistant", "content": "Great — glad I could help! 🎉"}
        )
        ss.asst_stage = "done"
        log_conversation("resolved")
    else:
        ss.asst_thumbs = "down"
        _enter_failure(thumbs_down=True)


def tell_me_more() -> None:
    ss = st.session_state
    ss.asst_stage = "chat"
    ss.asst_messages.append(
        {"role": "assistant",
         "content": "Okay — what else can you tell me about the issue?"}
    )


def _enter_failure(*, grounding_failed: bool = False,
                   thumbs_down: bool = False) -> None:
    ss = st.session_state
    sig = failure_capture.detect_failures(
        ss.asst_messages, thumbs_down=thumbs_down, grounding_failed=grounding_failed
    )
    ss.asst_failure_signals = sorted(
        set(ss.asst_failure_signals) | set(sig.as_list())
    )
    for reason in sig.reasons:
        if reason not in ss.asst_failure_reasons:
            ss.asst_failure_reasons.append(reason)
    ss.asst_stage = "offer_ticket"
    # Capture the failed chat now; a later ticket / duplicate-link / resolution
    # updates this same row (chatlog.append upserts on conversation_id).
    log_conversation("unresolved")


# --------------------------------------------------------------------------- #
# Ticket   (deterministic draft -> dedup -> Jira create; same sink as before)
# --------------------------------------------------------------------------- #

def prepare_ticket() -> None:
    """Build the no-model-call draft and run the duplicate check, once."""
    ss = st.session_state
    if ss.get("asst_ticket_draft") is not None:
        return
    draft = ticketing.default_draft(transcript())
    ss.asst_ticket_draft = (draft.subject, draft.category, draft.summary)
    ss.asst_duplicate_of = None
    dup = jira_dedup.find_duplicate(draft.subject, draft.summary)
    if dup:
        ss.asst_duplicate_of = {
            "key": dup.key, "summary": dup.summary,
            "similarity": round(dup.similarity, 3),
        }


def link_duplicate() -> None:
    ss = st.session_state
    key = (ss.get("asst_duplicate_of") or {}).get("key")
    ref = f" **[{key}]({jira_client.browse_url(key)})**" if key else ""
    ss.asst_ticket_id = None
    ss.asst_messages.append({
        "role": "assistant",
        "content": f"Linked you to existing ticket{ref} — the team is already "
                   "tracking it.",
    })
    ss.asst_stage = "done"
    log_conversation("linked_duplicate")
    ss.asst_ticket_draft = None


def file_ticket(*, name: str, email: str, subject: str, summary: str,
                needed_iso: str | None = None) -> str:
    """Create the Jira issue, append the ✅ message, log `ticket_filed`, return
    the key. Raises on a Jira failure — the caller shows the error."""
    ss = st.session_state
    category = (ss.get("asst_ticket_draft") or (None, "Other", None))[1] or "Other"
    due_date = ticketing.as_iso_date(needed_iso)
    urgency = ticketing.urgency_for_date(due_date)
    key = jira_client.create_issue(
        subject=subject, category=category, summary=summary, contact=email,
        transcript=transcript(), question_count=ss.asst_question_count,
        submitter_name=name or None, due_date=due_date, urgency=urgency,
    )
    ss.asst_ticket_id = key
    ss.asst_ticket_draft = (subject, category, summary)
    ss.asst_needed_by = due_date
    ss.asst_due_date = due_date
    ss.asst_dup_dismissed = False
    when = f"\n\n**Target date:** {due_date}" if due_date else ""
    ss.asst_messages.append({
        "role": "assistant",
        "content": (
            f"✅ Ticket **[{key}]({jira_client.browse_url(key)})** created."
            f"\n\n**Subject:** {subject}{when}\n\nOur team will follow up "
            f"at **{email}**."
        ),
    })
    ss.asst_stage = "done"
    log_conversation("ticket_filed")
    return key


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #

def log_conversation(outcome: str) -> None:
    """Upsert the conversation record (JSONL locally, `chat_logs` when a
    DATABASE_URL is set). Never raises — a logging hiccup must not break chat."""
    ss = st.session_state
    draft = ss.get("asst_ticket_draft") or (None, None, None)
    record = chatlog.ConversationRecord(
        conversation_id=ss.asst_conversation_id,
        started_at=ss.asst_started_at,
        ended_at=chatlog.now_iso(),
        outcome=outcome,
        question_count=ss.asst_question_count,
        messages=list(ss.asst_messages),
        failure_signals=sorted(set(ss.asst_failure_signals)),
        failure_reasons=list(ss.asst_failure_reasons),
        grounding_checks=list(ss.asst_grounding_checks),
        thumbs=ss.asst_thumbs,
        ticket_id=ss.asst_ticket_id,
        ticket_category=draft[1] if ss.asst_ticket_id else None,
        needed_by=ss.asst_needed_by,
        due_date=ss.asst_due_date,
        duplicate_of=(ss.asst_duplicate_of or {}).get("key"),
    )
    try:
        chatlog.append(record)
    except Exception as exc:  # noqa: BLE001 - best-effort logging
        log.warning("chat log append failed (%s): %s", type(exc).__name__, exc)
    ss.asst_logged = True
