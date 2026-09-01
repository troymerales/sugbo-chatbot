"""
Evaluation harness (§6 of the architecture doc) — the regression gate.

Runs the real inference pipeline (bot.respond, verification pass included) over
eval_set.jsonl, then scores each answer three ways:

  1. deterministic    — did it answer vs refuse as expected? are the must-include
                        doc tokens present?
  2. LLM-as-judge     — correctness + groundedness, scored by JUDGE_MODEL, which
                        must differ from ANSWER_MODEL (config enforces the default).
  3. aggregate        — per-slice metrics with bootstrap 95% CIs.

Outputs eval_scorecard.md + eval_scorecard.json. Re-run on every prompt / docs
change and compare against the committed scorecard.

Usage:
    python eval_run.py
    python eval_run.py --limit 10
    python eval_run.py --calibrate eval_labels.csv     # judge vs human, Cohen's kappa
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

import bot
import cli
import config
import knowledge
from llm import LLMError, QuotaError, generate

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass


# --------------------------------------------------------------------------- #
# Load
# --------------------------------------------------------------------------- #

def load_cases(limit: int | None = None) -> list[dict]:
    rows = []
    for line in config.EVAL_SET_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows[:limit] if limit else rows


# --------------------------------------------------------------------------- #
# Judge
# --------------------------------------------------------------------------- #

_JUDGE_RUBRIC = """You are grading a SugboDoc support assistant against the
product DOCUMENTATION (the only allowed source of truth).

You get: the DOCUMENTATION, the QUESTION, the EXPECTED BEHAVIOUR
("answer" or "refuse"), and the ASSISTANT ANSWER.

Score two things from 0.0 to 1.0:

- "correctness":
    * expected "answer": 1.0 if the answer gives the right steps/facts from the
      docs and is reasonably complete; partial credit for partially right.
    * expected "refuse": 1.0 if the assistant correctly says it doesn't have the
      information (and doesn't then invent an answer); 0.0 if it made something up.
- "groundedness": 1.0 if every specific claim (UI labels, paths, fields, steps)
    is supported by the DOCUMENTATION; lower as unsupported specifics appear.
    A correct refusal is fully grounded (1.0).

Reply with JSON only:
{"correctness": 0.0-1.0, "groundedness": 0.0-1.0, "notes": "one sentence"}"""


@dataclass
class JudgeScore:
    correctness: float
    groundedness: float
    notes: str
    ok: bool = True


def judge(question: str, expected_behavior: str, answer: str) -> JudgeScore:
    prompt = (
        f"DOCUMENTATION:\n{knowledge.load_docs()}\n\n"
        f"QUESTION:\n{question}\n\n"
        f"EXPECTED BEHAVIOUR: {expected_behavior}\n\n"
        f"ASSISTANT ANSWER:\n{answer}"
    )
    try:
        raw = generate(
            prompt, system=_JUDGE_RUBRIC, model=config.JUDGE_MODEL,
            temperature=0.0, json_mode=True,
        )
        data = json.loads(raw)
        return JudgeScore(
            correctness=float(data.get("correctness", 0.0)),
            groundedness=float(data.get("groundedness", 0.0)),
            notes=str(data.get("notes", "")),
        )
    except (LLMError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return JudgeScore(0.0, 0.0, f"judge failed: {exc}", ok=False)


# --------------------------------------------------------------------------- #
# Run one case
# --------------------------------------------------------------------------- #

@dataclass
class CaseResult:
    id: str
    expected_behavior: str
    answered: bool               # pipeline produced an answer (not a refusal)
    behavior_correct: bool
    must_include_hits: int
    must_include_total: int
    section_mentioned: bool
    grounding_supported: bool
    correctness: float
    groundedness: float
    answer: str
    judge_notes: str
    judge_ok: bool = True

    @property
    def must_include_pass(self) -> bool:
        return self.must_include_total == 0 or self.must_include_hits == self.must_include_total


def run_case(case: dict, *, with_judge: bool = True) -> CaseResult:
    chat = bot.fresh_chat()
    result = bot.respond(chat, case["question"])
    answer = result.text
    expected = case["expected_behavior"]
    answered = not result.refused

    behavior_correct = (answered and expected == "answer") or (
        not answered and expected == "refuse"
    )

    must = [t.lower() for t in case.get("must_include", [])]
    hits = sum(1 for t in must if t in answer.lower()) if expected == "answer" else 0
    total = len(must) if expected == "answer" else 0

    section = case.get("expected_section")
    section_mentioned = bool(section) and section.lower() in answer.lower()

    js = judge(case["question"], expected, answer) if with_judge else JudgeScore(
        0.0, 0.0, "judge skipped (--no-judge)", ok=True
    )

    return CaseResult(
        id=case["id"],
        expected_behavior=expected,
        answered=answered,
        behavior_correct=behavior_correct,
        must_include_hits=hits,
        must_include_total=total,
        section_mentioned=section_mentioned,
        grounding_supported=result.grounding.supported,
        correctness=js.correctness,
        groundedness=js.groundedness,
        answer=answer,
        judge_notes=js.notes,
        judge_ok=js.ok,
    )


# --------------------------------------------------------------------------- #
# Aggregate
# --------------------------------------------------------------------------- #

def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def bootstrap_ci(xs: list[float], *, iters: int = 2000, alpha: float = 0.05) -> tuple[float, float]:
    if len(xs) < 2:
        return (_mean(xs), _mean(xs))
    rng = random.Random(0)
    means = []
    n = len(xs)
    for _ in range(iters):
        sample = [xs[rng.randrange(n)] for _ in range(n)]
        means.append(_mean(sample))
    means.sort()
    lo = means[int(iters * alpha / 2)]
    hi = means[int(iters * (1 - alpha / 2))]
    return (lo, hi)


@dataclass
class Scorecard:
    generated_at: str
    answer_model: str
    judge_model: str
    n_cases: int
    backend: str = "gemini"
    metrics: dict = field(default_factory=dict)
    cases: list[dict] = field(default_factory=list)


def build_scorecard(results: list[CaseResult]) -> Scorecard:
    ans = [r for r in results if r.expected_behavior == "answer"]
    ref = [r for r in results if r.expected_behavior == "refuse"]

    behavior_all = [1.0 if r.behavior_correct else 0.0 for r in results]
    correctness_all = [r.correctness for r in results]

    over_refusals = [r for r in ans if not r.answered]
    missed_refusals = [r for r in ref if r.answered]

    metrics = {
        "behavior_accuracy": {
            "value": round(_mean(behavior_all), 3),
            "ci95": [round(x, 3) for x in bootstrap_ci(behavior_all)],
        },
        "mean_correctness": {
            "value": round(_mean(correctness_all), 3),
            "ci95": [round(x, 3) for x in bootstrap_ci(correctness_all)],
        },
        "answer_slice": {
            "n": len(ans),
            "mean_correctness": round(_mean([r.correctness for r in ans]), 3),
            "mean_groundedness": round(_mean([r.groundedness for r in ans]), 3),
            "must_include_pass_rate": round(_mean([1.0 if r.must_include_pass else 0.0 for r in ans]), 3),
            "section_mention_rate": round(_mean([1.0 if r.section_mentioned else 0.0 for r in ans]), 3),
            "over_refusal_rate": round(len(over_refusals) / len(ans), 3) if ans else 0.0,
        },
        "refuse_slice": {
            "n": len(ref),
            "correct_refusal_rate": round(1 - (len(missed_refusals) / len(ref)), 3) if ref else 0.0,
            "hallucinated_instead_of_refusing": [r.id for r in missed_refusals],
        },
    }

    card = Scorecard(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        answer_model=config.ANSWER_MODEL,
        judge_model=config.JUDGE_MODEL,
        n_cases=len(results),
        backend=config.LLM_BACKEND,
        metrics=metrics,
    )
    card.cases = [
        {
            "id": r.id, "expected": r.expected_behavior,
            "behavior_correct": r.behavior_correct,
            "correctness": round(r.correctness, 2),
            "groundedness": round(r.groundedness, 2),
            "must_include": f"{r.must_include_hits}/{r.must_include_total}",
            "judge_notes": r.judge_notes,
        }
        for r in results
    ]
    return card


def write_scorecard(card: Scorecard) -> None:
    config.SCORECARD_JSON_PATH.write_text(
        json.dumps(card.__dict__, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    m = card.metrics
    judged = card.judge_model not in ("", "(none — --no-judge)")
    lines = [
        "# SugboDoc Assistant — Eval Scorecard",
        "",
        f"- Generated: `{card.generated_at}`",
        f"- Backend: `{card.backend}`"
        + ("  ⚠️ **mock backend — plumbing check only, not a quality measurement**"
           if card.backend == "mock" else ""),
        f"- Answer model: `{card.answer_model}`  ·  Judge model: `{card.judge_model}`",
        f"- Cases: **{card.n_cases}**",
        "",
        "## Headline",
        "",
        "| Metric | Value | 95% CI |",
        "|---|---|---|",
        f"| Behaviour accuracy (answer vs refuse) | **{m['behavior_accuracy']['value']}** | {m['behavior_accuracy']['ci95']} |",
    ]
    if judged:
        lines.append(
            f"| Mean correctness (judge) | **{m['mean_correctness']['value']}** | {m['mean_correctness']['ci95']} |"
        )
    lines += [
        "",
        "## Answer slice",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Cases | {m['answer_slice']['n']} |",
    ]
    if judged:
        lines += [
            f"| Mean correctness | {m['answer_slice']['mean_correctness']} |",
            f"| Mean groundedness | {m['answer_slice']['mean_groundedness']} |",
        ]
    lines += [
        f"| Must-include token pass rate | {m['answer_slice']['must_include_pass_rate']} |",
        f"| Cited the expected section | {m['answer_slice']['section_mention_rate']} |",
        f"| Over-refusal rate (refused an answerable Q) | {m['answer_slice']['over_refusal_rate']} |",
        "",
        "## Refuse slice (the hallucination guard)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Cases | {m['refuse_slice']['n']} |",
        f"| Correct-refusal rate | **{m['refuse_slice']['correct_refusal_rate']}** |",
        f"| Hallucinated instead of refusing | {m['refuse_slice']['hallucinated_instead_of_refusing'] or 'none'} |",
        "",
        "## Per-case",
        "",
    ]
    if judged:
        lines += [
            "| id | expected | behaviour | correctness | groundedness | must-incl | judge notes |",
            "|---|---|---|---|---|---|---|",
        ]
        for c in card.cases:
            ok = "✅" if c["behavior_correct"] else "❌"
            lines.append(
                f"| {c['id']} | {c['expected']} | {ok} | {c['correctness']} | "
                f"{c['groundedness']} | {c['must_include']} | {c['judge_notes']} |"
            )
    else:
        lines += [
            "| id | expected | behaviour | must-incl |",
            "|---|---|---|---|",
        ]
        for c in card.cases:
            ok = "✅" if c["behavior_correct"] else "❌"
            lines.append(f"| {c['id']} | {c['expected']} | {ok} | {c['must_include']} |")
    config.SCORECARD_MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Calibration
# --------------------------------------------------------------------------- #

def cohens_kappa(a: list[int], b: list[int]) -> float:
    n = len(a)
    if n == 0:
        return 0.0
    agree = sum(1 for x, y in zip(a, b) if x == y) / n
    pa1 = sum(a) / n
    pb1 = sum(b) / n
    pe = pa1 * pb1 + (1 - pa1) * (1 - pb1)
    return (agree - pe) / (1 - pe) if pe != 1 else 1.0


def calibrate(results: list[CaseResult], labels_csv: str) -> None:
    human: dict[str, int] = {}
    with open(labels_csv, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("id") and row.get("human_correct") not in (None, ""):
                human[row["id"].strip()] = int(float(row["human_correct"]))

    pairs = [(human[r.id], 1 if r.correctness >= 0.5 else 0) for r in results if r.id in human]
    if not pairs:
        print("No overlapping ids between the label CSV and the eval run.")
        return
    h, j = [p[0] for p in pairs], [p[1] for p in pairs]
    agree = sum(1 for x, y in zip(h, j) if x == y) / len(pairs)
    print(f"\nCalibration ({len(pairs)} labelled cases):")
    print(f"  raw agreement : {agree:.3f}")
    print(f"  Cohen's kappa : {cohens_kappa(h, j):.3f}")
    disagreements = [r.id for r in results if r.id in human and human[r.id] != (1 if r.correctness >= 0.5 else 0)]
    if disagreements:
        print(f"  disagreements : {', '.join(disagreements)}")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--calibrate", metavar="LABELS_CSV", default=None)
    ap.add_argument("--no-judge", action="store_true",
                    help="skip the LLM judge — deterministic checks only (cheap)")
    cli.add_llm_flags(ap)
    args = ap.parse_args()
    cli.apply_llm_flags(args)

    if config.LLM_BACKEND == "gemini" and not config.get_api_key():
        raise SystemExit("GEMINI_API_KEY is not set (see .env.example). Or run --mock.")
    with_judge = not args.no_judge
    if with_judge and config.JUDGE_MODEL == config.ANSWER_MODEL and config.LLM_BACKEND == "gemini":
        print("WARNING: JUDGE_MODEL == ANSWER_MODEL — set GEMINI_JUDGE_MODEL to a "
              "different (stronger) model for a trustworthy score.\n")

    cases = load_cases(args.limit)
    print(f"Running {len(cases)} eval cases through bot.respond() "
          f"[backend={config.LLM_BACKEND}, judge={'on' if with_judge else 'off'}]…\n")

    results: list[CaseResult] = []
    for i, case in enumerate(cases, 1):
        try:
            r = run_case(case, with_judge=with_judge)
        except QuotaError as exc:
            print(f"\n{exc}\n")
            print(f"Stopping after {len(results)} of {len(cases)} cases — "
                  "writing a PARTIAL scorecard.")
            break
        results.append(r)
        mark = "ok " if r.behavior_correct else "MISS"
        print(f"  [{i:>2}/{len(cases)}] {mark} {r.id:<32} "
              f"corr={r.correctness:.2f} grnd={r.groundedness:.2f}")

    if not results:
        raise SystemExit("No cases completed.")

    judge_failures = [r for r in results if not r.judge_ok]
    if with_judge and len(judge_failures) > len(results) * 0.3:
        raise SystemExit(
            f"\nJUDGE BROKEN: {len(judge_failures)}/{len(results)} judge calls failed "
            f"(model `{config.JUDGE_MODEL}`). The correctness/groundedness numbers "
            "would be meaningless. First error:\n  "
            + judge_failures[0].judge_notes[:300]
            + "\n\nFix GEMINI_JUDGE_MODEL and re-run."
        )

    card = build_scorecard(results)
    card.judge_model = config.JUDGE_MODEL if with_judge else "(none — --no-judge)"
    write_scorecard(card)

    m = card.metrics
    print("\n" + "=" * 60)
    print(f"behaviour accuracy : {m['behavior_accuracy']['value']}  CI {m['behavior_accuracy']['ci95']}")
    if with_judge:
        print(f"mean correctness   : {m['mean_correctness']['value']}  CI {m['mean_correctness']['ci95']}")
    print(f"must-include pass  : {m['answer_slice']['must_include_pass_rate']}")
    print(f"correct-refusal    : {m['refuse_slice']['correct_refusal_rate']}  "
          f"({m['refuse_slice']['n']} cases)")
    print(f"over-refusal       : {m['answer_slice']['over_refusal_rate']}")
    print("=" * 60)
    print(f"\nwrote {config.SCORECARD_MD_PATH.name} and {config.SCORECARD_JSON_PATH.name}")

    if args.calibrate:
        calibrate(results, args.calibrate)


if __name__ == "__main__":
    try:
        main()
    except QuotaError as exc:
        raise SystemExit(str(exc))
