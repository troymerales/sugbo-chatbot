"""
MERGE SEAM #1 — where Streamlit's `st.secrets` meets the rest of the code.

`load_secrets()` copies every flat key in `.streamlit/secrets.toml` into
`os.environ` *without* overwriting a value already set in the real environment.
That lets the pure-Python layer under `core/` keep reading `os.environ` only and
never import Streamlit.

Call it as the FIRST thing in every Streamlit entrypoint / page, before
importing `config`, `core.*`, or `assistant.widget`:

    from assistant.bootstrap import load_secrets
    load_secrets()

At merge time this module goes away: the umbrella's own `core/config.py`
(st.secrets -> os.environ) does the same job. Delete this file and drop the two
lines above from each page (or replace with the umbrella's bootstrap).
"""

from __future__ import annotations

import os

_DONE = False


def load_secrets() -> None:
    """Idempotent. No-op when Streamlit or a secrets file is absent (so plain
    `python -m ...` / `LLM_BACKEND=mock` runs and the test-suite are unaffected)."""
    global _DONE
    if _DONE:
        return
    _DONE = True

    try:
        import streamlit as st
    except ModuleNotFoundError:
        return

    try:
        items = list(st.secrets.items())
    except Exception:
        # No secrets.toml configured at all — fine for local .env / mock runs.
        return

    for key, value in items:
        if isinstance(value, (dict, list)):
            continue  # nested sections don't map to a single env var
        os.environ.setdefault(str(key), str(value))
