"""
Consultation Transcript — Bisaya/Cebuano speech → SOAP note.

Record or upload a consult, transcribe it (fine-tuned Whisper via the HF
Inference API), draft an English SOAP note via Gemini, optionally extract
structured clinical data and run a grounding review, then save to the notes
database. Every field is editable before saving.

Layout follows the workflow: a narrow, centred recording card is the focal
point; once a transcript exists it collapses to a one-line summary and the
transcript + SOAP workspaces take over at a wider reading width.
"""

from __future__ import annotations

from assistant.bootstrap import load_secrets

load_secrets()

import streamlit as st  # noqa: E402

from assistant.widget import preload_assistant, render_floating_assistant  # noqa: E402
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
# Claim the floating assistant's stylesheet now, at the top of the run. Otherwise
# a later st.spinner pauses the script before render_floating_assistant() (at the
# bottom of the page) is reached, Streamlit drops the not-yet-re-rendered <style>,
# and the stale FAB collapses to an unstyled rectangle in the page flow.
preload_assistant()

if "work" not in st.session_state:
    st.session_state.work = {
        "transcript": "", "soap": SoapNote().as_sections(), "extract": {}, "review": {},
        "audio_filename": "", "duration_s": None, "saved_id": None, "warnings": [],
    }
work = st.session_state.work

has_transcript = bool(work["transcript"].strip())
has_soap = any(v.strip() for v in work["soap"].values())
step = 3 if has_soap else (2 if has_transcript else 1)


def _fmt_dur(seconds: float | None) -> str:
    if not seconds:
        return "—"
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}:{s:02d}"


def _stepper(current: int) -> str:
    names = ["Record", "Transcribe", "Document"]
    out = ['<div class="sd-steps">']
    for i, name in enumerate(names, start=1):
        cls = "done" if i < current else ("cur" if i == current else "")
        mark = "&#10003;" if i < current else str(i)
        out.append(f'<div class="step {cls}"><span class="dot">{mark}</span>{name}</div>')
        if i < len(names):
            out.append('<span class="sep"></span>')
    out.append("</div>")
    return "".join(out)


# ---- pagehead: title + workflow stepper (matches the dashboard's .pagehead) ---
head_l, head_r = st.columns([3, 2], vertical_alignment="center")
with head_l:
    st.title("🎙️ Consultation Transcript")
with head_r:
    st.markdown(_stepper(step), unsafe_allow_html=True)


# =========================================================== STAGE 1 · record ==
if not has_transcript:
    st.caption("Record the consultation in Bisaya/Cebuano — SugboDoc transcribes "
               "it and drafts an English SOAP note. Everything stays editable.")

    transcribe_err = st.session_state.pop("cx_transcribe_error", None)
    audio_nonce = st.session_state.get("cx_audio_nonce", 0)

    _, mid, _ = st.columns([1, 2.4, 1])
    with mid:
        with panel("record"):
            st.markdown('<p class="sd-rec-title">Record the consultation</p>',
                        unsafe_allow_html=True)
            st.markdown('<p class="sd-rec-sub">Tap the microphone and speak normally '
                        'in Bisaya or Cebuano.</p>', unsafe_allow_html=True)

            # Wrap the mic + the discard control so CSS can pin the "✕" onto the
            # audio-input's own play/re-record row (a mic recording has no
            # built-in clear); bumping the widget key drops the take so the user
            # can re-record or switch to uploading a file.
            with st.container(key="sdrec_wrap"):
                recorded = st.audio_input("Record the consultation",
                                          label_visibility="collapsed",
                                          key=f"cx_audio_{audio_nonce}")
                if recorded is not None:
                    reset_box = st.container(key="sdrec_reset")
                    if reset_box.button("✕", key="cx_reset_rec",
                                        help="Discard this recording"):
                        st.session_state.pop(f"cx_audio_{audio_nonce}", None)
                        st.session_state.cx_audio_nonce = audio_nonce + 1
                        st.rerun()

            uploaded = st.file_uploader(
                "or upload a recording", type=["wav", "mp3", "m4a", "flac", "ogg"],
                label_visibility="collapsed",
            )
            audio_file = recorded or uploaded

            st.divider()
            m_l, m_r = st.columns(2)
            patient_ref = m_l.text_input(
                "Patient reference (optional)", key="cx_patient_ref",
                help="e.g. initials + date, or a chart number. No PII needed.",
            )
            context = m_r.text_input(
                "Known context (optional)", key="cx_context",
                help="e.g. '54F, hypertensive, on losartan'. Used only if "
                     "consistent with the transcript.",
            )

            if not settings.asr_available:
                st.info("Set `HF_TOKEN` in the app secrets to enable transcription.")

            # A placeholder so the click can swap the button for its busy state
            # in place — same run, no rerun — which keeps the rest of the card
            # fresh underneath (a rerun-first approach leaves the previous run's
            # card on screen as a stale duplicate during the ASR wait).
            btn_slot = st.empty()
            clicked = btn_slot.container(key="sdbtn_transcribe").button(
                "Transcribe", type="primary", use_container_width=True,
                disabled=audio_file is None or not settings.asr_available,
                key="cx_transcribe",
            )
            if transcribe_err:
                st.error(transcribe_err)

    render_floating_assistant()

    if clicked and audio_file is not None:
        btn_slot.container(key="sdbtn_busy_transcribe").button(
            "Transcribing…", type="primary", use_container_width=True,
            disabled=True, key="cx_transcribe_busy",
        )
        try:
            from stt.asr import transcribe

            data, mime, name = read_upload(audio_file)
            result = transcribe(data, mime,
                                duration_s=duration_seconds(data, name))
            work.update(
                transcript=result.text, audio_filename=name,
                duration_s=result.duration_s, warnings=result.quality_warnings(),
                soap=SoapNote().as_sections(), extract={}, review={}, saved_id=None,
            )
            st.session_state.pop("transcript_box", None)
        except Exception as e:  # noqa: BLE001
            st.session_state["cx_transcribe_error"] = f"Transcription failed: {e}"
        st.rerun()

    st.stop()


# =============================================== STAGE 2+ · transcript & SOAP ==
patient_ref = st.session_state.get("cx_patient_ref", "")
context = st.session_state.get("cx_context", "")
audio_file = None

# ---- recorded summary strip -------------------------------------------------
with panel("recorded"):
    strip_l, strip_r = st.columns([4, 1], vertical_alignment="center")
    fname = work["audio_filename"] or "Recording"
    strip_l.markdown(
        f'<div class="sd-recdone"><span class="ok">&#10003;</span>'
        f'<span>Captured &nbsp;·&nbsp; <b>{fname}</b></span>'
        f'<span class="meta">&nbsp;·&nbsp; {_fmt_dur(work["duration_s"])}</span></div>',
        unsafe_allow_html=True,
    )
    if strip_r.button("New recording", use_container_width=True):
        work.update(transcript="", soap=SoapNote().as_sections(), extract={},
                    review={}, audio_filename="", duration_s=None, saved_id=None,
                    warnings=[])
        for k in list(st.session_state.keys()):
            if k.startswith(("soap_", "transcript_box")):
                st.session_state.pop(k, None)
        st.rerun()

for w in work["warnings"]:
    st.warning(w, icon=":material/warning:")


# ---- transcript document --------------------------------------------------
with panel("transcript"):
    words = len(work["transcript"].split())
    st.markdown(
        f'<div class="sd-doc-head"><h3>Transcript</h3>'
        f'<span class="sd-chip">{words} words</span>'
        f'<span class="sd-chip">{_fmt_dur(work["duration_s"])}</span></div>',
        unsafe_allow_html=True,
    )
    st.caption("Edit freely before generating the note — the SOAP step reads this text.")
    transcript = st.text_area(
        "Transcript", value=work["transcript"], key="transcript_box", height=240,
        label_visibility="collapsed",
    )
    work["transcript"] = transcript


# ---- SOAP workspace -----------------------------------------------------------
llm_ok = settings.llm_available

with panel("soap"):
    st.markdown('<div class="sd-doc-head"><h3>Generated SOAP note</h3></div>',
                unsafe_allow_html=True)
    st.markdown('<p class="sd-soap-toolbar">Draft the note from the transcript, '
                'pull structured facts, then check it against the source.</p>',
                unsafe_allow_html=True)
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
        "Set `GEMINI_API_KEY` in the app secrets to enable SOAP generation, "
        "extraction, and review."
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


# ---- save (quiet footer) ----------------------------------------------------
with panel("save"):
    s_title, s_tags, s_btn = st.columns([2, 2, 1], vertical_alignment="bottom")
    title = s_title.text_input(
        "Note title",
        value=work.get("title", "") or (patient_ref or "Untitled consult"),
    )
    tags = s_tags.text_input("Tags (comma-separated, optional)")
    save_clicked = s_btn.button(
        "Save to database", type="primary", use_container_width=True,
        disabled=not transcript.strip(),
    )
    status_col = st.container()

if save_clicked:
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
