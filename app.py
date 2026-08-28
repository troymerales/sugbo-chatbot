"""
SugboDoc Support Assistant — minimal Streamlit chatbot (Gemini).

Answers are grounded in SugboDoc-Documentation.md, which is loaded into the model's
system instruction on startup.

Flow:
  1. Greets the user, waits for a question.
  2. Answers with Gemini (using the docs), then asks "Did that help?" after every answer.
  3. "Yes"  -> conversation resolved.
     "No"   -> keep chatting.
  4. Once the user has asked 3 questions without resolution, it offers to file
     a support ticket ("this is taking a while to solve...").
  5. If the user accepts, the conversation is summarized into a ticket and
     appended to tickets.csv.

Run:
    pip install -r requirements.txt
    # provide a key one of these ways:
    #   - .streamlit/secrets.toml  ->  GEMINI_API_KEY = "..."
    #   - environment variable     ->  set GEMINI_API_KEY=...
    #   - paste it into the sidebar
    streamlit run app.py
"""

from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path

import streamlit as st
from google import genai
from google.genai import types

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

MODEL = "gemini-2.5-flash"          # or "gemini-2.0-flash", "gemini-2.5-pro"
TICKETS_CSV = Path("tickets.csv")
DOCS_PATH = Path("SugboDoc-Documentation.md")
QUESTIONS_BEFORE_TICKET = 3

PERSONA = """You are the SugboDoc support assistant. SugboDoc is a clinic and
practice-management SaaS.

Answer using ONLY the documentation provided below. Give step-by-step instructions
when the user is trying to accomplish a task, and mention the relevant section
heading. If the answer is not in the documentation, say plainly that you don't
have that information in your records rather than guessing.
"""


def build_system_prompt() -> str:
    try:
        docs = DOCS_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return PERSONA + "\n\n(Note: documentation file not found.)"
    return f"{PERSONA}\n\n===== SUGBODOC DOCUMENTATION =====\n\n{docs}\n\n===== END DOCUMENTATION ====="

GREETING = "Hi! I'm the SugboDoc support assistant. What can I help you with today?"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def get_api_key() -> str | None:
    """Look for the key in secrets, then env, then the sidebar input."""
    try:
        if "GEMINI_API_KEY" in st.secrets:
            return st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass
    return (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or st.session_state.get("api_key_input")
    )


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
    st.session_state.stage = "feedback"


def generate_ticket(client: genai.Client) -> tuple[str, str, str]:
    """Summarize the conversation into (subject, category, description)."""
    prompt = (
        "Summarize the following support conversation into a ticket.\n"
        "Reply in EXACTLY this format, nothing else:\n"
        "Subject: <one short line>\n"
        "Category: <one of: Scheduling, Patients, Clinical, Billing, "
        "Immunization, Staff/Admin, Account, Other>\n"
        "Description: <2-4 sentences: the problem and what was already tried>\n\n"
        "Conversation:\n" + transcript_text()
    )
    subject, category, description = "Support request", "Other", ""
    try:
        text = client.models.generate_content(model=MODEL, contents=prompt).text or ""
    except Exception:  # noqa: BLE001
        text = ""
    for line in text.splitlines():
        low = line.lower().strip()
        if low.startswith("subject:"):
            subject = line.split(":", 1)[1].strip() or subject
        elif low.startswith("category:"):
            category = line.split(":", 1)[1].strip() or category
        elif low.startswith("description:"):
            description = line.split(":", 1)[1].strip()
    if not description:
        description = transcript_text()[:2000]
    return subject, category, description


def save_ticket(subject: str, category: str, description: str, contact: str) -> str:
    ticket_id = f"TKT-{datetime.now():%Y%m%d-%H%M%S}"
    row = {
        "ticket_id": ticket_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "subject": subject,
        "category": category,
        "description": description,
        "contact": contact,
        "questions_asked": st.session_state.question_count,
        "transcript": transcript_text(),
    }
    write_header = not TICKETS_CSV.exists()
    with TICKETS_CSV.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(row))
        if write_header:
            writer.writeheader()
        writer.writerow(row)
    return ticket_id


def reset_conversation() -> None:
    for key in ("messages", "question_count", "stage", "last_ticket_id", "chat"):
        st.session_state.pop(key, None)


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #

st.set_page_config(page_title="SugboDoc Support", page_icon="🩺")
st.title("🩺 SugboDoc Support Assistant")

# --- session state defaults ---
st.session_state.setdefault("messages", [{"role": "assistant", "content": GREETING}])
st.session_state.setdefault("question_count", 0)
st.session_state.setdefault("stage", "chat")          # chat | feedback | offer_ticket | ticket_form | done
st.session_state.setdefault("last_ticket_id", None)

# --- API key gate ---
api_key = get_api_key()
with st.sidebar:
    st.subheader("Settings")
    st.text(f"Model: {MODEL}")
    if DOCS_PATH.exists():
        st.caption(f"📄 Grounded on `{DOCS_PATH.name}`")
    else:
        st.caption(f"⚠️ `{DOCS_PATH.name}` not found — answering without docs")
    if not api_key:
        st.text_input("Gemini API key", type="password", key="api_key_input")
        api_key = get_api_key()
    st.metric("Questions this chat", st.session_state.question_count)
    if TICKETS_CSV.exists():
        st.caption(f"Tickets saved in `{TICKETS_CSV.name}`")
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

# --- stage-specific UI ---
stage = st.session_state.stage

if stage == "chat":
    if prompt := st.chat_input("Type your question…"):
        with st.spinner("Thinking…"):
            answer_user(prompt)
        st.rerun()

elif stage == "feedback":
    with st.chat_message("assistant"):
        st.write("Did that help?")
        col_yes, col_no = st.columns(2)
        if col_yes.button("👍 Yes", use_container_width=True):
            st.session_state.messages.append(
                {"role": "assistant", "content": "Great — glad I could help! 🎉"}
            )
            st.session_state.stage = "done"
            st.rerun()
        if col_no.button("👎 No", use_container_width=True):
            if st.session_state.question_count >= QUESTIONS_BEFORE_TICKET:
                st.session_state.stage = "offer_ticket"
            else:
                st.session_state.messages.append(
                    {"role": "assistant",
                     "content": "No problem — tell me more and I'll try again."}
                )
                st.session_state.stage = "chat"
            st.rerun()

elif stage == "offer_ticket":
    with st.chat_message("assistant"):
        st.warning(
            "This is taking a while to solve. Would you like to submit a support "
            "ticket so our team can follow up?"
        )
        col_yes, col_no = st.columns(2)
        if col_yes.button("📨 Yes, create a ticket", use_container_width=True):
            st.session_state.stage = "ticket_form"
            st.rerun()
        if col_no.button("Keep trying", use_container_width=True):
            st.session_state.messages.append(
                {"role": "assistant",
                 "content": "Okay — what else can you tell me about the issue?"}
            )
            st.session_state.stage = "chat"
            st.rerun()

elif stage == "ticket_form":
    with st.chat_message("assistant"):
        st.write("I'll summarize this conversation into a ticket.")
        with st.form("ticket_form"):
            contact = st.text_input("Your email (optional)")
            submitted = st.form_submit_button("Submit ticket")
        if submitted:
            with st.spinner("Creating ticket…"):
                subject, category, description = generate_ticket(client)
                ticket_id = save_ticket(subject, category, description, contact)
            st.session_state.last_ticket_id = ticket_id
            st.session_state.messages.append({
                "role": "assistant",
                "content": (
                    f"✅ Ticket **{ticket_id}** created and saved.\n\n"
                    f"**Subject:** {subject}  \n**Category:** {category}\n\n"
                    "Our team will follow up"
                    + (f" at **{contact}**." if contact else " shortly.")
                ),
            })
            st.session_state.stage = "done"
            st.rerun()

elif stage == "done":
    if st.session_state.last_ticket_id:
        st.success(
            f"Ticket {st.session_state.last_ticket_id} appended to {TICKETS_CSV.name}"
        )
    st.chat_message("assistant").write("Use **Start a new chat** in the sidebar to ask something else.")
