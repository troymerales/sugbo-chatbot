"""
Jira Chatbot Evaluation — results dashboard (public demo build).

Self-contained: renders every section over the **simulated** results in
``evaluation/mock_results/`` and shows a disclosure in the hero. Makes no LLM
calls and never writes to any results file. Reuses the pure helpers in
``evaluation/backtest.py`` (loading / scoring / agreement) — no eval logic is
duplicated.

    streamlit run evaluation/dashboard_mock.py

To point the same dashboard at a private ``evaluation/results/`` locally, use
``evaluation/dashboard_real.py`` (git-ignored).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# --- make the project importable when Streamlit's CWD is the repo root ------- #
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from evaluation import backtest as bt  # noqa: E402  (helpers only — no LLM)

RESULTS_DIR = Path(__file__).resolve().parent / "mock_results"
CLASSES = list(bt.CLASSIFICATIONS)                      # FULL, PARTIAL, HUMAN
CLASS_COLOR = {"FULL": "#12805c", "PARTIAL": "#a15c00", "HUMAN": "#b4232f"}
CLASS_RANGE = [CLASS_COLOR[c] for c in CLASSES]   # column-order palette for wide charts
ACCENT = "#3b41d6"                                # single-series bar colour (app indigo)
CLASS_HELP = {
    "FULL": "Reply is correct, specific and self-sufficient — a workflow could end here.",
    "PARTIAL": "Real on-topic help, but a human would still very likely need to step in.",
    "HUMAN": "Needs access / a manual change / a decision / investigation, or the reply "
             "is a refusal, vague, wrong or hallucinated.",
}

def _configure_page() -> None:
    """Page config + a width cap. Called first thing in main() (not at import
    time) so it also takes effect when dashboard_real.py imports this module."""
    st.set_page_config(page_title="Jira Chatbot Evaluation", page_icon="📊",
                       layout="wide", initial_sidebar_state="collapsed")
    # `layout="wide"` gives charts/tables room, but on a large monitor Streamlit
    # otherwise stretches the content edge to edge — cap it at a readable width.
    st.markdown(
        "<style>[data-testid='stMainBlockContainer']{max-width:1240px;margin-inline:auto;}"
        "</style>",
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Loading (cached — parsed once per file version)
# --------------------------------------------------------------------------- #

def _to_bool(v):
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in {"true", "1", "yes"}:
        return True
    if s in {"false", "0", "no"}:
        return False
    return None


@st.cache_data(show_spinner=False)
def load_results(mtime: float | None) -> pd.DataFrame:
    p = RESULTS_DIR / "backtest_results.csv"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p)
    for c in ("historical_resolved", "chatbot_refused", "grounding_supported",
              "grounding_checked", "evaluator_fallback"):
        if c in df.columns:
            df[c] = df[c].map(_to_bool)
    if "summary" in df.columns:
        df["summary"] = df["summary"].fillna("").astype(str)
        if "summary_length" not in df.columns:
            df["summary_length"] = df["summary"].str.len()
    if "classification" in df.columns:
        df["classification"] = df["classification"].astype(str).str.upper().str.strip()
    for c in ("chatbot_error", "grounding_reason", "evaluation_reason", "chatbot_response",
              "nearest_doc_sections", "evaluator_model"):
        if c in df.columns:
            df[c] = df[c].fillna("").astype(str).replace({"nan": "", "None": ""})
    return df


@st.cache_data(show_spinner=False)
def load_metrics(mtime: float | None) -> dict:
    p = RESULTS_DIR / "summary_metrics.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"_malformed": True}


@st.cache_data(show_spinner=False)
def load_manual(mtime: float | None) -> pd.DataFrame:
    p = RESULTS_DIR / "manual_review_sample.csv"
    if not p.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(p).fillna("")
    except (pd.errors.EmptyDataError, OSError):
        return pd.DataFrame()


def _mtime(name: str) -> float | None:
    p = RESULTS_DIR / name
    return p.stat().st_mtime if p.exists() else None


@st.cache_data(show_spinner="Scoring lexical documentation overlap…")
def doc_overlap(ticket_ids: tuple, texts: tuple) -> pd.DataFrame:
    """Cached wrapper around `backtest.doc_overlap_frame` — one source of truth for
    the rule-based, no-LLM 'how close is this ticket to anything documented' signal.
    Used only when `backtest_results.csv` predates the baked-in `doc_overlap` column.
    """
    try:
        frame = pd.DataFrame({"ticket_id": list(ticket_ids), "summary": list(texts)})
        return bt.doc_overlap_frame(frame)
    except Exception as exc:  # noqa: BLE001 — enrichment is best-effort
        return pd.DataFrame({"_error": [str(exc)]})


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def kpis(df: pd.DataFrame, metrics: dict) -> dict:
    """Derived from the results frame; falls back to summary_metrics.json."""
    if not df.empty and "classification" in df.columns:
        total = len(df)
        counts = df["classification"].value_counts()
        full = int(counts.get("FULL", 0))
        partial = int(counts.get("PARTIAL", 0))
        human = int(counts.get("HUMAN", 0))
    else:
        total = int(metrics.get("total_tickets", 0))
        full = int(metrics.get("full", 0))
        partial = int(metrics.get("partial", 0))
        human = int(metrics.get("human", 0))
    return {
        "total": total, "full": full, "partial": partial, "human": human,
        "deflection": (full / total) if total else 0.0,
        "partial_rate": (partial / total) if total else 0.0,
        "human_rate": (human / total) if total else 0.0,
    }


def classification_series(df: pd.DataFrame) -> pd.Series:
    return (df["classification"].value_counts()
            .reindex(CLASSES).fillna(0).astype(int))


def fallback_state(df: pd.DataFrame) -> str:
    if "evaluator_fallback" not in df.columns or df.empty:
        return "none"
    fb = df["evaluator_fallback"].fillna(False).astype(bool)
    if fb.all():
        return "all"
    if fb.any():
        return "some"
    return "none"


def tag_reason(row: pd.Series) -> list[str]:
    """Per-ticket failure tags, reusing evaluation/backtest.py's category keywords."""
    text = f"{row.get('evaluation_reason', '')} {row.get('chatbot_response', '')}".lower()
    tags = [name for name, kws in bt.FAILURE_PATTERNS.items() if any(k in text for k in kws)]
    return tags or ["other"]


def filtered(df, classes, id_query, text_query, section_query) -> pd.DataFrame:
    out = df
    if classes:
        out = out[out["classification"].isin(classes)]
    if id_query:
        out = out[out["ticket_id"].astype(str).str.contains(id_query.strip(), case=False)]
    if text_query:
        out = out[out["summary"].str.contains(text_query.strip(), case=False, na=False)]
    if section_query and "nearest_doc_sections" in out.columns:
        out = out[out["nearest_doc_sections"].str.contains(
            section_query.strip(), case=False, na=False)]
    return out


def bucket(series: pd.Series, edges: list[float], labels: list[str]) -> pd.Series:
    return pd.cut(series, bins=edges, labels=labels, include_lowest=True)


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #

#: When True, the Manual Validation section becomes an inline editor that writes
#: human_evaluation / human_reason back to manual_review_sample.csv. OFF for the
#: public demo (ephemeral filesystem, and the demo labels are fixed);
#: dashboard_real.py sets it True for the private local view.
ALLOW_MANUAL_EDIT: bool = False

#: Disclosure captions shown at the top of the hero. This is the PUBLIC demo
#: build, so it is populated; dashboard_real.py (git-ignored) clears it.
DEMO_NOTICE: list[str] = [
    "**Demo dashboard.** The ticket data below is **simulated** to protect confidential "
    "information — it demonstrates the evaluation system, not real tickets.",
    "**Real historical result:** replaying 33 real historical Jira tickets gave **6.1% "
    "potential ticket deflection** — a historical estimate, not observed production automation.",
]


def section_header(metrics: dict) -> None:
    st.title("Jira Chatbot Evaluation")
    st.caption("Historical backtest of potential AI ticket deflection")
    # Disclosure text for the public demo — rendered as plain captions so the
    # layout is identical to the real dashboard (which sets DEMO_NOTICE = []).
    for _note in DEMO_NOTICE:
        st.caption(_note)
    st.markdown(
        "> Historical Jira tickets were replayed through the chatbot and independently "
        "evaluated for whether the chatbot could reasonably have handled the request "
        "**without human intervention**. This is a **counterfactual estimate**, not a "
        "record of automation that happened."
    )
    run = metrics.get("run", {})
    if run:
        bits = [
            f"run `{run.get('run_id', '?')}`",
            f"chatbot **{run.get('chatbot_model', '?')}**",
            f"evaluator **{run.get('evaluator_model', '?')}**",
            f"retrieval {'RAG' if run.get('prod_use_rag') else 'full-context'}",
            f"verification {'on' if run.get('prod_verify_answers') else 'off'}",
        ]
        gen = metrics.get("generated_at", "")
        st.caption(" · ".join(bits) + (f" · generated {gen[:19].replace('T', ' ')} UTC" if gen else ""))


def section_tldr(k: dict, metrics: dict, agreement: dict) -> None:
    """One-screen summary: the number, whether it's validated, what it doesn't prove."""
    with st.container(border=True):
        c1, c2, c3 = st.columns([1.1, 1, 1.3])
        c1.metric(
            "Potential deflection rate", f"{k['deflection']:.1%}",
            help="FULL ÷ tickets evaluated. The 95% CI is binomial **sampling** error only "
                 "— it treats these tickets as a random sample (they are a filtered "
                 "convenience set) and does **not** account for LLM-evaluator error, which "
                 "the manual validation section addresses.",
        )
        lo, hi = metrics.get("deflection_ci95_low"), metrics.get("deflection_ci95_high")
        elo, ehi = metrics.get("deflection_ci95_exact_low"), metrics.get("deflection_ci95_exact_high")
        if lo is not None and k["total"]:
            extra = f"; {elo:.1%}–{ehi:.1%} exact" if elo is not None else ""
            c1.caption(f"{k['full']} of {k['total']} · 95% CI {lo:.1%}–{hi:.1%} Wilson{extra}")
        else:
            c1.caption(f"{k['full']} of {k['total']} tickets")

        n = agreement.get("reviewed", 0)
        if n:
            c2.metric("Evaluator ↔ human agreement", f"{agreement.get('agreement_rate', 0):.0%}")
            c2.caption(f"n = {n} · Cohen's κ {agreement.get('cohens_kappa', 0):.2f}")
        else:
            c2.metric("Evaluator ↔ human agreement", "not validated")
            c2.caption("no human labels in the review sample yet")

        miss = int(metrics.get("likely_miss_count", 0))
        c3.metric("Refusals that may be recoverable", miss)
        c3.caption("refused, but the docs appear to cover the topic")

        st.caption(
            "This is a **historical counterfactual estimate** of what the chatbot *could* "
            "have handled unaided — not observed production automation. It depends on an "
            "LLM evaluator (validate it above) and on how the ticket set was filtered."
        )


def section_kpis(k: dict, metrics: dict) -> None:
    cols = st.columns(5)
    cards = [
        ("Tickets evaluated", f"{k['total']:,}", "backtest population"),
        ("FULL", f"{k['full']:,}", f"{k['deflection']:.1%} of total"),
        ("PARTIAL", f"{k['partial']:,}", f"{k['partial_rate']:.1%} of total"),
        ("HUMAN", f"{k['human']:,}", f"{k['human_rate']:.1%} of total"),
        ("Potential deflection rate", f"{k['deflection']:.1%}", "FULL ÷ total"),
    ]
    for col, (label, value, sub) in zip(cols, cards):
        with col:
            with st.container(border=True):
                st.metric(label, value)
                if sub:
                    st.caption(sub)

    calls = metrics.get("est_chatbot_calls")
    if calls:
        parts = [f"chatbot ≈ **{calls}** model calls", f"evaluator ≈ **{metrics.get('est_evaluator_calls', '?')}** calls"]
        if metrics.get("latency_s_p50") is not None:
            parts.append(f"per-ticket latency: median **{metrics['latency_s_p50']}s**, "
                         f"p95 **{metrics['latency_s_p95']}s**")
        st.caption("Cost & latency —  " + "  ·  ".join(parts))


def _class_bar(counts: pd.Series):
    """Ordered FULL→PARTIAL→HUMAN horizontal bar with the fixed palette."""
    import altair as alt

    data = counts.rename_axis("classification").reset_index(name="tickets")
    return (
        alt.Chart(data)
        .mark_bar()
        .encode(
            y=alt.Y("classification:N", sort=CLASSES, title=None),
            x=alt.X("tickets:Q", title="tickets"),
            color=alt.Color("classification:N", sort=CLASSES,
                            scale=alt.Scale(domain=CLASSES,
                                            range=[CLASS_COLOR[c] for c in CLASSES]),
                            legend=None),
            tooltip=["classification", "tickets"],
        )
        .properties(height=180, width="container")
    )


def section_breakdown(df: pd.DataFrame, fb: str) -> None:
    st.subheader("Classification breakdown")
    if fb == "all":
        st.error(
            "**Every classification in this dataset is an evaluator fallback.** "
            "The FULL / PARTIAL / HUMAN split below is not a valid evaluator result — "
            "treat it as missing data.", icon="🚫",
        )
    counts = classification_series(df)
    left, right = st.columns([2, 1])
    with left:
        st.altair_chart(_class_bar(counts))
    with right:
        tbl = counts.rename_axis("class").reset_index(name="tickets")
        tbl["share"] = (tbl["tickets"] / max(counts.sum(), 1)).map("{:.1%}".format)
        st.dataframe(tbl, hide_index=True, width="stretch")
    # legend below, full width — three wrapped captions in a 1/3 column read cramped
    for c in CLASSES:
        st.caption(f"**{c}** — {CLASS_HELP[c]}")


def section_reasons(df: pd.DataFrame) -> None:
    st.subheader("Why tickets were not fully deflectable")
    st.caption(
        "Rule-based tagging of the evaluator's free-text reason for every PARTIAL / HUMAN "
        "ticket, using the keyword categories defined in `evaluation/backtest.py` "
        "(`FAILURE_PATTERNS`). Transparent, no LLM — a ticket can carry more than one tag."
    )
    non_full = df[df["classification"].isin(["PARTIAL", "HUMAN"])]
    if non_full.empty:
        st.success("No PARTIAL or HUMAN tickets — nothing to explain here.")
        return
    agg = bt.failure_patterns(df)
    if agg.empty:
        st.info("Reason text is not available in these results.")
        return
    agg = agg.rename(columns={"patterns": "reason_category", "count": "tickets"})
    c1, c2 = st.columns([3, 2])
    with c1:
        st.bar_chart(agg, x="reason_category", y="tickets", horizontal=True,
                     color=ACCENT, height=max(150, 48 * len(agg)))
    with c2:
        st.dataframe(agg, hide_index=True, width="stretch")
    st.caption(
        f"{len(non_full)} tickets need a human. Most common driver: "
        f"**{agg.iloc[0]['reason_category']}** ({agg.iloc[0]['tickets']} tickets)."
    )


def section_explorer(df: pd.DataFrame) -> None:
    st.subheader("Ticket explorer")
    f1, f2, f3, f4 = st.columns([1.3, 1, 1.4, 1.4])
    classes = f1.multiselect("Classification", CLASSES, default=CLASSES)
    id_q = f2.text_input("Ticket ID contains", "")
    text_q = f3.text_input("Summary contains", "")
    section_q = (f4.text_input("Doc section contains", "")
                 if "nearest_doc_sections" in df.columns else "")

    view = filtered(df, classes, id_q, text_q, section_q)
    st.caption(f"{len(view)} / {len(df)} tickets match")
    if view.empty:
        st.info("No tickets match these filters.")
        return

    show_cols = [c for c in ("ticket_id", "classification", "chatbot_refused",
                             "doc_overlap", "summary") if c in view.columns]
    st.dataframe(view[show_cols], hide_index=True, width="stretch", height=260)

    labels = {
        f"{r.ticket_id} · {r.classification} · {str(r.summary)[:70]}": r.ticket_id
        for r in view.itertuples()
    }
    pick = st.selectbox("Inspect a ticket", list(labels), index=0)
    row = view[view["ticket_id"] == labels[pick]].iloc[0]
    _render_ticket(row)


def _render_ticket(row: pd.Series) -> None:
    cls = row["classification"]
    color = CLASS_COLOR.get(cls, "#6b7280")
    is_fallback = bool(row.get("evaluator_fallback", False))

    st.markdown(
        f"<div style='border-left:4px solid {color};padding:.2rem .9rem;margin:.4rem 0'>"
        f"<span style='background:{color};color:#fff;padding:1px 9px;border-radius:10px;"
        f"font-size:.8rem;font-weight:600'>{cls}</span>"
        + (" <span style='background:#b4232f;color:#fff;padding:1px 9px;border-radius:10px;"
           "font-size:.8rem;font-weight:600'>EVALUATOR FALLBACK</span>" if is_fallback else "")
        + f"&nbsp;&nbsp;<b>Ticket {row['ticket_id']}</b></div>",
        unsafe_allow_html=True,
    )

    st.markdown("**Original ticket**")
    st.write(row["summary"])
    meta = {c: row[c] for c in ("issue_type", "Type", "Type_norm", "historical_status",
                                "historical_resolved", "summary_length") if c in row.index}
    if meta:
        st.caption(" · ".join(f"{k}: `{v}`" for k, v in meta.items()))

    st.markdown("**Retrieved documentation**")
    if row.get("nearest_doc_sections"):
        st.write(row["nearest_doc_sections"])
        st.caption(
            "Lexical overlap only — production runs full-context (no retrieval step). "
            f"`grounding_reason`: {row.get('grounding_reason', '—')}"
        )
    else:
        st.caption(
            "Production runs full-context (`USE_RAG=off`) — there is no per-ticket "
            f"retrieval record. Grounding-pass note: {row.get('grounding_reason', '—')}"
        )

    st.markdown("**Chatbot response**")
    resp = str(row.get("chatbot_response", "")).strip()
    err = str(row.get("chatbot_error", "")).strip()
    if err:
        st.error(f"Chatbot errored: {err}")
    elif not resp:
        st.info("No response recorded.")
    else:
        (st.warning if bool(row.get("chatbot_refused")) else st.info)(resp)
        if bool(row.get("chatbot_refused")):
            st.caption("This is the fixed refusal reply — the bot found nothing in the docs.")

    st.markdown("**Evaluation**")
    ec1, ec2 = st.columns([1, 3])
    ec1.metric("Classification", cls)
    ec2.write(row.get("evaluation_reason", "—"))
    if is_fallback:
        st.warning(
            "This classification came from the **fallback mechanism** (empty response, or "
            "the evaluator returned invalid output twice → defaulted to HUMAN). "
            "It is not a genuine evaluator judgement.", icon="⚠️",
        )
    ev_model = row.get("evaluator_model")
    if ev_model:
        st.caption(f"evaluator model: `{ev_model}`")


def section_failure_analysis(df: pd.DataFrame) -> None:
    st.subheader("Failure analysis")
    st.caption("Slices of the classification against other variables. None of these is a "
               "ground-truth label — they are exploratory.")

    tabs = st.tabs(["Likely misses", "By summary length", "By doc overlap",
                    "By historical outcome", "Common reasons", "No-overlap tickets",
                    "Evaluator fallback"])

    with tabs[0]:
        lm = bt.likely_misses(df)
        st.metric("Refusals that may be recoverable", len(lm),
                  help="Refused, but the ticket summary has ≥25% lexical overlap with a "
                       "documentation section — the docs may well cover it.")
        st.caption(
            "The most **actionable** slice: these are tickets the chatbot declined even "
            "though the documentation appears to address the topic. Candidates for a "
            "retrieval or prompt fix, not appropriate declines. (Lexical heuristic — an "
            "upper bound, review individually.)"
        )
        if len(lm):
            st.dataframe(lm, hide_index=True, width="stretch", height=280)
        elif "doc_overlap" not in df.columns:
            st.info("Documentation-overlap enrichment is disabled or failed.")
        else:
            st.success("No refusals with high documentation overlap.")

    tabs = tabs[1:]

    with tabs[0]:
        if "summary_length" in df.columns and df["summary_length"].notna().any():
            edges = [0, 80, 140, 200, 280, max(281, df["summary_length"].max() + 1)]
            b = bucket(df["summary_length"], edges,
                       ["≤80", "81–140", "141–200", "201–280", "280+"])
            ct = pd.crosstab(b, df["classification"]).reindex(columns=CLASSES).fillna(0).astype(int)
            st.bar_chart(ct, color=CLASS_RANGE, height=300)
            st.caption("Ticket summary length (characters) vs classification.")
        else:
            st.info("`summary_length` not available.")

    with tabs[1]:
        if "doc_overlap" in df.columns:
            b = bucket(df["doc_overlap"].fillna(0), [0, 0.05, 0.15, 0.25, 0.4, 1.0],
                       ["0–5%", "5–15%", "15–25%", "25–40%", "40%+"])
            ct = pd.crosstab(b, df["classification"]).reindex(columns=CLASSES).fillna(0).astype(int)
            st.bar_chart(ct, color=CLASS_RANGE, height=300)
            st.caption("Best lexical overlap with any doc section (rule-based) vs classification.")
        else:
            st.info("Documentation-overlap enrichment is disabled or failed.")

    with tabs[2]:
        if "historical_resolved" in df.columns and df["historical_resolved"].notna().any():
            hr = df["historical_resolved"].map({True: "resolved", False: "unresolved"})
            ct = pd.crosstab(df["classification"], hr).reindex(index=CLASSES).fillna(0).astype(int)
            st.dataframe(ct, width="stretch")
            if hr.nunique(dropna=True) < 2:
                st.info(f"Every ticket here has historical_resolved = "
                        f"**{df['historical_resolved'].dropna().iloc[0]}** — this cut is "
                        "uninformative for this dataset.")
            st.caption("`historical_resolved` is a separate historical outcome — **not** the "
                       "correct label for FULL/PARTIAL/HUMAN.")
        else:
            st.info("`historical_resolved` not available.")

    with tabs[3]:
        agg = bt.failure_patterns(df)
        if agg.empty:
            st.info("No PARTIAL/HUMAN reason text.")
        else:
            agg = agg.rename(columns={"patterns": "reason", "count": "tickets"})
            st.bar_chart(agg, x="reason", y="tickets", horizontal=True,
                         color=ACCENT, height=max(150, 48 * len(agg)))

    with tabs[4]:
        if "doc_overlap" in df.columns:
            no_doc = df[df["doc_overlap"].fillna(0) < 0.05]
            st.metric("Tickets with ~no documentation overlap (<5%)", len(no_doc))
            if len(no_doc):
                st.dataframe(
                    no_doc[[c for c in ("ticket_id", "classification", "doc_overlap", "summary")
                            if c in no_doc.columns]],
                    hide_index=True, width="stretch", height=240)
        else:
            st.info("Documentation-overlap enrichment is disabled or failed.")

    with tabs[5]:
        if "evaluator_fallback" in df.columns:
            fb = df[df["evaluator_fallback"].fillna(False).astype(bool)]
            st.metric("Evaluator-fallback classifications", len(fb))
            if len(fb):
                st.dataframe(
                    fb[[c for c in ("ticket_id", "classification", "chatbot_error",
                                    "evaluation_reason", "summary") if c in fb.columns]],
                    hide_index=True, width="stretch", height=240)
            else:
                st.success("No fallback rows — every classification is a real evaluator result.")
        else:
            st.info("`evaluator_fallback` column not present.")


def section_trace(df: pd.DataFrame) -> None:
    st.subheader("Example trace — one ticket, end to end")
    st.caption("Exactly what each model received and produced. Nothing hidden: the chatbot "
               "is the production pipeline, the evaluator is a separate model that never "
               "sees the historical outcome.")

    ids = df["ticket_id"].astype(str).tolist()
    default_ix = 0
    answered = df[df["chatbot_refused"].map(_to_bool) == False]  # noqa: E712
    if not answered.empty:
        default_ix = ids.index(str(answered.iloc[0]["ticket_id"]))
    pick = st.selectbox("Ticket", ids, index=default_ix, key="trace_pick")
    row = df[df["ticket_id"].astype(str) == pick].iloc[0]
    refused = bool(_to_bool(row.get("chatbot_refused")))

    st.markdown("**1 · Ticket summary** — the only input the chatbot receives")
    st.code(str(row["summary"]), language="text", wrap_lines=True)

    try:
        from core import knowledge
        sys_len = len(knowledge.system_prompt())
        persona = knowledge.PERSONA.strip()
    except Exception:  # noqa: BLE001
        sys_len, persona = 0, "You are the SugboDoc support assistant. Answer only from the docs."
    with st.expander("2 · Prompt sent to the chatbot"):
        st.code(
            f"SYSTEM:\n{persona}\n\n"
            f"===== SUGBODOC DOCUMENTATION =====\n"
            f"[the full product documentation — {sys_len:,} characters — is inlined here; "
            f"production runs full-context, no retrieval step]\n"
            f"===== END DOCUMENTATION =====\n\n"
            f"USER:\n{row['summary']}",
            language="text", wrap_lines=True,
        )

    st.markdown("**3 · Chatbot response** — rendered as the user would see it")
    with st.container(border=True):
        st.markdown(str(row.get("chatbot_response", "")) or "_(no response)_")
    st.caption(f"refused: `{refused}`  ·  grounding pass: {row.get('grounding_reason', '—')}")

    with st.expander("4 · Prompt sent to the evaluator (separate model)"):
        ev_user = bt._EVAL_USER_TEMPLATE.format(
            summary=row["summary"], response=row.get("chatbot_response", ""))
        st.code(f"SYSTEM:\n{bt.EVALUATOR_SYSTEM.strip()}\n\nUSER:\n{ev_user}",
                language="text", wrap_lines=True)

    st.markdown("**5 · Evaluator verdict**")
    st.code(
        json.dumps({"classification": row["classification"],
                    "reason": str(row.get("evaluation_reason", ""))}, indent=2),
        language="json",
    )
    if bool(_to_bool(row.get("evaluator_fallback"))):
        st.warning("This verdict is an **evaluator fallback**, not a real judgement.", icon="⚠️")


def _manual_editor(manual: pd.DataFrame) -> None:
    """Inline editor for human_evaluation / human_reason. Persists to
    manual_review_sample.csv only when the Save button is pressed."""
    st.markdown("**Label the sample**")
    st.caption(
        "Pick a ticket in *Example trace* above to read the full chatbot reply, then set "
        "**Your label** for it here (the LLM's label + reason are shown for reference). "
        "Optionally note why, then **Save** — it writes to `manual_review_sample.csv` and "
        "the stats below recompute."
    )

    view = manual.copy()
    he = view.get("human_evaluation", pd.Series("", index=view.index)).astype(str).str.strip().str.upper()
    view["human_evaluation"] = he.where(he.isin(CLASSES), None)
    view["human_reason"] = view.get("human_reason", "").astype(str).replace({"nan": ""})

    # editable columns first so "Your label" is always the leftmost visible one
    show = [c for c in ("human_evaluation", "human_reason", "ticket_id", "summary",
                        "llm_evaluation", "llm_reason")
            if c in view.columns]
    edited = st.data_editor(
        view[show], key="manual_edit", hide_index=True, width="stretch",
        num_rows="fixed", height=460,
        column_config={
            "human_evaluation": st.column_config.SelectboxColumn(
                "Your label", options=CLASSES, required=False, width="small"),
            "human_reason": st.column_config.TextColumn("Your reason", width="medium"),
            "ticket_id": st.column_config.TextColumn("Ticket", disabled=True, width="small"),
            "summary": st.column_config.TextColumn("Summary", disabled=True, width="medium"),
            "llm_evaluation": st.column_config.TextColumn("LLM", disabled=True, width="small"),
            "llm_reason": st.column_config.TextColumn("LLM reason", disabled=True, width="medium"),
        },
    )

    n_set = int(edited["human_evaluation"].notna().sum())
    b, note = st.columns([1, 3])
    if b.button(f"💾 Save {n_set} label{'' if n_set == 1 else 's'}", type="primary",
                key="manual_save"):
        out = manual.copy()
        out["human_evaluation"] = edited["human_evaluation"].fillna("").values
        out["human_reason"] = edited["human_reason"].fillna("").values
        if "judge_correct" in out.columns:
            out["judge_correct"] = ""            # recomputed by score_manual_review()
        path = RESULTS_DIR / "manual_review_sample.csv"
        out.to_csv(path, index=False)
        st.cache_data.clear()
        st.toast(f"Saved {n_set} labels → {path.name}", icon="✅")
        st.rerun()
    note.caption("Edits persist in the page until you Save; Save writes them to disk.")
    st.divider()


def section_manual(manual: pd.DataFrame) -> None:
    st.subheader("Manual validation")
    if manual.empty:
        st.info("`manual_review_sample.csv` not found — skipping human-vs-LLM validation.")
        return

    if ALLOW_MANUAL_EDIT:
        _manual_editor(manual)

    n_total = len(manual)
    labelled = manual[manual["human_evaluation"].astype(str).str.strip().str.upper().isin(CLASSES)] \
        if "human_evaluation" in manual.columns else manual.iloc[0:0]

    c1, c2, c3 = st.columns(3)
    c1.metric("In review sample", n_total)
    c2.metric("Human-labelled so far", len(labelled))

    if labelled.empty:
        c3.metric("Agreement", "—")
        if ALLOW_MANUAL_EDIT:
            st.info("No labels saved yet — use the editor above, then Save.")
        else:
            st.warning(
                "No human labels in `manual_review_sample.csv` yet. Fill the "
                "`human_evaluation` column (FULL / PARTIAL / HUMAN) and re-open this page.",
                icon="✍️",
            )
            st.dataframe(
                manual[[c for c in ("ticket_id", "llm_evaluation", "human_evaluation", "llm_reason")
                        if c in manual.columns]].head(50),
                hide_index=True, width="stretch",
            )
        return

    try:
        agr = bt.evaluator_agreement(manual)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not compute agreement: {exc}")
        return

    c3.metric("Agreement rate", f"{agr.get('agreement_rate', 0):.1%}")
    m1, m2, m3 = st.columns(3)
    m1.metric("LLM judge correct", agr.get("judge_correct", "—"))
    m2.metric("LLM judge wrong", agr.get("judge_incorrect", "—"))
    m3.metric("Cohen's κ", f"{agr.get('cohens_kappa', 0):.3f}")

    cm = agr.get("confusion_matrix")
    if isinstance(cm, pd.DataFrame):
        st.markdown("**Confusion matrix** — rows = human, columns = LLM evaluator")
        st.dataframe(cm, width="stretch")

    scored = bt.score_manual_review(manual)
    disagree = scored[scored["judge_correct"] == "no"]
    st.markdown(f"**Disagreements ({len(disagree)})**")
    if disagree.empty:
        st.success("Human and LLM agree on every labelled ticket.")
    else:
        st.dataframe(
            disagree[[c for c in ("ticket_id", "llm_evaluation", "human_evaluation",
                                  "llm_reason", "human_reason", "summary")
                      if c in disagree.columns]],
            hide_index=True, width="stretch",
        )
    st.caption(
        f"This sample ({n_total} tickets) is a spot-check, not a statistically "
        "representative audit — read the agreement number as a sanity signal only."
    )


def section_methodology(metrics: dict) -> None:
    with st.expander("Methodology & Limitations"):
        run = metrics.get("run", {})
        st.markdown(
            f"""
- **This is a historical backtest / counterfactual**, not a record of automation that
  occurred. Tickets were replayed through the chatbot after the fact.
- **What the chatbot saw:** only each ticket's opening summary. No resolution status, no
  later comments, no information that became available after the ticket was filed.
- **`resolved = True` does not mean a ticket was chatbot-deflectable.** It records what a
  human did. It is shown only as an extra outcome variable, never as the label.
- **Potential Deflection Rate = FULL ÷ total** is an *estimate* of what fraction *could*
  have been handled unaided — not observed real-world automation. Do not report it as
  "the chatbot automated X%".
- **The evaluator is an LLM** (`{run.get('evaluator_model', '?')}`) judging another LLM
  (`{run.get('chatbot_model', '?')}`). It never sees `resolved`. It can still make
  judgement errors — the Manual Validation section is the sanity check, and it is a
  spot-check, not a representative audit.
- **Retrieval:** production runs {'RAG' if run.get('prod_use_rag') else 'full-context (no retrieval step)'};
  the "Retrieved documentation" shown per ticket is a rule-based lexical overlap computed
  by this dashboard, not the chatbot's own mechanism.
- **Evaluator fallback:** a row marked `evaluator_fallback = True` was *not* genuinely
  classified (empty response, or invalid evaluator output) and defaults to HUMAN. Those
  rows are flagged throughout and should not be read as real evaluator verdicts.
- **Dataset scope:** whatever filtering produced `backtest_results.csv` (see the notebook)
  determines what these numbers describe. They are not automatically representative of the
  whole ticket history.
"""
        )
        if metrics and not metrics.get("_malformed"):
            st.json(metrics, expanded=False)


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #

def main() -> None:
    _configure_page()
    with st.sidebar:
        st.header("Data source")
        st.code(str(RESULTS_DIR), language="text")
        for f in ("backtest_results.csv", "summary_metrics.json", "manual_review_sample.csv"):
            st.write(("✅ " if (RESULTS_DIR / f).exists() else "❌ ") + f)
        if st.button("Reload files", width="stretch"):
            st.cache_data.clear()
            st.rerun()
        st.caption("Read-only view. No model calls are made.")
        st.divider()
        st.caption(
            "**Source**\n\n"
            "- `evaluation/jira_backtest.ipynb` — the experiment\n"
            "- `evaluation/backtest.py` — the harness (load · run · evaluate · score)\n"
            "- `evaluation/FINDINGS.md` — result & limitations write-up"
        )

    metrics = load_metrics(_mtime("summary_metrics.json"))
    df = load_results(_mtime("backtest_results.csv"))
    manual = load_manual(_mtime("manual_review_sample.csv"))

    section_header(metrics)

    if metrics.get("_malformed"):
        st.error("`summary_metrics.json` is present but not valid JSON — showing what can "
                 "be derived from `backtest_results.csv` instead.")
    if df.empty:
        st.warning(
            f"No `backtest_results.csv` found in `{RESULTS_DIR}` (or it is empty). "
            "Run the backtest notebook first — this dashboard only *displays* results.",
            icon="📭",
        )
        section_methodology(metrics)
        return

    # documentation-overlap enrichment (rule-based, cached, no LLM)
    if "summary" in df.columns and "nearest_doc_sections" not in df.columns:
        ov = doc_overlap(tuple(df["ticket_id"].astype(str)), tuple(df["summary"]))
        if not ov.empty and "_error" not in ov.columns:
            ov = ov.rename(columns={"ticket_id": "_tid"})
            df["_tid"] = df["ticket_id"].astype(str)
            df = df.merge(ov, on="_tid", how="left").drop(columns=["_tid"])

    fb = fallback_state(df)
    if fb == "some":
        n = int(df["evaluator_fallback"].fillna(False).astype(bool).sum())
        st.warning(
            f"**{n} of {len(df)} classifications were produced by the fallback mechanism** "
            "and should not be interpreted as valid evaluator results. They are flagged "
            "in the explorer and failure analysis.", icon="⚠️",
        )

    k = kpis(df, metrics)
    try:
        agreement = bt.evaluator_agreement(manual) if not manual.empty else {"reviewed": 0}
    except Exception:  # noqa: BLE001
        agreement = {"reviewed": 0}

    section_tldr(k, metrics, agreement)
    st.divider()
    section_kpis(k, metrics)
    st.divider()
    section_breakdown(df, fb)
    st.divider()
    section_reasons(df)
    st.divider()
    section_explorer(df)
    st.divider()
    section_failure_analysis(df)
    st.divider()
    section_trace(df)
    st.divider()
    section_manual(manual)
    st.divider()
    section_methodology(metrics)


# Guarded so `dashboard_real.py` (git-ignored) can `import` this module and reuse
# every section against a private results dir. `streamlit run` this file directly
# and it renders — Streamlit executes the target script as "__main__".
if __name__ == "__main__":
    main()
