"""
SugboDoc Support Assistant — standalone Streamlit demo.

Pure Streamlit: no FastAPI, no separate backend, no HTML/JS front end making
requests. The support assistant runs entirely in-process via `core/`.

    pip install -r requirements.txt
    #  add GEMINI_API_KEY (+ JIRA_* / DATABASE_URL) to .streamlit/secrets.toml
    streamlit run streamlit_app.py
    #  or, fully offline:  LLM_BACKEND=mock streamlit run streamlit_app.py

This entrypoint mirrors the shape of the umbrella "SugboDoc" app it merges into:
a dashboard rendered as a static backdrop + a floating assistant widget. In the
umbrella, `render_floating_assistant()` is the only piece that carries over —
see MERGE.md.
"""

from __future__ import annotations

# MERGE SEAM #1 — must run before importing config / core / assistant.widget.
from assistant.bootstrap import load_secrets

load_secrets()

import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402

import config  # noqa: E402
from assistant.widget import render_floating_assistant  # noqa: E402
from core import jira_client  # noqa: E402

st.set_page_config(page_title="SugboDoc Support", page_icon="🩺", layout="wide")

_WIDGET_HTML = config.ROOT / "web" / "index.html"


def _dashboard_backdrop() -> str:
    """The static SugboDoc dashboard mock from web/index.html, with the old
    JS widget + FAB + <script> stripped out (the real widget is the Streamlit
    one). Falls back to a plain heading if the file is missing."""
    try:
        html = _WIDGET_HTML.read_text(encoding="utf-8")
    except OSError:
        return "<h1 style='font-family:system-ui'>SugboDoc eClinic</h1>"
    marker = "<!-- ============ Floating support assistant ============ -->"
    if marker in html:
        html = html.split(marker, 1)[0] + "</body>\n</html>"
    return html


with st.sidebar:
    st.subheader("🩺 SugboDoc Support")
    st.caption("Standalone demo of the floating assistant. The widget is bottom-right.")
    if config.LLM_BACKEND == "mock":
        st.info("`LLM_BACKEND=mock` — offline canned answers.")
    elif not config.get_api_key():
        st.error("Set `GEMINI_API_KEY` in `.streamlit/secrets.toml`, or run with "
                 "`LLM_BACKEND=mock`.")
    else:
        st.caption(f"Answer model: `{config.ANSWER_MODEL}` · "
                   f"verify: {'on' if config.VERIFY_ANSWERS else 'off'}")
    st.caption("🟢 Jira ready" if jira_client.jira_configured()
               else "🔴 Jira not configured — ticket form will explain")
    st.caption("🟢 Chat logs → Postgres" if config.DATABASE_URL
               else "🟡 Chat logs → local file (ephemeral on Community Cloud)")

components.html(_dashboard_backdrop(), height=900, scrolling=True)

render_floating_assistant()
