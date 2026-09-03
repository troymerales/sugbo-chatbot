"""
SugboDoc Support Assistant — Streamlit runtime bot.

The full inference path from the architecture doc:

  question
    -> answer model (grounded in SugboDoc-Documentation.md)
    -> verification pass (independent model call: is every claim in the docs?)
    -> grounded answer, or the canonical refusal
  feedback loop ("did that help?")
    -> rule-based failure capture
    -> offer a ticket
  ticket
    -> deterministic draft -> dedup against open Jira issues -> user review -> Jira REST create
  every conversation is logged to logs/chats.jsonl for the eval + analytics jobs.

Run:
    pip install -r requirements.txt
    #  copy .env.example -> .env, fill in GEMINI_API_KEY + JIRA_*
    streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

import config
from core import (
    bot,
    chatlog,
    failure_capture,
    jira_client,
    jira_dedup,
    knowledge,
    ticketing,
)
from core.llm import QuotaError

st.set_page_config(page_title="SugboDoc Support", page_icon="🩺")
st.title("🩺 SugboDoc Support Assistant")

GREETING = "Hi! I'm the SugboDoc support assistant. What can I help you with today?"


# --------------------------------------------------------------------------- #
# Session state
# --------------------------------------------------------------------------- #

def init_state() -> None:
    ss = st.session_state
    ss.setdefault("conversation_id", chatlog.new_conversation_id())
    ss.setdefault("started_at", chatlog.now_iso())
    ss.setdefault("messages", [{"role": "assistant", "content": GREETING}])
    ss.setdefault("question_count", 0)
    ss.setdefault("stage", "chat")            # chat | feedback | offer_ticket | done
    ss.setdefault("grounding_checks", [])
    ss.setdefault("failure_signals", [])
    ss.setdefault("failure_reasons", [])
    ss.setdefault("thumbs", None)             # "up" | "down" | None
    ss.setdefault("last_ticket_id", None)
    ss.setdefault("duplicate_of", None)
    ss.setdefault("logged", False)


def reset_conversation(*, log_abandoned: bool = True) -> None:
    ss = st.session_state
    if log_abandoned and not ss.get("logged") and ss.get("question_count", 0) > 0:
        _log_conversation("abandoned")
    for key in (
        "conversation_id", "started_at", "messages", "question_count", "stage",
        "grounding_checks", "failure_signals", "failure_reasons", "thumbs",
        "last_ticket_id", "duplicate_of", "logged", "chat", "ticket_draft",
        "open_ticket_dialog", "dup_dismissed", "needed_by", "due_date",
    ):
        ss.pop(key, None)


def transcript_text() -> str:
    return "\n".join(
        f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
        for m in st.session_state.messages
    )


def _log_conversation(outcome: str) -> None:
    ss = st.session_state
    record = chatlog.ConversationRecord(
        conversation_id=ss["conversation_id"],
        started_at=ss["started_at"],
        ended_at=chatlog.now_iso(),
        outcome=outcome,
        question_count=ss["question_count"],
        messages=list(ss["messages"]),
        failure_signals=sorted(set(ss.get("failure_signals", []))),
        failure_reasons=list(ss.get("failure_reasons", [])),
        grounding_checks=list(ss.get("grounding_checks", [])),
        thumbs=ss.get("thumbs"),
        ticket_id=ss.get("last_ticket_id"),
        ticket_category=(ss.get("ticket_draft") or (None, None, None))[1]
        if ss.get("last_ticket_id") else None,
        needed_by=ss.get("needed_by"),
        due_date=ss.get("due_date"),
        duplicate_of=(ss.get("duplicate_of") or {}).get("key"),
    )
    chatlog.append(record)
    ss["logged"] = True


# --------------------------------------------------------------------------- #
# Actions
# --------------------------------------------------------------------------- #

def handle_question(text: str) -> None:
    ss = st.session_state
    ss.messages.append({"role": "user", "content": text})
    ss.question_count += 1

    result = bot.respond(ss.chat, text)
    ss.messages.append({"role": "assistant", "content": result.text})
    ss.grounding_checks.append(result.log_entry(text))

    if result.refused or result.grounding.is_refusal_worthy:
        _enter_failure(grounding_failed=result.grounding.is_refusal_worthy)
    else:
        ss.stage = "feedback"


def _enter_failure(*, grounding_failed: bool = False, thumbs_down: bool = False) -> None:
    """Compute rule-based failure signals, then move to the ticket offer."""
    ss = st.session_state
    signals = failure_capture.detect_failures(
        ss.messages, thumbs_down=thumbs_down, grounding_failed=grounding_failed
    )
    ss.failure_signals = sorted(set(ss.failure_signals) | set(signals.as_list()))
    for reason in signals.reasons:
        if reason not in ss.failure_reasons:
            ss.failure_reasons.append(reason)
    ss.stage = "offer_ticket"
    # Capture the failed chat now; if a ticket / duplicate-link follows it
    # updates this same row (chatlog.append upserts on conversation_id).
    _log_conversation("unresolved")


# --------------------------------------------------------------------------- #
# Ticket modal
# --------------------------------------------------------------------------- #

@st.dialog("Submit a support ticket")
def ticket_dialog() -> None:
    ss = st.session_state
    st.caption("A separate ticket form — your chat stays exactly as it is.")

    if not jira_client.jira_configured():
        st.error(
            "Jira isn't configured. Add `JIRA_BASE_URL`, `JIRA_EMAIL`, "
            "`JIRA_API_TOKEN` and `JIRA_PROJECT_KEY` to `.env`, then restart."
        )
        if st.button("Close"):
            st.rerun()
        return

    if "ticket_draft" not in ss:
        with st.spinner("Preparing the ticket…"):
            draft = ticketing.default_draft(transcript_text())   # no model call
            ss.ticket_draft = (draft.subject, draft.category, draft.summary)
            ss.duplicate_of = None
            dup = jira_dedup.find_duplicate(draft.subject, draft.summary)
            if dup:
                ss.duplicate_of = {
                    "key": dup.key, "summary": dup.summary,
                    "similarity": round(dup.similarity, 3),
                }

    draft_subject, draft_category, draft_summary = ss.ticket_draft

    if ss.get("duplicate_of") and not ss.get("dup_dismissed"):
        d = ss.duplicate_of
        st.warning(
            f"This looks close to an existing open ticket "
            f"**[{d['key']}]({jira_client.browse_url(d['key'])})** — "
            f"*{d['summary']}* (similarity {d['similarity']}).",
        )
        c1, c2 = st.columns(2)
        if c1.button("That's my issue — don't file", use_container_width=True):
            ss.last_ticket_id = None
            ss.messages.append({
                "role": "assistant",
                "content": (
                    f"Linked you to existing ticket "
                    f"**[{d['key']}]({jira_client.browse_url(d['key'])})**. "
                    "The team is already tracking it."
                ),
            })
            ss.stage = "done"
            _log_conversation("linked_duplicate")
            ss.pop("ticket_draft", None)
            st.rerun()
        if c2.button("File a new one anyway", use_container_width=True):
            ss.dup_dismissed = True
            st.rerun()
        return

    with st.form("ticket_form"):
        name = st.text_input("Name (optional)", placeholder="Jane Dela Cruz")
        email = st.text_input("Your email", placeholder="you@example.com")
        subject = st.text_input("Subject", value=draft_subject)
        summary = st.text_area(
            "Summary", value=draft_summary, height=170,
            help="Edit freely — add anything that helps the team reproduce it.",
        )
        needed_date = st.date_input(
            "When do you need this? (optional)", value=None,
            help="Sets the ticket's due date; urgency is derived from how soon it is.",
        )
        col_submit, col_cancel = st.columns(2)
        submitted = col_submit.form_submit_button("Submit to Jira", use_container_width=True)
        cancelled = col_cancel.form_submit_button("Cancel", use_container_width=True)

    if cancelled:
        ss.pop("ticket_draft", None)
        ss.pop("dup_dismissed", None)
        st.rerun()

    if submitted:
        if not (email.strip() and subject.strip() and summary.strip()):
            st.error("Please fill in email, subject, and summary.")
            return
        due_date = needed_date.isoformat() if needed_date else None
        urgency = ticketing.urgency_for_date(due_date)
        try:
            with st.spinner("Creating the Jira issue…"):
                key = jira_client.create_issue(
                    subject=subject.strip(),
                    category=draft_category,
                    summary=summary.strip(),
                    contact=email.strip(),
                    transcript=transcript_text(),
                    question_count=ss.question_count,
                    submitter_name=name.strip() or None,
                    due_date=due_date,
                    urgency=urgency,
                )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Couldn't create the Jira issue:\n\n{exc}")
            return

        ss.last_ticket_id = key
        ss.ticket_draft = (subject.strip(), draft_category, summary.strip())
        ss["needed_by"] = due_date
        ss["due_date"] = due_date
        ss.pop("dup_dismissed", None)
        _when = f"\n\n**Target date:** {due_date}" if due_date else ""
        ss.messages.append({
            "role": "assistant",
            "content": (
                f"✅ Ticket **[{key}]({jira_client.browse_url(key)})** created in Jira.\n\n"
                f"**Subject:** {subject.strip()}{_when}\n\n"
                f"Our team will follow up at **{email.strip()}**."
            ),
        })
        ss.stage = "done"
        _log_conversation("ticket_filed")
        st.rerun()


# --------------------------------------------------------------------------- #
# App body
# --------------------------------------------------------------------------- #

init_state()

with st.sidebar:
    if config.DOCS_PATH.exists():
        st.caption(f"📄 Grounded on `{config.DOCS_PATH.name}` "
                   f"({len(knowledge.sections())} sections)")
    else:
        st.caption(f"⚠️ `{config.DOCS_PATH.name}` not found")

    if jira_client.jira_configured():
        st.caption(f"🟢 Jira: `{jira_client.JIRA_PROJECT_KEY}` · {jira_client.JIRA_ISSUE_TYPE}")
    else:
        st.caption("🔴 Jira not configured — see `.env.example`")

    if config.LLM_BACKEND == "mock":
        st.caption("🧪 backend: `mock` (offline, canned answers)")
    else:
        st.caption(f"🧠 answer: `{config.ANSWER_MODEL}` · verify: `{config.UTILITY_MODEL}`")

    _needs_key = config.LLM_BACKEND == "gemini" and not config.get_api_key()
    if _needs_key:
        st.error("Set `GEMINI_API_KEY` in `.env` (or run with `LLM_BACKEND=mock`).")

    st.metric("Questions this chat", st.session_state.question_count)
    if st.session_state.get("failure_signals"):
        st.caption("⚠️ signals: " + ", ".join(st.session_state["failure_signals"]))
    if st.session_state.get("failure_reasons"):
        st.caption("↳ " + "; ".join(st.session_state["failure_reasons"]))

    if st.button("Start a new chat"):
        reset_conversation()
        st.rerun()

if _needs_key:
    st.info("Add your Gemini API key to `.env` to begin (get one free at "
            "https://aistudio.google.com/apikey), or start with `LLM_BACKEND=mock "
            "streamlit run app.py` to try the flow offline.")
    st.stop()

st.session_state.setdefault("chat", bot.fresh_chat())

for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

if st.session_state.pop("open_ticket_dialog", False):
    ticket_dialog()

stage = st.session_state.stage


def question_box(label: str = "Type your question…") -> None:
    if prompt := st.chat_input(label):
        try:
            with st.spinner("Thinking…"):
                handle_question(prompt)
        except QuotaError as exc:
            st.error(str(exc))
            st.stop()
        st.rerun()


if stage == "chat":
    question_box()

elif stage == "feedback":
    with st.chat_message("assistant"):
        st.write("Did that help? You can also just keep typing below.")
        c_yes, c_no = st.columns(2)
        if c_yes.button("👍 Yes", use_container_width=True):
            st.session_state.thumbs = "up"
            st.session_state.messages.append(
                {"role": "assistant", "content": "Great — glad I could help! 🎉"}
            )
            st.session_state.stage = "done"
            _log_conversation("resolved")
            st.rerun()
        if c_no.button("👎 No", use_container_width=True):
            st.session_state.thumbs = "down"
            _enter_failure(thumbs_down=True)
            st.rerun()
    question_box()

elif stage == "offer_ticket":
    taking_long = st.session_state.question_count >= config.QUESTIONS_BEFORE_TICKET
    with st.chat_message("assistant"):
        if taking_long:
            st.warning("This is taking a while to solve. Want to submit a ticket, "
                       "or tell me more?")
        else:
            st.write("Sorry that didn't help. Want to submit a ticket, or tell me "
                     "more so I can try again?")
        c_yes, c_no = st.columns(2)
        if c_yes.button("📨 Submit a ticket", use_container_width=True):
            st.session_state.open_ticket_dialog = True
            st.rerun()
        if c_no.button("💬 Tell me more", use_container_width=True):
            st.session_state.messages.append(
                {"role": "assistant",
                 "content": "Okay — what else can you tell me about the issue?"}
            )
            st.session_state.stage = "chat"
            st.rerun()
    question_box("Or keep describing the issue…")

elif stage == "done":
    key = st.session_state.last_ticket_id
    if key and jira_client.jira_configured():
        st.success(f"Ticket {key} created in Jira.")
        st.markdown(f"[Open {key} in Jira]({jira_client.browse_url(key)})")
    st.chat_message("assistant").write(
        "Use **Start a new chat** in the sidebar to ask something else."
    )
