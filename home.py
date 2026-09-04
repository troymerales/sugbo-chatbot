"""
SugboDoc dashboard — the eClinic home screen.

The left navigation rail and the top bar are the real app shell (`shell.py`);
the dashboard body below is a static mockup. The only things that do anything
here are the rail's links and the floating 💬 support button.
"""

from __future__ import annotations

from assistant.bootstrap import load_secrets

load_secrets()

import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402

import config  # noqa: E402
from assistant.widget import render_floating_assistant  # noqa: E402
from shell import render_shell  # noqa: E402

_BODY = config.ROOT / "web" / "dashboard.html"

render_shell("dashboard")

try:
    components.html(_BODY.read_text(encoding="utf-8"), height=700, scrolling=True)
except OSError:
    st.error("`web/dashboard.html` not found.")

render_floating_assistant()
