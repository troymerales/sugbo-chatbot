"""Past Notes — browse, search, edit, re-run, export, and delete saved SOAP notes."""

from __future__ import annotations

from assistant.bootstrap import load_secrets

load_secrets()

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from assistant.widget import render_floating_assistant  # noqa: E402
from stt import export  # noqa: E402
from stt import notes_db as db  # noqa: E402
from stt.config import get_settings  # noqa: E402
from shell import panel, render_shell  # noqa: E402
from stt.schemas import SoapNote  # noqa: E402
from stt_ui import editable_soap, llm_guard, render_extract, render_review  # noqa: E402

st.set_page_config(page_title="Past Notes", page_icon="📁", layout="wide",
                   initial_sidebar_state="expanded")
db.init_db()
settings = get_settings()
render_shell("past-notes")

st.title("📁 Past Notes")
st.caption("Every consult you've saved — search, edit, re-run the model, or export.")

PAGE_SIZE = 15
if "notes_page" not in st.session_state:
    st.session_state.notes_page = 0

browse = st.container(key="sdpanel_browse")
search = browse.text_input("Search", placeholder="title, patient ref, transcript, SOAP text, tags")
if search != st.session_state.get("_last_search"):
    st.session_state.notes_page = 0
    st.session_state._last_search = search

total = db.count_notes(search=search)
if total == 0:
    browse.info("No notes yet. Create one on the Consultation Transcript page.")
    render_floating_assistant()
    st.stop()

pages = max(1, -(-total // PAGE_SIZE))
st.session_state.notes_page = min(st.session_state.notes_page, pages - 1)
offset = st.session_state.notes_page * PAGE_SIZE
rows = db.list_notes(search=search, limit=PAGE_SIZE, offset=offset)

table = pd.DataFrame(
    [
        {
            "id": r["id"],
            "created": r["created_at"].replace("T", " ").replace("+00:00", ""),
            "title": r["title"],
            "patient": r["patient_ref"],
            "assessment": (r["soap"].get("Assessment") or "")[:80],
            "grounding": r["review"].get("grounding_score", ""),
            "tags": r["tags"],
        }
        for r in rows
    ]
)
browse.dataframe(table, use_container_width=True, hide_index=True)

with browse:
    nav_prev, nav_info, nav_next = st.columns([1, 2, 1])
if nav_prev.button("← Newer", use_container_width=True, disabled=st.session_state.notes_page == 0):
    st.session_state.notes_page -= 1
    st.rerun()
nav_info.caption(f"Page {st.session_state.notes_page + 1} / {pages} · {total} notes")
if nav_next.button("Older →", use_container_width=True,
                   disabled=st.session_state.notes_page >= pages - 1):
    st.session_state.notes_page += 1
    st.rerun()

ids = [r["id"] for r in rows]
selected = browse.selectbox(
    "Open note", ids,
    format_func=lambda i: next(f"#{r['id']} · {r['title'] or 'Untitled'}" for r in rows if r["id"] == i),
)
note = db.get_note(selected)
if not note:
    render_floating_assistant()
    st.stop()

if st.session_state.get("_open_note") != selected:
    for k in list(st.session_state.keys()):
        if k.startswith(("edit_", "pn_soap_")):
            del st.session_state[k]
    st.session_state._open_note = selected

meta = st.columns(4)
meta[0].metric("Created", note["created_at"][:10])
meta[1].metric("Updated", note["updated_at"][:10])
meta[2].metric("Audio", f"{note['duration_s']:.0f}s" if note.get("duration_s") else "—")
meta[3].metric("Grounding", f"{note['review'].get('grounding_score', '?')}/5" if note.get("review") else "—")

with panel("note"):
    st.subheader(f"Note #{note['id']}")
    title = st.text_input("Title", value=note["title"], key="edit_title")
    c1, c2 = st.columns(2)
    patient_ref = c1.text_input("Patient reference", value=note["patient_ref"], key="edit_patient")
    tags = c2.text_input("Tags", value=note["tags"], key="edit_tags")
    context = st.text_input("Context", value=note["context"], key="edit_context")

    transcript = st.text_area("Transcript", value=note["transcript"],
                              key="edit_transcript", height=180)

    st.markdown("### SOAP")
    soap = editable_soap(note["soap"] or SoapNote().as_sections(), key_prefix="pn_soap")

    with st.expander("Structured clinical data"):
        render_extract(note.get("extract") or {})
    with st.expander("Grounding review"):
        render_review(note.get("review") or {})

with panel("actions"):
    st.subheader("Actions")
    a1, a2, a3, a4 = st.columns(4)
    action_status = st.container()
llm_ok = settings.llm_available

if a1.button("Save changes", type="primary", use_container_width=True):
    db.update_note(
        note["id"], title=title, patient_ref=patient_ref, tags=tags, context=context,
        transcript=transcript, soap=soap,
    )
    st.success("Saved.")
    st.rerun()

if a2.button("Regenerate SOAP", use_container_width=True,
              disabled=not (llm_ok and transcript.strip())):
    from stt.soap import generate_soap_note

    with llm_guard("SOAP regeneration"):
        with st.spinner("Regenerating…"):
            new = generate_soap_note(transcript, context=context or None)
        db.update_note(note["id"], soap=new.as_sections(), review={})
        for k in list(st.session_state.keys()):
            if k.startswith("pn_soap_"):
                del st.session_state[k]
        st.success("SOAP regenerated.")
        st.rerun()

if a3.button("Re-extract + review", use_container_width=True,
              disabled=not (llm_ok and transcript.strip())):
    from stt.extract import extract_clinical_facts
    from stt.review import review_soap_note

    with llm_guard("Re-extract + review"):
        with st.spinner("Working…"):
            extract = extract_clinical_facts(transcript).model_dump()
            review = review_soap_note(transcript, SoapNote.from_sections(soap)).model_dump()
        db.update_note(note["id"], extract=extract, review=review)
        st.success("Updated.")
        st.rerun()

if a4.button("Delete note", use_container_width=True):
    st.session_state._confirm_delete = note["id"]

if st.session_state.get("_confirm_delete") == note["id"]:
    action_status.warning("Delete this note permanently?")
    with action_status:
        d1, d2 = st.columns(2)
    if d1.button("Yes, delete", type="primary", use_container_width=True):
        db.delete_note(note["id"])
        st.session_state.pop("_confirm_delete", None)
        st.session_state.pop("_open_note", None)
        st.rerun()
    if d2.button("Cancel", use_container_width=True):
        st.session_state.pop("_confirm_delete", None)
        st.rerun()

fresh = db.get_note(note["id"])
with panel("export"):
    st.subheader("Export")
    st.caption("Download this note for the patient chart or a referral letter.")
    e1, e2, e3 = st.columns(3)
e1.download_button("Markdown", export.to_markdown(fresh), use_container_width=True,
                   file_name=f"soap_{note['id']}.md")
e2.download_button("Plain text", export.to_text(fresh), use_container_width=True,
                   file_name=f"soap_{note['id']}.txt")
if export.pdf_available():
    e3.download_button("PDF", export.to_pdf(fresh), use_container_width=True,
                       file_name=f"soap_{note['id']}.pdf", mime="application/pdf")
else:
    e3.caption("`pip install reportlab` for PDF")


render_floating_assistant()
