"""
Streamlit-only helpers shared by the STT pages (``pages/1_Consultation_Transcript.py``,
``pages/2_Past_Notes.py``, ``pages/3_Evaluation.py``).

The app shell (left nav + top bar) lives in ``shell.py``; this module is just the
small render helpers. Nothing in ``stt/`` imports it -- it's the one place allowed
to know about both Streamlit and the ``stt`` layer (the mirror of ``core/`` <->
``assistant/``).
"""

from __future__ import annotations

from contextlib import contextmanager

import streamlit as st

from stt.gemini import LLM_EXHAUSTED_MESSAGE, LLMQuotaError, LLMUnavailableError
from stt.schemas import SECTIONS


@contextmanager
def llm_guard(action: str = "That step"):
    """Wrap an LLM-backed action so a quota / missing-key failure renders a clean
    message instead of a traceback, and the page keeps going."""
    try:
        yield
    except LLMQuotaError:
        st.error(LLM_EXHAUSTED_MESSAGE, icon=":material/hourglass_empty:")
    except LLMUnavailableError:
        st.warning("The SOAP model isn't configured -- add a Gemini API key in the sidebar.",
                   icon=":material/key:")
    except Exception as e:  # noqa: BLE001 -- last-resort net
        st.error(f"{action} failed: {e}")


def editable_soap(soap: dict[str, str], *, key_prefix: str) -> dict[str, str]:
    edited: dict[str, str] = {}
    for section in SECTIONS:
        edited[section] = st.text_area(
            section, value=soap.get(section, ""), key=f"{key_prefix}_{section}", height=140
        )
    return edited


def render_extract(extract: dict) -> None:
    if not extract or not any(extract.values()):
        st.caption("No structured data extracted yet.")
        return
    for key, val in extract.items():
        if not val:
            continue
        label = key.replace("_", " ").capitalize()
        if isinstance(val, list):
            if val and isinstance(val[0], dict):
                val = ", ".join(f"{d.get('name','')}: {d.get('value','')}" for d in val)
            else:
                val = ", ".join(str(v) for v in val)
        st.markdown(f"**{label}:** {val}")


def render_review(review: dict) -> None:
    if not review:
        st.caption("No grounding review yet.")
        return
    c1, c2 = st.columns(2)
    c1.metric("Grounding", f"{review.get('grounding_score', '?')}/5")
    c2.metric("Completeness", f"{review.get('completeness_score', '?')}/5")
    unsupported = review.get("unsupported_statements") or []
    missing = review.get("missing_elements") or []
    if unsupported:
        st.markdown("**Unsupported statements**")
        for s in unsupported:
            st.markdown(f"- :red[{s}]")
    if missing:
        st.markdown("**Missing from the note**")
        for s in missing:
            st.markdown(f"- :orange[{s}]")
    if review.get("summary"):
        st.info(review["summary"])
    if not unsupported and not missing:
        st.success("No grounding or completeness issues flagged.")
