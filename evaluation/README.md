# `evaluation/` — Jira chatbot historical backtest

A counterfactual experiment: **had this exact SugboDoc support chatbot existed when a batch
of historical Jira tickets was filed, how many could it plausibly have handled without a
human?** The output is a **Potential Ticket Deflection Rate**.

This package does **not** modify the chatbot. It imports and runs the production inference
path unchanged.

```
evaluation/
├── jira_backtest.ipynb        the experiment (run this)
├── backtest.py                reusable engine — loading, running, evaluating, metrics, plots
├── dashboard.py               read-only Streamlit dashboard over the saved results
├── data/
│   ├── jira_tickets.sample.csv committed synthetic sample (so the notebook runs on a clone)
│   └── jira_tickets.csv        <- your real export goes here (git-ignored)
└── results/                    generated, git-ignored
    ├── chatbot_responses.csv   phase-1 output (resumable checkpoint)
    ├── evaluations.csv         phase-2 output (resumable checkpoint)
    ├── backtest_results.csv    merged, one row per evaluated ticket
    ├── manual_review_sample.csv sample for human validation (+ judge_correct column)
    └── summary_metrics.json    headline numbers + full run config
```

## Quick start

```bash
pip install -r requirements.txt -r requirements-eval.txt
jupyter notebook evaluation/jira_backtest.ipynb        # run the backtest
streamlit run evaluation/dashboard.py                  # explore the results
```

## Dashboard

`evaluation/dashboard.py` is a **read-only** view over `evaluation/results/` — it never runs
the backtest and **makes zero model calls**. Sections: KPI cards, classification breakdown,
rule-based reason analysis (reuses `backtest.FAILURE_PATTERNS`), a ticket explorer with
per-ticket detail, failure-mode slices, and human-vs-LLM agreement from
`manual_review_sample.csv`. It computes a transparent lexical doc-overlap signal on load
(no LLM) since production runs full-context with no retrieval record. Handles missing
files, empty data, malformed JSON, and evaluator-fallback rows with clear messages.

Rehearse the whole flow for free first: in Section 2 set `os.environ["LLM_BACKEND"]="mock"`
before the imports. (The mock backend cannot act as the evaluator, so every ticket comes
back `HUMAN` — that only proves the plumbing.)

## Your dataset

Drop a CSV at `evaluation/data/jira_tickets.csv` (or any `jira_tickets*.csv` that
isn't the sample — e.g. `jira_tickets_history.csv`). `load_tickets()` normalises common
Jira-export header variants:

| canonical | accepted source headers (case-insensitive) | notes |
|---|---|---|
| `ticket_id` | `ticket_id`, `Issue id`, `Issue key`, `Key`, `Id` | must be unique |
| `summary` | `summary`, `Title`, `Subject`, `Name` | the opening one-liner — the **only** thing the chatbot sees |
| `historical_resolved` | `Resolution`, `Resolved`, `Status` | historical metadata; **never shown to the bot or the evaluator**. Blank `Resolution` falls back to `Status` |
| `historical_status` | `Status`, `State` | kept for analysis only |
| `issue_type`, `priority`, `project`, `category`, `created_at` | `Issue Type`, `Priority`, `Component`, … | carried through for Graph 5 |

> **Note on ticket type.** If the export is product **user stories / feature requests**
> ("As an Admin, I want …"), expect a low deflection rate — those are engineering work, not
> documentation questions. That is a real finding ("what fraction of our backlog is
> docs-answerable"), not a bug.

## How the chatbot is reused

`backtest.run_chatbot()` calls:

```python
chat = core.bot.fresh_chat()          # config.ANSWER_MODEL + knowledge.system_prompt()
result = core.bot.respond(chat, summary)   # answer + verification pass — the prod pipeline
```

That is the same code the Streamlit widget (`assistant/`) and the FastAPI backend
(`api/service.py`) run. One fresh single-turn `Chat` per ticket. The chatbot model is
**not** configurable in the notebook — it is read from `config.ANSWER_MODEL` and recorded
in `summary_metrics.json`.

## How responses are evaluated

A **separate** role: `EVALUATOR_MODEL` (default `config.JUDGE_MODEL`, a different/stronger
model), its own strict prompt (`backtest.EVALUATOR_SYSTEM`), `temperature=0`, JSON output.
It receives **only** `(summary, chatbot_response)` — never `historical_resolved`. Output is
constrained to `FULL` / `PARTIAL` / `HUMAN`; a malformed reply is retried once, then
defaults to `HUMAN` (the conservative label).

**Batched.** `EVAL_BATCH_SIZE` tickets are judged per call — one request returns a JSON
array of verdicts, cutting evaluator calls ~Nx. Every verdict must echo its `ticket_id`;
the count and id-set are validated and anything dropped/mislabelled is re-judged
individually. Batching the *evaluator* is safe (it is not the production chatbot); the
chatbot phase is **never** batched.

### Was the judge right? (`judge_correct`)

The manual-review sample carries a `judge_correct` column. `backtest.score_manual_review()`
fills it `yes`/`no` per row once a human label is present (blank otherwise), and
`evaluator_agreement()` reports `judge_correct` / `judge_incorrect` counts alongside the
agreement rate and Cohen's kappa. This is the sanity check on the LLM-as-a-judge.

| label | meaning |
|---|---|
| `FULL` | correct, specific, self-sufficient — a workflow could end here, no human needed |
| `PARTIAL` | real on-topic help, but a human still very likely needs to finish/verify/act |
| `HUMAN` | needs access / a manual change / a decision / investigation, or the reply is a refusal, vague, wrong or hallucinated |

## Resumability

Both phases append to CSV after every `BATCH_SIZE` tickets and skip `ticket_id`s already
present. Interrupt any time; re-run to continue. A Gemini daily-quota error (`llm.QuotaError`)
stops the run cleanly with everything so far saved. Delete a `results/*.csv` to redo that
phase from scratch.

Cost ≈ 2 Gemini calls per ticket for the chatbot (answer + verification) + 1 for the
evaluator. The `core.llm` SQLite cache (`logs/llm_cache.sqlite`) means re-running an
unchanged ticket is free.

## Limitations

* **Counterfactual** — no real users, no multi-turn conversation, no follow-up. A summary is
  a lossy proxy for the ticket thread.
* **LLM-judges-LLM** — Section 8 exports a sample for human labelling and computes
  agreement + Cohen's kappa. Quote the deflection rate with that number attached.
* **KB drift** — the bot answers from today's `docs/SugboDoc-Documentation.md`, not the docs
  as they were when each ticket was filed.
* **`historical_resolved` is not ground truth** for deflectability — it records what humans
  did. Graph 3 is exploratory only.

Report the result as *"XX % **potential** ticket deflection, from historical backtesting"* —
never *"the chatbot automated XX % of tickets"*.
