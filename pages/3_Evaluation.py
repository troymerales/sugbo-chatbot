"""
Evaluation — offline accuracy on the synthetic ``trial/`` set: ASR word error
rate against the known source text, and optional SOAP grounding / completeness
scores.
"""

from __future__ import annotations

from assistant.bootstrap import load_secrets

load_secrets()

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from assistant.widget import render_floating_assistant  # noqa: E402
from stt import evaluation  # noqa: E402
from stt.config import get_settings  # noqa: E402
from shell import render_shell  # noqa: E402
from stt.gemini import LLM_EXHAUSTED_MESSAGE  # noqa: E402

st.set_page_config(page_title="Evaluation", page_icon="📊", layout="wide",
                   initial_sidebar_state="expanded")
settings = get_settings()
render_shell("evaluation")

st.title("📊 Evaluation")
st.caption(
    "Each clip in `trial/audio_output/` was synthesized from a known line in "
    "`trial/script.txt`, so ASR output can be scored directly."
)

setup = st.container(key="sdpanel_setup")

clips = evaluation.load_reference_clips()
if not clips:
    setup.error(f"No reference clips found under `{settings.trial_dir}`.")
    render_floating_assistant()
    st.stop()

setup.write(f"**{len(clips)}** reference clips "
            f"({sum(c.kind == 'dialogue' for c in clips)} dialogue, "
            f"{sum(c.kind == 'narration' for c in clips)} narration).")

with setup:
    col1, col2, col3 = st.columns(3)
kinds = col1.multiselect("Clip types", ["dialogue", "narration"], default=["dialogue", "narration"])
run_soap = col2.checkbox("Also generate SOAP notes", value=False,
                         disabled=not settings.llm_available)
run_review = col3.checkbox("Also score grounding/completeness", value=False,
                           disabled=not (settings.llm_available and run_soap))

selected = [c for c in clips if c.kind in kinds]
setup.caption(f"{len(selected)} clips selected. "
              + ("Each clip is a hosted ASR call — a few seconds each." if selected else ""))

if setup.button("Run evaluation", type="primary", disabled=not selected):
    results = []
    progress = setup.progress(0.0, text="Starting…")
    for i, clip in enumerate(selected, start=1):
        progress.progress(i / len(selected), text=f"{clip.clip_id} ({i}/{len(selected)})")
        results.append(evaluation.evaluate_clip(clip, run_soap=run_soap, run_review=run_review))
    progress.empty()
    st.session_state.eval_results = results

results = st.session_state.get("eval_results")
if not results:
    render_floating_assistant()
    st.stop()

if any(r.error == LLM_EXHAUSTED_MESSAGE for r in results):
    st.error(LLM_EXHAUSTED_MESSAGE, icon=":material/hourglass_empty:")
    st.caption("ASR scores below are unaffected; the SOAP columns are blank.")

agg = evaluation.aggregate(results)
m = st.columns(4)  # metric row sits on the page background, like the dashboard
m[0].metric("Mean WER", f"{agg['mean_wer']:.1%}" if agg["mean_wer"] is not None else "—")
m[1].metric("Mean CER", f"{agg['mean_cer']:.1%}" if agg["mean_cer"] is not None else "—")
m[2].metric("Mean grounding", f"{agg['mean_grounding']:.1f}/5" if "mean_grounding" in agg else "—")
m[3].metric("Errors", agg["errors"])

table = st.container(key="sdpanel_results")
df = pd.DataFrame(
    [
        {
            "clip": r.clip.clip_id,
            "kind": r.clip.kind,
            "WER": None if r.wer is None else round(r.wer, 3),
            "CER": None if r.cer is None else round(r.cer, 3),
            "grounding": r.grounding_score,
            "completeness": r.completeness_score,
            "error": r.error or "",
        }
        for r in results
    ]
)
table.dataframe(df, use_container_width=True, hide_index=True)
table.download_button("Download results CSV", df.to_csv(index=False),
                      file_name="evaluation.csv")

detail = st.container(key="sdpanel_detail")
with detail:
    st.subheader("Per-clip detail")
    for r in results:
        label = (f"{r.clip.clip_id} · WER {r.wer:.1%}" if r.wer is not None
                 else f"{r.clip.clip_id} · error")
        with st.expander(label):
            if r.error:
                st.error(r.error)
            st.markdown("**Reference**")
            st.write(r.clip.reference_text)
            st.markdown("**Hypothesis (ASR)**")
            st.write(r.hypothesis or "_(none)_")
            if r.soap:
                st.markdown("**SOAP**")
                for k, v in r.soap.items():
                    st.markdown(f"*{k}:* {v}")
            if r.extras.get("review_summary"):
                st.info(r.extras["review_summary"])


render_floating_assistant()
