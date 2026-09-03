"""
The support-ticket form, as an `@st.dialog`. Opened from a button in the widget.

Thin UI over `assistant.session` — the flow and the Jira sink are unchanged from
the old `web/index.html` modal and `app.py`'s dialog:  deterministic draft (no
model call)  ->  dedup against open Jira issues  ->  a review form  ->
`jira_client.create_issue`  ->  the ✅ message + a `ticket_filed` log record.
"""

from __future__ import annotations

import streamlit as st

from assistant import session
from core import jira_client


@st.dialog("Submit a support ticket")
def ticket_dialog() -> None:
    ss = st.session_state
    st.caption("A separate ticket form — your chat stays exactly as it is.")

    if not jira_client.jira_configured():
        st.error(
            "Jira isn't configured. Set `JIRA_BASE_URL`, `JIRA_EMAIL`, "
            "`JIRA_API_TOKEN` and `JIRA_PROJECT_KEY` (in `.streamlit/secrets.toml` "
            "or the environment), then reload."
        )
        return

    with st.spinner("Preparing the ticket…"):
        session.prepare_ticket()
    draft_subject, _, draft_summary = ss.asst_ticket_draft

    # ---- duplicate warning ------------------------------------------------ #
    dup = ss.get("asst_duplicate_of")
    if dup and not ss.get("asst_dup_dismissed"):
        st.warning(
            f"This looks close to an existing open ticket "
            f"**[{dup['key']}]({jira_client.browse_url(dup['key'])})** — "
            f"*{dup['summary']}* (similarity {dup['similarity']})."
        )
        c1, c2 = st.columns(2)
        if c1.button("That's my issue — link it", use_container_width=True):
            session.link_duplicate()
            st.rerun()
        if c2.button("File a new one anyway", use_container_width=True):
            ss.asst_dup_dismissed = True
            st.rerun()
        return

    # ---- the form ------------------------------------------------------- #
    with st.form("asst_ticket_form"):
        name = st.text_input("Name (optional)", placeholder="Jane Dela Cruz")
        email = st.text_input("Your email", placeholder="you@example.com")
        subject = st.text_input("Subject", value=draft_subject)
        summary = st.text_area(
            "Summary", value=draft_summary, height=160,
            help="Edit freely — add anything that helps the team reproduce it.",
        )
        needed = st.date_input(
            "When do you need this? (optional)", value=None,
            help="Sets the ticket's due date; urgency follows from how soon it is.",
        )
        c_submit, c_cancel = st.columns(2)
        submitted = c_submit.form_submit_button(
            "Submit to Jira", use_container_width=True
        )
        cancelled = c_cancel.form_submit_button("Cancel", use_container_width=True)

    if cancelled:
        ss.asst_ticket_draft = None
        ss.asst_dup_dismissed = False
        st.rerun()

    if submitted:
        if not (email.strip() and subject.strip() and summary.strip()):
            st.error("Please fill in email, subject, and summary.")
            return
        try:
            with st.spinner("Creating the Jira issue…"):
                session.file_ticket(
                    name=name.strip(), email=email.strip(),
                    subject=subject.strip(), summary=summary.strip(),
                    needed_iso=needed.isoformat() if needed else None,
                )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Couldn't create the Jira issue:\n\n{exc}")
            return
        st.rerun()
