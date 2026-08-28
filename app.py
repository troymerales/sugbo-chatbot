"""
SugboDoc Support Assistant — minimal Streamlit chatbot (Gemini).

Answers are grounded in SugboDoc-Documentation.md, which is loaded into the model's
system instruction on startup.

Flow:
  1. Greets the user, waits for a question.
  2. Answers with Gemini (using the docs), then asks "Did that help?" after every answer.
  3. "Yes"  -> conversation resolved.
     "No"   -> submit a ticket, or tell me more.
  4. Once the user has asked 3 questions without resolution, it proactively offers
     to file a ticket ("this is taking a while to solve...").
  5. If the user accepts, a modal collects email / subject / summary (pre-filled
     with an AI draft) and creates a Jira issue via the REST API.

Run:
    pip install -r requirements.txt
    # copy .env.example -> .env and fill in GEMINI_API_KEY + the JIRA_* vars
    streamlit run app.py
"""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types

from jira_client import (
    JIRA_ISSUE_TYPE,
    JIRA_PROJECT_KEY,
    browse_url,
    create_issue,
    jira_configured,
)

load_dotenv(override=True)  # read .env into os.environ

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

MODEL = "gemini-3.6-flash"          # or "gemini-2.0-flash", "gemini-2.5-pro"
DOCS_PATH = Path("SugboDoc-Documentation.md")
QUESTIONS_BEFORE_TICKET = 3

PERSONA = """You are the SugboDoc support assistant. SugboDoc is a clinic and
practice-management SaaS.

Answer using ONLY the documentation provided below. Give step-by-step instructions
when the user is trying to accomplish a task, and mention the relevant section
heading. If the answer is not in the documentation, say plainly that you don't
have that information in your records rather than guessing.
"""

GREETING = "Hi! I'm the SugboDoc support assistant. What can I help you with today?"


def build_system_prompt() -> str:
    try:
        docs = DOCS_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return PERSONA + "\n\n(Note: documentation file not found.)"
    return f"{PERSONA}\n\n===== SUGBODOC DOCUMENTATION =====\n\n{docs}\n\n===== END DOCUMENTATION ====="


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def get_api_key() -> str | None:
    """Gemini key: secrets, then env."""
    try:
        if "GEMINI_API_KEY" in st.secrets:
            return st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass
    return os.environ.get("GEMINI_API_KEY")


@st.cache_resource(show_spinner=False)
def get_client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)


@st.cache_data(show_spinner=False)
def load_system_prompt() -> str:
    return build_system_prompt()


def new_chat(client: genai.Client):
    return client.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(system_instruction=load_system_prompt()),
    )


def transcript_text() -> str:
    lines = []
    for m in st.session_state.messages:
        who = "User" if m["role"] == "user" else "Assistant"
        lines.append(f"{who}: {m['content']}")
    return "\n".join(lines)


def answer_user(text: str) -> None:
    """Send the user's message to Gemini and store the reply."""
    st.session_state.messages.append({"role": "user", "content": text})
    st.session_state.question_count += 1
    try:
        reply = st.session_state.chat.send_message(text).text or "(no response)"
    except Exception as exc:  # noqa: BLE001 - surface any API error to the user
        reply = f"Sorry, something went wrong contacting Gemini:\n\n`{exc}`"
    st.session_state.messages.append({"role": "assistant", "content": reply})
    st.session_state.stage = (
        "offer_ticket"
        if st.session_state.question_count >= QUESTIONS_BEFORE_TICKET
        else "feedback"
    )


def draft_ticket(client: genai.Client) -> tuple[str, str, str]:
    """AI draft used to pre-fill the ticket form: (subject, category, summary)."""
    prompt = (
        "Draft a support ticket from this conversation.\n"
        "Reply in EXACTLY this format, nothing else:\n"
        "Subject: <one short line>\n"
        "Category: <one of: Scheduling, Patients, Clinical, Billing, "
        "Immunization, Staff/Admin, Account, Other>\n"
        "Summary: <2-4 sentences: the problem and what was already tried>\n\n"
        "Conversation:\n" + transcript_text()
    )
    subject, category, summary = "", "Other", ""
    try:
        text = client.models.generate_content(model=MODEL, contents=prompt).text or ""
    except Exception:  # noqa: BLE001
        text = ""
    for line in text.splitlines():
        low = line.lower().strip()
        if low.startswith("subject:"):
            subject = line.split(":", 1)[1].strip()
        elif low.startswith("category:"):
            category = line.split(":", 1)[1].strip() or "Other"
        elif low.startswith("summary:"):
            summary = line.split(":", 1)[1].strip()
    return subject, category, summary


# --------------------------------------------------------------------------- #
# Ticket modal
# --------------------------------------------------------------------------- #

def reset_conversation() -> None:
    for key in ("messages", "question_count", "stage", "last_ticket_id",
                "chat", "ticket_draft", "open_ticket_dialog"):
        st.session_state.pop(key, None)


@st.dialog("Submit a support ticket")
def ticket_dialog(client: genai.Client) -> None:
    """Separate modal window for filing a Jira ticket — kept apart from the chat."""
    st.caption("This opens a separate ticket form. Your chat stays as it is.")

    if not jira_configured():
        st.error(
            "Jira isn't configured. Add `JIRA_BASE_URL`, `JIRA_EMAIL`, "
            "`JIRA_API_TOKEN` and `JIRA_PROJECT_KEY` to your `.env`, then restart."
        )
        if st.button("Close"):
            st.rerun()
        return

    if "ticket_draft" not in st.session_state:
        with st.spinner("Preparing a draft…"):
            st.session_state.ticket_draft = draft_ticket(client)
    draft_subject, draft_category, draft_summary = st.session_state.ticket_draft

    with st.form("ticket_form"):
        email = st.text_input("Your email", placeholder="you@example.com")
        subject = st.text_input("Subject", value=draft_subject)
        summary = st.text_area(
            "Summary", value=draft_summary, height=170,
            help="Describe the issue in your own words — add any context that helps.",
        )
        col_submit, col_cancel = st.columns(2)
        submitted = col_submit.form_submit_button("Submit to Jira", use_container_width=True)
        cancelled = col_cancel.form_submit_button("Cancel", use_container_width=True)

    if cancelled:
        st.session_state.pop("ticket_draft", None)
        st.rerun()

    if submitted:
        if not (email.strip() and subject.strip() and summary.strip()):
            st.error("Please fill in email, subject, and summary.")
            return
        try:
            with st.spinner("Creating Jira issue…"):
                key = create_issue(
                    subject=subject.strip(),
                    category=draft_category,
                    summary=summary.strip(),
                    contact=email.strip(),
                    transcript=transcript_text(),
                    question_count=st.session_state.question_count,
                )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Couldn't create the Jira issue:\n\n{exc}")
            return
        st.session_state.last_ticket_id = key
        st.session_state.pop("ticket_draft", None)
        st.session_state.messages.append({
            "role": "assistant",
            "content": (
                f"✅ Ticket **[{key}]({browse_url(key)})** created in Jira.\n\n"
                f"**Subject:** {subject.strip()}\n\n"
                f"Our team will follow up at **{email.strip()}**."
            ),
        })
        st.session_state.stage = "done"
        st.rerun()


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #

st.set_page_config(page_title="SugboDoc Support", page_icon="🩺")
st.title("🩺 SugboDoc Support Assistant")

# --- session state defaults ---
st.session_state.setdefault("messages", [{"role": "assistant", "content": GREETING}])
st.session_state.setdefault("question_count", 0)
st.session_state.setdefault("stage", "chat")          # chat | feedback | offer_ticket | done
st.session_state.setdefault("last_ticket_id", None)

# --- sidebar / status ---
api_key = get_api_key()
with st.sidebar:
    if DOCS_PATH.exists():
        st.caption(f"📄 Grounded on `{DOCS_PATH.name}`")
    else:
        st.caption(f"⚠️ `{DOCS_PATH.name}` not found — answering without docs")
    if jira_configured():
        st.caption(f"🟢 Jira: `{JIRA_PROJECT_KEY}` · {JIRA_ISSUE_TYPE}")
    else:
        st.caption("🔴 Jira not configured — see `.env.example`")
    if not api_key:
        st.text_input("Gemini API key", type="password", key="api_key_input")
        api_key = api_key or st.session_state.get("api_key_input")
    st.metric("Questions this chat", st.session_state.question_count)
    if st.button("Start a new chat"):
        reset_conversation()
        st.rerun()

if not api_key:
    st.info(
        "Add your Gemini API key in the sidebar to begin. "
        "Get one free at https://aistudio.google.com/apikey"
    )
    st.stop()

client = get_client(api_key)
st.session_state.setdefault("chat", new_chat(client))

# --- render conversation ---
for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

# --- open the ticket modal when requested (consumed once) ---
if st.session_state.pop("open_ticket_dialog", False):
    ticket_dialog(client)

# --- stage-specific UI ---
stage = st.session_state.stage

if stage == "chat":
    if prompt := st.chat_input("Type your question…"):
        with st.spinner("Thinking…"):
            answer_user(prompt)
        st.rerun()

elif stage == "feedback":
    with st.chat_message("assistant"):
        st.write("Did that help? You can also just keep typing below.")
        col_yes, col_no = st.columns(2)
        if col_yes.button("👍 Yes", use_container_width=True):
            st.session_state.messages.append(
                {"role": "assistant", "content": "Great — glad I could help! 🎉"}
            )
            st.session_state.stage = "done"
            st.rerun()
        if col_no.button("👎 No", use_container_width=True):
            st.session_state.stage = "offer_ticket"
            st.rerun()
    # chat stays available; a follow-up here counts as another question
    if prompt := st.chat_input("Type your question…"):
        with st.spinner("Thinking…"):
            answer_user(prompt)
        st.rerun()

elif stage == "offer_ticket":
    taking_long = st.session_state.question_count >= QUESTIONS_BEFORE_TICKET
    with st.chat_message("assistant"):
        if taking_long:
            st.warning(
                "This is taking a while to solve. Would you like to submit a support "
                "ticket, or tell me more?"
            )
        else:
            st.write(
                "Sorry that didn't help. Would you like to submit a ticket, or tell "
                "me more so I can try again?"
            )
        col_yes, col_no = st.columns(2)
        if col_yes.button("📨 Submit a ticket", use_container_width=True):
            st.session_state.open_ticket_dialog = True
            st.rerun()
        if col_no.button("💬 Tell me more", use_container_width=True):
            st.session_state.messages.append(
                {"role": "assistant",
                 "content": "Okay — what else can you tell me about the issue?"}
            )
            st.session_state.stage = "chat"
            st.rerun()
    # typing here is the same as "tell me more"
    if prompt := st.chat_input("Or keep describing the issue…"):
        with st.spinner("Thinking…"):
            answer_user(prompt)
        st.rerun()

elif stage == "done":
    key = st.session_state.last_ticket_id
    if key:
        st.success(f"Ticket {key} created in Jira.")
        if jira_configured():
            st.markdown(f"[Open {key} in Jira]({browse_url(key)})")
    st.chat_message("assistant").write(
        "Use **Start a new chat** in the sidebar to ask something else."
    )
