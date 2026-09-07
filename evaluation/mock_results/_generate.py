"""
Regenerate the SYNTHETIC results set that the public demo (`dashboard_mock.py`)
reads. No real Jira data, no LLM calls.

    python evaluation/mock_results/_generate.py

Source: evaluation/data/jira_tickets.sample.csv (committed synthetic sample).
Classifications / responses / reasons are fabricated by simple rules to give the
demo a believable, slightly messy spread that exercises every panel:
evaluator fallbacks, likely-misses, and a few human-vs-LLM disagreements.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from evaluation import backtest as bt  # noqa: E402

SAMPLE = ROOT / "evaluation" / "data" / "jira_tickets.sample.csv"
OUT = Path(__file__).resolve().parent

src = pd.read_csv(SAMPLE, dtype=str).fillna("").head(30).reset_index(drop=True)

# --- fabricate classifications: real bug/access/billing tickets -> HUMAN,
#     the rest split FULL / PARTIAL deterministically so the demo has a spread.
HUMAN_HINTS = ("cannot", "not showing", "error", "wrong", "expired", "locked out",
               "500", "spinner", "double", "migration", "import", "api", "hipaa",
               "duplicate", "merge", "refund", "void", "report", "bulk", "spam",
               "no-show", "lost everything", "restriction")


def classify(idx: int, summary: str) -> str:
    s = summary.lower()
    if any(h in s for h in HUMAN_HINTS):
        return "HUMAN"
    return "FULL" if idx % 2 else "PARTIAL"


FULL_RESP = ("From the **{topic}** section of the documentation:\n\n1. Open the module "
             "from the sidebar.\n2. Choose **Add / Edit** and fill in the fields.\n"
             "3. Save — the change applies immediately. [demo response]")
PARTIAL_RESP = ("The documentation covers this area under **{topic}**, but not the exact "
                "option you describe. Here is the closest documented procedure… "
                "[demo response]")
REFUSAL = "I don't have enough information in my records to answer that. Please submit a support ticket."
REASONS = {
    "FULL": "The reply gives the documented steps and needs no staff action.",
    "PARTIAL": "On-topic and partially helpful, but a staff member would still need to confirm or finish it.",
    "HUMAN": "Needs privileged access, a manual change, investigation or a decision — or the reply is a refusal.",
}

now = datetime.now(timezone.utc).isoformat(timespec="seconds")
rows = []
for i, r in enumerate(src.itertuples(index=False)):
    cls = classify(i, r.summary)
    topic = r.summary.split(":")[0][:44]
    fallback = i in (5, 19)                       # two demo evaluator fallbacks
    if fallback:
        cls = "HUMAN"
    refused = cls == "HUMAN"
    resp = "" if fallback and i == 5 else (
        FULL_RESP.format(topic=topic) if cls == "FULL"
        else PARTIAL_RESP.format(topic=topic) if cls == "PARTIAL"
        else REFUSAL)
    reason = ("No chatbot response was produced for this ticket." if (fallback and i == 5)
              else "Evaluator did not return a valid classification after 2 attempts; "
                   "defaulted to HUMAN (conservative)." if fallback
              else REASONS[cls])
    rows.append({
        "ticket_id": r.ticket_id,
        "summary": r.summary,
        "historical_resolved": (r.resolved == "True"),
        "chatbot_response": resp,
        "classification": cls,
        "evaluation_reason": reason,
        "issue_type": r.issue_type,
        "priority": r.priority,
        "historical_status": "Done" if r.resolved == "True" else "In Progress",
        "chatbot_refused": refused,
        "grounding_checked": True,
        "grounding_supported": True,
        "grounding_reason": "assistant refused, which is allowed" if refused
                            else "draft answer reflects the documentation",
        "chatbot_model": "gemini-3.1-flash-lite",
        "chatbot_error": "TimeoutError: demo" if (fallback and i == 5) else "",
        "latency_s": round(1.0 + (i % 7) * 0.6 + (12.0 if i == 11 else 0.0), 2),
        "answered_at": now,
        "evaluator_model": "gemini-flash-latest",
        "evaluator_fallback": fallback,
        "summary_length": len(r.summary),
    })

df = pd.DataFrame(rows)
# bake in the rule-based doc-overlap columns (same helper the real run uses)
df = df.merge(bt.doc_overlap_frame(df[["ticket_id", "summary"]]), on="ticket_id", how="left")
df.to_csv(OUT / "backtest_results.csv", index=False)

total = len(df)
c = df["classification"].value_counts().to_dict()
full, partial, human = c.get("FULL", 0), c.get("PARTIAL", 0), c.get("HUMAN", 0)
lat = df["latency_s"]
metrics = {
    "total_tickets": total, "full": full, "partial": partial, "human": human,
    "potential_deflection_rate": round(full / total, 4),
    "partial_assistance_rate": round(partial / total, 4),
    "human_required_rate": round(human / total, 4),
    "evaluator_fallback_count": int(df["evaluator_fallback"].sum()),
    "chatbot_error_count": int((df["chatbot_error"] != "").sum()),
    "est_chatbot_calls": total * 2,
    "est_evaluator_calls": -(-total // 15),
    "latency_s_p50": round(float(lat.quantile(0.5)), 2),
    "latency_s_p95": round(float(lat.quantile(0.95)), 2),
    "latency_s_mean": round(float(lat.mean()), 2),
    "chatbot_wall_time_s": round(float(lat.sum()), 1),
    "likely_miss_count": int(len(bt.likely_misses(df))),
    "historical_resolved_true": int(df["historical_resolved"].sum()),
    "historical_resolved_false": int((~df["historical_resolved"]).sum()),
    "run": {
        "run_id": "demo-simulated-001",
        "chatbot_model": "gemini-3.1-flash-lite",
        "evaluator_model": "gemini-flash-latest",
        "batch_size": 50, "eval_batch_size": 15, "evaluator_temperature": 0.0,
        "max_workers": 1, "limit": None,
        "prod_answer_model": "gemini-3.1-flash-lite",
        "prod_utility_model": "gemini-3.1-flash-lite",
        "prod_chat_temperature": 0.2,
        "prod_verify_answers": True, "prod_use_rag": False, "prod_rag_top_k": None,
        "prod_llm_backend": "gemini",
        "prod_refusal_marker": "I don't have enough information in my records to answer that",
        "note": "SIMULATED dataset for the public demo — not a real backtest run.",
    },
    "generated_at": now,
}
(OUT / "summary_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

# --- manual review sample: 12 rows, 10 human-labelled, 2 disagreements ------- #
sample = df.sample(n=12, random_state=7).reset_index(drop=True)
man = pd.DataFrame({
    "ticket_id": sample["ticket_id"], "summary": sample["summary"],
    "chatbot_response": sample["chatbot_response"],
    "llm_evaluation": sample["classification"], "llm_reason": sample["evaluation_reason"],
})
h, hr = [], []
for i, cls in enumerate(sample["classification"]):
    if i >= 10:
        h.append(""); hr.append("")
    elif i in (3, 8):
        h.append({"FULL": "PARTIAL", "PARTIAL": "HUMAN", "HUMAN": "PARTIAL"}[cls])
        hr.append("Reviewer judged this needs more human involvement than the model did.")
    else:
        h.append(cls); hr.append("Agrees with the automated label.")
man["human_evaluation"] = h
man["human_reason"] = hr
man["judge_correct"] = ""
man.to_csv(OUT / "manual_review_sample.csv", index=False)

print("wrote", OUT.name, "/", total, "rows")
print(df["classification"].value_counts().to_string())
print("deflection", metrics["potential_deflection_rate"],
      "| fallbacks", metrics["evaluator_fallback_count"],
      "| likely_miss", metrics["likely_miss_count"])
