"""
`render_floating_assistant()` — the shared floating support widget.

Call it once at the bottom of any page (Homepage, Consultation Transcript, …).
State lives in `st.session_state`, so the conversation follows the user from
page to page. The widget is a `st.popover` pinned bottom-right by `styles.py`;
its body is a `@st.fragment`, so typing in the widget reruns only the widget,
not the host page (which may be rendering a heavy dashboard iframe).
"""

from __future__ import annotations

import streamlit as st

import config
from assistant import session, styles
from assistant.ticket_dialog import ticket_dialog
from core import jira_client

_INPUT_STAGES = ("chat", "feedback", "offer_ticket")


def render_floating_assistant() -> None:
    session.init()
    styles.inject()
    with st.container(key="sugbodoc_assistant"):
        with st.popover("💬  Support", use_container_width=False):
            _panel()


@st.fragment
def _panel() -> None:
    ss = st.session_state

    st.markdown("**SugboDoc Assistant** — answers from the product documentation")

    for msg in ss.asst_messages:
        role = "user" if msg["role"] == "user" else "assistant"
        with st.chat_message(role):
            st.markdown(msg["content"])

    # An answer is mid-flight: stream it, verify, then rerun to show controls.
    if ss.get("asst_pending"):
        with st.chat_message("assistant"):
            draft = st.write_stream(session.stream_reply())
        session.resolve_pending(draft or "")
        st.rerun()

    _controls(ss.asst_stage)

    if ss.asst_stage in _INPUT_STAGES:
        with st.form("asst_input", clear_on_submit=True, border=False):
            text = st.text_input(
                "Message", label_visibility="collapsed",
                placeholder="Ask about scheduling, billing, encounters…",
            )
            sent = st.form_submit_button("Send", use_container_width=True)
        if sent and text.strip():
            session.ask(text.strip())
            st.rerun()


def _controls(stage: str) -> None:
    ss = st.session_state

    if stage == "feedback":
        st.caption("Did that help? You can also just keep typing.")
        c1, c2 = st.columns(2)
        if c1.button("👍 Yes", use_container_width=True, key="asst_fb_yes"):
            session.feedback(True)
            st.rerun()
        if c2.button("👎 No", use_container_width=True, key="asst_fb_no"):
            session.feedback(False)
            st.rerun()

    elif stage == "offer_ticket":
        if ss.asst_question_count >= config.QUESTIONS_BEFORE_TICKET:
            st.warning("This is taking a while — want to file a ticket?")
        else:
            st.caption("Sorry that didn't help. File a ticket, or tell me more?")
        c1, c2 = st.columns(2)
        if c1.button("📨 Submit a ticket", use_container_width=True, key="asst_mk"):
            ticket_dialog()
        if c2.button("💬 Tell me more", use_container_width=True, key="asst_more"):
            session.tell_me_more()
            st.rerun()

    elif stage == "done":
        tid = ss.asst_ticket_id
        if tid and jira_client.jira_configured():
            st.success(f"Ticket [{tid}]({jira_client.browse_url(tid)}) created in Jira.")
        if st.button("Start a new chat", use_container_width=True, key="asst_new"):
            session.reset()
            st.rerun()
