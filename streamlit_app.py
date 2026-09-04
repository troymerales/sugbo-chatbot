"""
SugboDoc — Streamlit multipage app. This file is the entrypoint / router; the
home page is `home.py`.

    pip install -r requirements-dev.txt
    #  add GEMINI_API_KEY, HF_TOKEN (+ JIRA_* / DATABASE_URL) to .streamlit/secrets.toml
    streamlit run streamlit_app.py
    #  or, fully offline:  LLM_BACKEND=mock streamlit run streamlit_app.py

The nav is `position="hidden"` on purpose: every page renders the eClinic shell
(left rail + top bar) itself via `shell.render_shell()`, which draws its own
navigation styled to match `web/dashboard.html`.
"""

from __future__ import annotations

# MERGE SEAM #1 — must run before importing config / core / stt / assistant.
from assistant.bootstrap import load_secrets

load_secrets()

import streamlit as st  # noqa: E402

st.set_page_config(page_title="SugboDoc", page_icon="🩺", layout="wide",
                   initial_sidebar_state="expanded")

_PAGES = [
    # default=True -> served at "/" ; a url_path here would be ignored.
    st.Page("home.py", title="Dashboard", icon=":material/dashboard:", default=True),
    st.Page("pages/1_Consultation_Transcript.py", title="Consultation Transcript",
            icon="🎙️", url_path="consultation-transcript"),
    st.Page("pages/2_Past_Notes.py", title="Past Notes", icon="📁",
            url_path="past-notes"),
    st.Page("pages/3_Evaluation.py", title="Evaluation", icon="📊",
            url_path="evaluation"),
]

st.navigation(_PAGES, position="hidden").run()
