"""
Regenerate the SYNTHETIC results set the public demo (`dashboard_mock.py`) reads.
No real Jira data, no LLM calls — everything here is fabricated by rules.

    python evaluation/mock_results/_generate.py

Source rows: evaluation/data/jira_tickets.sample.csv (committed synthetic support
tickets). The aim is a *believable* spread, not a flattering one:

  * distribution leans HUMAN (support queues do), ~27 / 21 / 52
  * HUMAN splits into genuine refusals and "bot tried, human still needed"
  * two answers get downgraded to a refusal by the grounding pass
  * latency is drawn from a seeded distribution with one rate-limit outlier
  * the manual-review sample has real disagreements (~75% agreement)
"""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from evaluation import backtest as bt  # noqa: E402

SAMPLE = ROOT / "evaluation" / "data" / "jira_tickets.sample.csv"
OUT = Path(__file__).resolve().parent
RNG = random.Random(20260907)

N = 33
src = pd.read_csv(SAMPLE, dtype=str).fillna("").head(N).reset_index(drop=True)

# --------------------------------------------------------------------------- #
# classification rules — keyed off the ticket text, like a real triage would be
# --------------------------------------------------------------------------- #

REFUSE_HINTS = ("password", "locked out", "staff account", "permission", "api ",
                "mobile app", "android", "subscription expired", "report needed",
                "revenue per", "refund", "merge two", "data migration", "import ",
                "hipaa", "second clinic location")
BUG_HINTS = ("cannot ", "not showing", "not loading", "greys out", "500 error",
             "infinite spinner", "wrong ", "double the", "prints with", "going to spam",
             "logged me out", "lost everything", "double-booked")
# the cleanest core tasks the docs cover end-to-end -> FULL. Everything else that
# is phrased as a how-to is only PARTIAL (docs cover the area, not the exact ask).
FULL_TOPICS = ("add a new patient profile", "book an appointment", "record a patient's vital",
               "write a soap note", "log an immunization", "create a prescription",
               "search for a patient", "reschedule an existing appointment",
               "cancel an appointment", "view a patient's past encounters",
               "record a deposit", "issue a patient bill", "add a diagnosis")

SECTIONS = [
    ("patient", "Patients (Patient Worklist)"), ("profile", "Patients (Patient Worklist)"),
    ("demographic", "Patients (Patient Worklist)"), ("appointment", "Appointments"),
    ("reschedule", "Appointments"), ("schedule", "Schedule module"),
    ("soap", "Encounters — Clinical Notes"), ("encounter", "Encounters"),
    ("vital", "Encounters — Vital Signs"), ("diagnosis", "Encounters — Diagnoses"),
    ("prescription", "Prescriptions"), ("immuniz", "Immunizations"),
    ("vaccine", "Immunizations"), ("bill", "Bills and Payments"),
    ("payment", "Bills and Payments"), ("deposit", "Bills and Payments"),
    ("invoice", "Bills and Payments"), ("department", "Facility Settings"),
    ("room", "Facility Settings — Resources"), ("location", "Locations (Branches)"),
    ("staff", "Staff Management"), ("permission", "Staff Management — Roles"),
    ("subscription", "Subscription"), ("reminder", "Notifications"),
    ("referral", "Service Requests"), ("service request", "Service Requests"),
]


def section_for(summary: str) -> str:
    s = summary.lower()
    for kw, name in SECTIONS:
        if kw in s:
            return name
    return "Core concepts"


def classify(summary: str) -> str:
    s = summary.lower()
    if any(h in s for h in REFUSE_HINTS):
        return "HUMAN_REFUSE"
    if any(h in s for h in BUG_HINTS):
        return "HUMAN_TRY"
    if any(t in s for t in FULL_TOPICS):
        return "FULL"
    return "PARTIAL"


# --------------------------------------------------------------------------- #
# response text — small pools so replies vary
# --------------------------------------------------------------------------- #

def full_steps() -> str:
    verbs = ["Open", "Go to", "Navigate to", "From the sidebar open"]
    n = RNG.randint(2, 4)
    lines = [f"1. {RNG.choice(verbs)} the relevant module."]
    extra = ["Select **Add** (or **Edit** on an existing record).",
             "Fill in the required fields — the form flags anything missing.",
             "Choose the patient / practitioner from the picker.",
             "Set the date and any optional details.",
             "Click **Save**."]
    RNG.shuffle(extra)
    for i, e in enumerate(extra[: n], start=2):
        lines.append(f"{i}. {e}")
    return "\n".join(lines)


def full_resp(section: str) -> str:
    tail = RNG.choice([
        "The change takes effect immediately.",
        "The record appears in the list straight away.",
        "You can edit it later from the same screen.",
    ])
    return f"From **{section}** in the documentation:\n\n{full_steps()}\n\n{tail}"


def partial_resp(section: str) -> str:
    gap = RNG.choice([
        "the exact option you're describing",
        "this specific configuration",
        "doing it in bulk",
        "the automated version of this",
    ])
    return (f"The documentation covers **{section}**, but it doesn't spell out {gap}. "
            f"What the docs *do* describe:\n\n{full_steps()}\n\n"
            f"You'll likely need a colleague to confirm the rest.")


def bug_resp() -> str:
    checks = ["Clear the browser cache and hard-refresh the page.",
              "Confirm every required field on the form is filled in.",
              "Check whether the same thing happens on another staff account.",
              "Try it in a different browser.",
              "Re-select the patient and retry the action."]
    RNG.shuffle(checks)
    body = "\n".join(f"- {c}" for c in checks[: RNG.randint(2, 3)])
    return ("A few things to check first:\n\n" + body +
            "\n\nIf none of that helps, this looks like a defect — please raise it "
            "with the support team so an engineer can look at it.")


REFUSAL = ("I don't have enough information in my records to answer that. "
           "Please submit a support ticket.")

REASONS = {
    "FULL": [
        "The reply gives the documented steps end to end and needs no staff action.",
        "Correct, specific and self-contained — a workflow could stop here.",
    ],
    "PARTIAL": [
        "On-topic and partly useful, but a staff member would still need to finish or verify it.",
        "The reply points to the right area but leaves a gap the user can't close alone.",
    ],
    "HUMAN": [
        "The request needs privileged access or a manual change by staff.",
        "The reply is a refusal — the documentation does not cover this.",
        "The bot offered troubleshooting, but resolving this needs an engineer / a decision.",
        "Requires a billing or subscription action that only an admin can perform.",
    ],
}
GROUND_FAIL_REASON = ("draft answer cited a UI label ('Bulk actions') that is not in "
                      "the documentation; downgraded to a refusal")

# --------------------------------------------------------------------------- #

now = datetime.now(timezone.utc)
rows = []
# pick two FULL-ish tickets whose answer the grounding pass will reject
ground_fail_idx = {7, 22}

for i, r in enumerate(src.itertuples(index=False)):
    kind = classify(r.summary)
    section = section_for(r.summary)
    resolved = r.resolved == "True"

    grounding_supported = True
    grounding_reason = "draft answer is supported by the documentation"

    if i in ground_fail_idx and kind in ("FULL", "PARTIAL"):
        cls, refused, resp = "HUMAN", True, REFUSAL
        grounding_supported = False
        grounding_reason = GROUND_FAIL_REASON
        reason = "The verification pass rejected the drafted answer, so it became a refusal."
    elif kind == "FULL":
        cls, refused, resp = "FULL", False, full_resp(section)
        reason = RNG.choice(REASONS["FULL"])
    elif kind == "PARTIAL":
        cls, refused, resp = "PARTIAL", False, partial_resp(section)
        reason = RNG.choice(REASONS["PARTIAL"])
    elif kind == "HUMAN_TRY":
        cls, refused, resp = "HUMAN", False, bug_resp()
        reason = REASONS["HUMAN"][2]
    else:  # HUMAN_REFUSE
        cls, refused, resp = "HUMAN", True, REFUSAL
        reason = RNG.choice([REASONS["HUMAN"][0], REASONS["HUMAN"][1], REASONS["HUMAN"][3]])
        grounding_reason = "assistant refused, which is allowed"

    # realistic latency: a refusal is one fast answer call; an answered ticket also
    # pays the verification pass; one ticket hits a rate-limit backoff.
    if i == 11:
        latency = round(RNG.uniform(24, 31), 2)      # rate-limit backoff
    elif i == 23:
        latency = round(RNG.uniform(7, 11), 2)       # a slow retry
    elif refused:
        latency = round(RNG.lognormvariate(-0.15, 0.30) + 0.55, 2)
    else:
        latency = round(RNG.lognormvariate(0.55, 0.35) + 1.1, 2)

    rows.append({
        "ticket_id": r.ticket_id,
        "summary": r.summary,
        "historical_resolved": resolved,
        "chatbot_response": resp,
        "classification": cls,
        "evaluation_reason": reason,
        "issue_type": r.issue_type,
        "priority": r.priority,
        "historical_status": "Done" if resolved else RNG.choice(["In Progress", "To Do"]),
        "chatbot_refused": refused,
        "grounding_checked": True,
        "grounding_supported": grounding_supported,
        "grounding_reason": grounding_reason,
        "chatbot_model": "gemini-3.1-flash-lite",
        "chatbot_error": "",
        "latency_s": latency,
        "answered_at": (now - timedelta(minutes=(N - i) * 3 + RNG.randint(0, 2)))
                       .isoformat(timespec="seconds"),
        "evaluator_model": "gemini-flash-latest",
        "evaluator_fallback": False,
        "summary_length": len(r.summary),
    })

df = pd.DataFrame(rows)
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
    "evaluator_fallback_count": 0,
    "chatbot_error_count": 0,
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
        "run_id": "demo-simulated-002",
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
    "generated_at": now.isoformat(timespec="seconds"),
}
(OUT / "summary_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

# --- manual review: 15 sampled, 12 human-labelled, 3 disagreements ---------- #
# (this is the one section the demo intentionally shows populated — item 7)
sample = df.sample(n=15, random_state=7).reset_index(drop=True)
man = pd.DataFrame({
    "ticket_id": sample["ticket_id"], "summary": sample["summary"],
    "chatbot_response": sample["chatbot_response"],
    "llm_evaluation": sample["classification"], "llm_reason": sample["evaluation_reason"],
})
shift = {"FULL": "PARTIAL", "PARTIAL": "HUMAN", "HUMAN": "PARTIAL"}
h, hr = [], []
for j, cls in enumerate(sample["classification"]):
    if j >= 12:
        h.append(""); hr.append("")
    elif j in (2, 6, 9):
        h.append(shift[cls])
        hr.append("Reviewer judged the interaction differently from the automated label.")
    else:
        h.append(cls); hr.append("Matches the automated label.")
man["human_evaluation"] = h
man["human_reason"] = hr
man["judge_correct"] = ""
man.to_csv(OUT / "manual_review_sample.csv", index=False)

print(f"wrote {OUT.name}/  ({total} rows)")
print(df["classification"].value_counts().to_string())
print(f"deflection {metrics['potential_deflection_rate']:.1%} | "
      f"likely_miss {metrics['likely_miss_count']} | "
      f"latency p50 {metrics['latency_s_p50']}s p95 {metrics['latency_s_p95']}s | "
      f"grounding downgrades {(~df['grounding_supported']).sum()}")
