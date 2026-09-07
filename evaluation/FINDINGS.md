# Jira Chatbot Historical Backtest — Findings

_Run `backtest-20260907-1142`. Numbers below are read straight from
`results/summary_metrics.json`; re-running the notebook regenerates both._

## The question

> If the SugboDoc support chatbot had existed when a batch of historical Jira
> tickets was filed, how many could it plausibly have handled **without human
> intervention**?

This is a **historical counterfactual**, not a measurement of automation that
happened.

## Method

1. **Chatbot** — the production pipeline, unchanged: `core.bot.fresh_chat()` +
   `core.bot.respond()` (answer model `gemini-3.1-flash-lite`, full documentation
   in-context, second-pass grounding check on). One fresh single-turn chat per
   ticket. It receives **only the ticket's opening summary** — no resolution
   status, no later comments, nothing that became known after filing.
2. **Evaluator** — a *separate* model (`gemini-flash-latest`; the intended
   `gemini-pro-latest` was daily-quota-exhausted), its own strict prompt, judged
   15 tickets per call. It sees only *(summary, reply)* and classifies each as
   `FULL` / `PARTIAL` / `HUMAN`.
3. **Dataset** — 33 tickets: a real Jira export of 50 product user stories,
   filtered to `Type ∈ {staff member, admin, doctor, user}` (see
   `jira_backtest.ipynb` §2b). Ticket text is not committed.

## Result

| | count | rate |
|---|---:|---:|
| **FULL** — could plausibly close unaided | **2** | **6.1%** |
| PARTIAL — real help, human still needed | 0 | 0.0% |
| HUMAN — needs a person | 31 | 93.9% |

**Potential ticket deflection: 6.1%** (2 / 33).

- **31 of 33 chatbot replies were the fixed refusal** ("I don't have enough
  information in my records…"). A refusal is always `HUMAN` by rule, so the
  evaluator was barely exercised on this dataset.
- **2 `FULL`**: a document-template-header how-to and a facility-setup walkthrough
  — both got correct, doc-grounded step-by-step answers.
- **Cost / latency**: ≈ 66 chatbot calls + 3 evaluator calls; per-ticket latency
  median 1.1 s, p95 35.3 s (one call hit a rate-limit backoff), ≈ 3.5 min total.
- **Likely misses**: 12 of the 31 refusals have ≥ 25% lexical overlap with a
  documentation section (`likely_misses()` — a lexical upper bound). Tickets like
  "view the SOAP Note List" or "filter appointment lists by location" are
  probably covered by the docs; the bot declined because they're phrased as
  feature-improvement requests, not "how do I" questions. **This is the most
  actionable output**: prompt/framing changes might recover some of them.

## What this does and does not show

- ✅ *"~6% potential ticket deflection, estimated by historical backtesting."*
- ❌ *"The chatbot automated 6% of support tickets."* — it never ran in production
  on these tickets.
- The **dataset is a feature backlog, not a support queue.** User stories ("As an
  Admin, I want a financial dashboard…") are engineering work, not documentation
  questions. So 6.1% here mostly measures *"how much of this backlog is a
  documented how-to"* — a valid finding, but not the same as "support deflection".
- **The evaluator is not yet validated against human labels.** `manual_review_
  sample.csv` has 33 rows but no human column filled, so agreement / Cohen's κ
  are unknown. The headline number currently has no independent sanity check.
- **Small n (33)** with only 2 positives — treat 6.1% as directional, wide error
  bars.
- **Knowledge-base drift** — the bot answered from *today's* docs, not the docs as
  they were when each ticket was filed.
- **`historical_resolved`** is degenerate here (all `Done`); the
  classification-vs-outcome cut is uninformative for this dataset.

## Next steps (highest value first)

1. **Validate the evaluator.** Hand-label ~25–30 rows of `manual_review_sample.csv`;
   report agreement + κ next to the 6.1%. Optionally run a second judge model and
   report inter-judge agreement.
2. **Run on an actual support-ticket export** (helpdesk queue: "how do I…",
   "X is broken", password resets) — the shape the chatbot is built for.
3. **Triage the 12 likely-misses individually**: are the docs really covering
   them? If so, that points at a prompt/retrieval fix worth ~N points of
   deflection.
4. **Verification-pass ablation** (`run_backtest(..., verify_answers=False)`):
   quantify how many `FULL`s the grounding check costs, and whether those were
   real hallucinations or over-caution.
5. Add confidence intervals and a naive baseline ("always refuse", "always
   attempt") for context.
