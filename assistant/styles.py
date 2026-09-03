"""
The floating-widget CSS. Lifted from the palette of the old `web/index.html`
widget (indigo #3b41d6) and pared down to what pins a Streamlit `st.popover` to
the bottom-right corner and makes its trigger look like a chat FAB.

This is cosmetic only. If a Streamlit upgrade renames the DOM hooks the widget
still works — it just stops floating (it renders inline instead). Priority order
from the brief: (1) it works, (2) it feels like an assistant, (3) simple, (4)
pixel-perfect — so this deliberately leans on one stable hook, the
`st.container(key=...)` class, and nothing fragile.
"""

from __future__ import annotations

import streamlit as st

# st.container(key="sugbodoc_assistant") renders a wrapper with this class.
_ANCHOR = "st-key-sugbodoc_assistant"

_CSS = f"""
<style>
.{_ANCHOR} {{
    position: fixed;
    right: 1.5rem;
    bottom: 1.5rem;
    z-index: 9990;
    width: auto;
    max-width: 420px;
}}
.{_ANCHOR} [data-testid="stPopover"] > div > button,
.{_ANCHOR} button[kind="secondary"] {{
    border-radius: 999px;
    padding: 0.55rem 1.15rem;
    font-weight: 600;
    background: #3b41d6;
    color: #ffffff;
    border: 0;
    box-shadow: 0 10px 26px rgba(59, 65, 214, 0.42);
}}
.{_ANCHOR} [data-testid="stPopoverBody"] {{
    width: min(24rem, calc(100vw - 3rem));
    max-height: min(34rem, calc(100vh - 8rem));
}}
@media (max-width: 640px) {{
    .{_ANCHOR} {{ right: 0.75rem; bottom: 0.75rem; }}
}}
</style>
"""


def inject() -> None:
    """Emit the stylesheet once per session run."""
    st.markdown(_CSS, unsafe_allow_html=True)
