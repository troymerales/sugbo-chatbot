"""
Consultation Transcript — Bisaya/Cebuano speech → SOAP note.

Upload or record a consult, transcribe it (fine-tuned Whisper via the HF
Inference API), draft an English SOAP note via Gemini, optionally extract
structured clinical data and run a grounding review, then save to the notes
database. Every field is editable before saving.
"""

from __future__ import annotations

from assistant.bootstrap import load_secrets

load_secrets()

import streamlit as st  # noqa: E402

from assistant.widget import render_floating_assistant  # noqa: E402
from stt import notes_db as db  # noqa: E402
from stt.audio import duration_seconds, read_upload  # noqa: E402
from stt.config import get_settings  # noqa: E402
from shell import panel, render_shell  # noqa: E402
from stt.schemas import SECTIONS, SoapNote  # noqa: E402
from stt_ui import editable_soap, llm_guard, render_extract, render_review  # noqa: E402

st.set_page_config(page_title="Consultation Transcript", page_icon="🎙️",
                   layout="wide", initial_sidebar_state="expanded")

db.init_db()
settings = get_settings()
render_shell("consultation-transcript")

st.title("🎙️ Consultation Transcript")
st.caption(
    "Transcribe a Bisaya/Cebuano consult, then draft an English SOAP note. "
    "Everything is editable before you save."
)

if "work" not in st.session_state:
    st.session_state.work = {
        "transcript": "", "soap": SoapNote().as_sections(), "extract": {}, "review": {},
        "audio_filename": "", "duration_s": None, "saved_id": None, "warnings": [],
    }
work = st.session_state.work


# ---------------------------------------------------------------- 1. audio ---
with panel("audio"):
    st.subheader("1 · Audio")
    st.caption("Upload a recording or capture one live, then transcribe it.")

    up_col, meta_col = st.columns([3, 2], gap="large")
    with up_col:
        uploaded = st.file_uploader(
            "Upload audio", type=["wav", "mp3", "m4a", "flac", "ogg"],
            label_visibility="collapsed",
        )
        recorded = st.audio_input("or record live from the microphone")
        audio_file = uploaded or recorded

    with meta_col:
        patient_ref = st.text_input(
            "Patient reference (optional)",
            help="e.g. initials + date, or a chart number. No PII needed.",
        )
        context = st.text_input(
            "Known context (optional)",
            help="e.g. '54F, hypertensive, on losartan'. Used only if consistent with the transcript.",
        )
        if not settings.asr_available:
            st.info("Set `HF_TOKEN` in the app secrets to enable transcription.")
        do_transcribe = st.button(
            "Transcribe", type="primary",
            disabled=audio_file is None or not settings.asr_available,
            use_container_width=True,
        )

if do_transcribe and audio_file is not None:
    try:
        from stt.asr import transcribe

        data, mime, name = read_upload(audio_file)
        with st.spinner("Transcribing…"):
            result = transcribe(data, mime, duration_s=duration_seconds(data, name))
        work.update(
            transcript=result.text,
            audio_filename=name,
            duration_s=result.duration_s,
            warnings=result.quality_warnings(),
            soap=SoapNote().as_sections(), extract={}, review={}, saved_id=None,
        )
        st.session_state.pop("transcript_box", None)
    except Exception as e:  # noqa: BLE001
        st.error(f"Transcription failed: {e}")

for w in work["warnings"]:
    st.warning(w, icon=":material/warning:")


# ----------------------------------------------------------- 2. transcript ---
with panel("transcript"):
    st.subheader("2 · Transcript")
    st.caption("Edit freely before generating the note — the SOAP step reads this text.")
    transcript = st.text_area(
        "Transcript (edit freely before generating the note)",
        value=work["transcript"], key="transcript_box", height=200,
        label_visibility="collapsed",
    )
    work["transcript"] = transcript


# ------------------------------------------------------------- 3. SOAP note ---
llm_ok = settings.llm_available

# The panel is laid out up front; the handlers below render back into these
# containers, so the click logic stays at module level instead of nesting.
with panel("soap"):
    st.subheader("3 · SOAP note")
    st.caption("Draft the note, pull structured facts, then check it against the transcript.")
    c_gen, c_extract, c_review = st.columns(3)
    soap_status = st.container()
    soap_box = st.container()
    soap_detail = st.container()

if c_gen.button("Generate SOAP", type="primary", use_container_width=True,
                disabled=not (llm_ok and transcript.strip())):
    from stt.soap import generate_soap_note

    with llm_guard("SOAP generation"):
        with st.spinner("Generating SOAP note…"):
            note = generate_soap_note(transcript, context=context or None)
        work["soap"] = note.as_sections()
        work["review"] = {}
        for section in SECTIONS:
            st.session_state.pop(f"soap_{section}", None)

if c_extract.button("Extract structured data", use_container_width=True,
                    disabled=not (llm_ok and transcript.strip())):
    from stt.extract import extract_clinical_facts

    with llm_guard("Extraction"):
        with st.spinner("Extracting…"):
            work["extract"] = extract_clinical_facts(transcript).model_dump()

soap_has_content = any(v.strip() for v in work["soap"].values())
if c_review.button("Run grounding review", use_container_width=True,
                   disabled=not (llm_ok and soap_has_content)):
    from stt.review import review_soap_note

    with llm_guard("Review"):
        with st.spinner("Reviewing note against transcript…"):
            work["review"] = review_soap_note(
                transcript, SoapNote.from_sections(work["soap"])
            ).model_dump()

if not llm_ok:
    soap_status.info(
        "Set `GEMINI_API_KEY` in the app secrets to enable SOAP generation, extraction, and review."
    )

with soap_box:
    work["soap"] = editable_soap(work["soap"], key_prefix="soap")

with soap_detail:
    if work["extract"]:
        with st.expander("Structured clinical data", expanded=True):
            render_extract(work["extract"])
    if work["review"]:
        with st.expander("Grounding review", expanded=True):
            render_review(work["review"])


# ---------------------------------------------------------------- 4. save ----
with panel("save"):
    st.subheader("4 · Save")
    st.caption("Stored locally in the notes database — review it later under Past Notes.")
    t_col, tag_col = st.columns(2)
    title = t_col.text_input(
        "Note title", value=work.get("title", "") or (patient_ref or "Untitled consult")
    )
    tags = tag_col.text_input("Tags (comma-separated, optional)")
    save_col, status_col = st.columns([1, 3])

if save_col.button("Save to database", type="primary", use_container_width=True,
                   disabled=not transcript.strip()):
    fields = dict(
        title=title, patient_ref=patient_ref, context=context,
        audio_filename=work["audio_filename"], duration_s=work["duration_s"],
        transcript=transcript, soap=work["soap"], extract=work["extract"],
        review=work["review"], whisper_model=settings.whisper_model_id,
        soap_model=settings.soap_model_id, tags=tags,
    )
    if work["saved_id"]:
        db.update_note(work["saved_id"], **fields)
        status_col.success(f"Updated note #{work['saved_id']}.")
    else:
        work["saved_id"] = db.create_note(**fields)
        status_col.success(f"Saved as note #{work['saved_id']}. See the Past Notes page.")

if work["saved_id"]:
    status_col.caption(f"Editing saved note #{work['saved_id']} — further saves update it.")


render_floating_assistant()
