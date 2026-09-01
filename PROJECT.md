# SugboDoc Support Assistant — Project Guide

A documentation-grounded support chatbot for **SugboDoc**, a clinic / practice-management
SaaS. The bot answers "how do I…" questions **only** from the product documentation, and
when it can't, it captures that failure and turns it into a Jira ticket and/or a
documentation-improvement task — so the knowledge base gets better over time.

This file is the walkthrough: what each piece does, why it's built that way, and how to run
it. The higher-level design rationale (with diagrams and the "techniques deliberately not
used" table) is in **`SugboDoc-Chatbot-Flowchart.md`**.

---

## 1. The idea in one paragraph

The product docs are small (~8k tokens). So instead of a vector database and retrieval
(RAG), the **whole document goes into the prompt every turn**. A second, independent model
call then checks the answer against the docs — a *verification pass* — and if any claim
isn't supported, the answer is replaced with a fixed refusal. Every conversation is logged.
Failed conversations feed two loops: an **outbound Jira ticket** (created only when the user
asks) and an offline **docs-maintenance loop** that clusters failures, drafts documentation
fixes, and re-scores them against an evaluation harness before they ship. Jira is *never*
read during a chat — the only path from Jira back to the bot is `Jira → docs → bot`.

---

## 2. Repository layout

```
chatbot/
├── SugboDoc-Documentation.md      the knowledge base (the single source of truth)
├── system-prompt.md              the original hand-written system prompt (reference)
├── SugboDoc-Chatbot-Flowchart.md design rationale + diagrams + file map (§12)
├── PROJECT.md                    ← you are here
│
├── config.py            paths, model names, thresholds, backend switches
├── llm.py               the one interface to a model: generate / chat / embed + cache
├── _gemini_backend.py   real Gemini calls (only llm.py imports it)
├── _mock_backend.py     offline deterministic stand-in (no API key / quota)
├── knowledge.py         load docs → sections → system prompt
├── grounding.py         the verification pass
├── failure_capture.py   rule-based failure signals + triage
├── ticketing.py         draft a ticket from a conversation
├── jira_client.py       create Jira issues (outbound) + two batch reads
├── jira_dedup.py        embed a draft vs open tickets → duplicate check
├── chatlog.py           append / load logs/chats.jsonl
├── bot.py               respond() — the inference pipeline (answer + verify)
├── engine.py            the conversation state machine (UI-independent)
│
├── app.py               Streamlit demo UI
├── service.py           FastAPI backend (JSON API + bundled web widget)
├── web/index.html       vanilla-JS chat widget served by service.py
│
├── eval_set.jsonl       90 graded test cases (61 answerable + 29 must-refuse)
├── eval_run.py          run the pipeline over eval_set → eval_scorecard.md
├── eval_gen.py          draft synthetic eval questions from each doc section
├── eval_labels_template.csv   for judge-vs-human calibration (Cohen's κ)
│
├── analytics_kpis.py    KPIs from the chat log (no model calls)
├── analytics_cluster.py cluster failed questions → logs/doc_gap_queue.json
├── docs_loop.py         queue + resolved Jira → drafted doc changes → doc_proposals/
├── seed_demo_log.py     synthetic chat log so the analytics scripts are demoable
│
├── llm_cache.py         inspect / clear the response cache
├── cli.py               shared --mock / --offline / --no-cache flags
├── jira_check.py        standalone Jira connectivity + field diagnostic
├── jira_test_ticket.py  end-to-end "file a real ticket" test
│
└── tests/               pytest suite (runs fully offline, 40 tests)
```

---

## 3. Core library — file by file

### `config.py`
Single place that loads `.env` (once) and holds every tunable. Nothing else calls
`load_dotenv`.

Key names:
- `ANSWER_MODEL`, `UTILITY_MODEL`, `JUDGE_MODEL`, `EMBED_MODEL` — all overridable via env.
  The judge **must differ** from the answer model or the eval score is inflated.
- `QUESTIONS_BEFORE_TICKET` (default 3) — after this many questions without a 👍, the bot
  proactively offers a ticket.
- `DEDUP_SIMILARITY_THRESHOLD` (default 0.82) — cosine similarity above which a drafted
  ticket is treated as a duplicate.
- `REFUSAL_MARKER` — the exact sentence the bot must emit when it can't answer.
- `LLM_BACKEND` (`gemini` | `mock`), `LLM_CACHE` (bool), `LLM_OFFLINE` (bool) — read
  **live on every call**, so scripts flip them at runtime via `cli.py`.

### `llm.py`
The only module that knows how to talk to a model. Everything else calls:
- `generate(prompt, system=?, model=?, temperature=?, json_mode=?) -> str` — one-shot.
- `new_chat(system, ...) -> Chat` and `Chat.send(text) -> str` — multi-turn. `Chat` is a
  plain dataclass whose `.history` is a list of `{"role", "text"}` — so it caches and
  pickles (important: the Streamlit app keeps one in session state).
- `embed(texts) -> list[list[float]]`.

Behind those:
- **`_cached(kind, payload, produce)`** — hashes the request (model + system + messages +
  temperature + backend) into `logs/llm_cache.sqlite`. On a hit, returns instantly. If
  `config.LLM_OFFLINE`, a miss raises `OfflineCacheMiss` instead of calling out. This is
  what lets you iterate on the eval harness all day against a warm cache with zero quota.
- **`retry(fn)`** — 4 attempts with backoff; parses `retryDelay` out of a 429 body to pace
  per-minute throttling; raises **`QuotaError`** (not an `LLMError`, so it propagates past
  every `except LLMError` and stops the run cleanly) when it sees a *daily* quota 429.
- `cache_stats()` / `clear_cache()` — used by `llm_cache.py`.
- Errors: `LLMError` (catch-all), `QuotaError`, `OfflineCacheMiss`.

### `_gemini_backend.py`
Real Gemini SDK calls. `_to_contents()` converts the neutral `{"role","text"}` list into
`types.Content`. Imported lazily so the mock path never needs `google-genai` or a key.

### `_mock_backend.py`
Deterministic offline stand-in, selected by `--mock` / `LLM_BACKEND=mock`. It is **not
smart** — it exists so every code path runs without an API key:
- `generate()` inspects the *system prompt* to tell which call it is (verify / triage /
  draft / judge / cluster-label / docs-loop) and returns well-formed JSON for each; for a
  plain user question it does naive word-overlap retrieval over the doc sections
  (`_retrieve`) and returns that section's steps, or the refusal if nothing scores well.
- `embed()` — hashed bag-of-words → 256-dim L2-normalised vectors. Real *lexical* cosine
  similarity (similar wording → similar vectors), enough for the dedup / clustering code
  to run and be tested.

Use it for: tests, the FastAPI demo, wiring up the loop. Not for: measuring answer
quality — that needs the real model.

### `knowledge.py`
- `load_docs()` — cached read of `SugboDoc-Documentation.md`.
- `sections()` — splits the doc on `##` / `###` headings into `Section(slug, title, level,
  body)`. 60+ sections. `content_sections()` drops the table of contents.
- `find_section(needle)` — loose lookup by slug or title substring (used by the eval
  section-match check and `docs_loop.py`).
- `system_prompt()` — assembles `PERSONA` (the answer rules + the exact refusal sentence) +
  the full docs between fences. **This is where the "no retrieval" decision lives** — to
  add section-level retrieval later you change only this function.

### `grounding.py` — the verification pass
`verify(question, draft_answer) -> GroundingVerdict`. A second model call with a
fact-checker rubric: is every specific claim (UI labels, paths, steps) in the docs?
- If the draft already contains the refusal marker → trivially supported, no call.
- Returns `GroundingVerdict(supported, unsupported_claims, reason, checked)`.
  `checked=False` means the verification call itself failed — we **fail open** (don't block
  the answer) but record it.
- `is_refusal_worthy` → the app/engine swaps in the refusal.

Why a separate pass: a model is weak at self-policing "I don't know" inside one call. A
cheap independent check catches hallucinations. Its strictness is a knob you tune against
the eval set.

### `failure_capture.py`
Two jobs:
- **`detect_failures(messages, thumbs_down=?, grounding_failed=?) -> FailureSignals`** —
  pure rules, no model:
  - `refused` — an assistant turn contains the refusal marker
  - `thumbs_down` — the user pressed 👎
  - `grounding_failed` — the verification pass rejected an answer
  - `repeated_question` — two user turns with `difflib` similarity ≥ 0.8
  - `negative_feedback` — the last user turn contains a phrase like "not helpful" / "that's
    wrong"
  *Rules first, model later:* a dissatisfaction classifier is only worth training once the
  logs show these rules missing failures.
- **`triage(transcript) -> TriageResult`** — one model call: `docs_gap` | `product_bug` |
  `out_of_scope`. Drives whether to offer a ticket and where the failure is filed.

### `ticketing.py`
`draft_ticket(transcript) -> TicketDraft(subject, category, summary)`. One model call that
turns a failed conversation into a structured draft the user reviews before filing.
Tracked metric (see eval): how often the draft is accepted with only minor edits.

### `jira_client.py`
- `create_issue(*, subject, category, summary, contact, transcript, question_count,
  extra_labels=?) -> "KAN-12"` — the outbound write. Builds an Atlassian Document Format
  (ADF) description via `_adf()` (one paragraph per line, blank line = spacer), attaches
  labels (`sugbodoc-assistant`, the category, `triage-<label>`).
- `list_recent_open_issues()` / `list_resolved_issues()` — the **only** reads, both batch:
  the first for dedup, the second for the docs loop. `_search()` uses the v3 JQL endpoint
  with a fallback to the older `/search`.
- `jira_configured()`, `browse_url(key)`.

### `jira_dedup.py`
`find_duplicate(draft_subject, draft_summary) -> DuplicateMatch | None`. Pulls recent open
assistant-filed issues, embeds `subject+description` for each plus the draft, takes the
best cosine similarity; returns a match if it clears `DEDUP_SIMILARITY_THRESHOLD`.
Best-effort — any failure returns `None` rather than blocking a ticket. **This is the one
Jira read in the whole runtime, and it's per-submission, not per-message.**

### `chatlog.py`
- `ConversationRecord` — one dataclass per finished conversation: id, timestamps, outcome
  (`resolved` | `ticket_filed` | `linked_duplicate` | `abandoned`), question count, full
  messages, `failure_signals`, `grounding_checks`, `triage_label`, `thumbs`, `ticket_id`,
  `duplicate_of`. `.failed` and `.failed_user_questions()` are used by the analytics.
- `append(record)` writes one JSON line to `logs/chats.jsonl`; `load_all()` reads them
  back. `new_conversation_id()`, `now_iso()`.

### `bot.py` — the inference pipeline
`respond(chat, question) -> AnswerResult`. The single code path for producing an answer,
used by **both** the app and the eval harness so they measure the same thing:
1. `chat.send(question)` — the answer model, grounded in the docs.
2. `grounding.verify(question, draft)`.
3. If not supported → return the fixed refusal. Else return the draft.
`AnswerResult(text, draft, refused, grounding)`; `.log_entry()` produces the per-answer
record stored in the chat log. `fresh_chat()` = `llm.new_chat(knowledge.system_prompt())`.

### `engine.py` — the conversation state machine
UI-independent. `service.py` drives a `Conversation` through it; `app.py` implements the
same flow inline (it predates this module).
- `start(id?) -> Conversation` (greeting + a fresh `bot` chat)
- `ask(conv, text)` — appends turn, calls `bot.respond`, then routes to `feedback`,
  `offer_ticket` (on refusal or after N questions), else stays.
- `feedback(conv, helpful)` — 👍 → `resolved` + log; 👎 → failure capture + triage.
- `tell_me_more(conv)` — back to `chat`.
- `ticket_draft(conv)` — `ticketing.draft_ticket` + `jira_dedup.find_duplicate`.
- `submit_ticket(conv, email, subject, summary, category)` — `jira_client.create_issue` +
  log `ticket_filed`.
- `link_duplicate(conv)` / `log_abandoned(conv)`.
- `_log(conv, outcome)` — writes the `ConversationRecord`.

Stages: `chat → feedback → offer_ticket → done`.

---

## 4. The three ways to run it

### A. Streamlit demo — `app.py`
```
pip install -r requirements.txt
cp .env.example .env       # add GEMINI_API_KEY (+ JIRA_* to enable ticketing)
streamlit run app.py
#  or, with no key:   LLM_BACKEND=mock streamlit run app.py
```
Sidebar shows what it's grounded on, the Jira target, the models, live triage + failure
signals. Stage machine identical to `engine.py`; the ticket form is a modal
(`@st.dialog`); every conversation is logged on a terminal state.

### B. FastAPI backend — `service.py`  (the "ship it to a website" path)
```
pip install -r requirements-service.txt
uvicorn service:app --reload
#  http://127.0.0.1:8000        bundled demo widget (web/index.html)
#  http://127.0.0.1:8000/docs   OpenAPI explorer
```
Endpoints: `POST /chat`, `POST /feedback`, `POST /tell-me-more`, `GET /ticket/draft`,
`POST /ticket`, `POST /ticket/link-duplicate`, `DELETE /session/{id}`, `GET /healthz`.
Sessions are an in-memory dict (`SESSIONS`) — swap for Redis / a DB table keyed by
`conversation_id` for real deployment; the only non-JSON thing to persist is
`Conversation.chat.history` (a list). CORS is open for the demo — lock `allow_origins`.

> **Answering "do I need to rewrite this in TypeScript?"** — no. Streamlit is the only part
> that can't embed in an existing site; `service.py` gives you a JSON API your existing
> frontend calls, and the eval/analytics scripts stay in Python as offline jobs.

### C. Offline batch jobs (the maintenance side)
```
python seed_demo_log.py            # synthetic log so there's something to analyse
python analytics_kpis.py           # containment / refusal / repeat-question KPIs
python analytics_cluster.py        # failed questions → impact-ranked doc_gap_queue.json
python docs_loop.py                # top gaps + resolved Jira → doc_proposals/*.md
python eval_run.py                 # score the bot → eval_scorecard.md
```
All of these accept `--mock` (no API), `--offline` (cache only), `--no-cache`.

---

## 5. The evaluation harness — `eval_run.py`

This is the part that makes the project defensible: **you can't claim the bot is good
without measuring it, and this measures it.**

`eval_set.jsonl` — 90 cases, each `{id, question, expected_behavior: "answer"|"refuse",
expected_section, must_include: [...]}`. 29 are a dedicated **"must refuse" slice** —
questions that sound answerable but aren't in the docs (delete a patient, SMS reminders,
telehealth, insurance claims…). The hallucination guard is only as good as this slice.

Each case is scored three ways:
1. **Deterministic** — did it answer vs refuse as expected (`behavior_correct`)? are the
   `must_include` doc tokens present? did it mention the expected section?
2. **LLM-as-judge** (`judge()`, `JUDGE_MODEL`) — `correctness` and `groundedness`, 0–1,
   with a rubric. The harness **aborts** if >30% of judge calls fail (a broken judge model
   would otherwise produce an all-zeros scorecard that looks like a catastrophe).
3. **Aggregate** (`build_scorecard`) — per-slice metrics with **bootstrap 95% CIs**
   (`bootstrap_ci`), over-refusal rate, correct-refusal rate, and a per-case table.

Outputs `eval_scorecard.md` (commit this as your baseline) and `eval_scorecard.json`.

**Calibration:** `python eval_run.py --calibrate eval_labels_template.csv` — you hand-label
40–60 cases (1 = acceptable, 0 = not), and it prints raw agreement + **Cohen's κ**
(`cohens_kappa`) between you and the judge. A judge you haven't calibrated is a vibe, not a
measurement.

**Cheap modes:** `--no-judge` (deterministic checks only — good for a quick regression
gate), `--limit N`, `--mock`, `--offline`.

`eval_gen.py` grows the set: for each doc section it asks the model for a couple of
realistic questions + the tokens a correct answer must contain, writing candidates to
`eval_generated.jsonl` for you to review and merge.

---

## 6. Failure mining & the docs loop

### `analytics_cluster.py`
1. Pull every failed conversation from the log, take its first user question.
2. `llm.embed()` them.
3. `sklearn.cluster.HDBSCAN` on L2-normalised vectors (cosine-like). If it finds no
   density (few points / weak signal) it falls back to one group.
4. For each cluster: a model call labels it (`label`, `gap`, `suggested_sections`).
5. **Impact score** = `cluster_size × (avg_questions_before_giving_up /
   QUESTIONS_BEFORE_TICKET) × recency_weight`, where `recency_weight = exp(-days/30)`.
6. Write `logs/doc_gap_queue.json`, impact-ranked.

### `docs_loop.py`
Reads that queue + (optionally) `jira_client.list_resolved_issues()` — a resolved bug often
means a doc is now wrong. For the top-N clusters it feeds the related doc section(s) + the
actual failed transcripts to the model and asks for a concrete doc change (or a "this is a
product bug, keep it in Jira" verdict) plus an eval case to add first. Output:
`doc_proposals/<date>-NN-<slug>.md` for a human to review, edit, and merge — **then re-run
`eval_run.py` and only merge if the scorecard doesn't regress.**

### `analytics_kpis.py`
No model calls. Containment (resolved without a ticket), ticket-filed rate,
duplicate-linked rate, abandoned rate, thumbs-up rate, refusal rate, verification-pass
catch rate, repeat-question rate, triage mix, ticket categories.

---

## 7. Tests — `tests/`

`pip install -r requirements-dev.txt && pytest`. 40 tests, **fully offline** (the
`conftest.py` fixture forces the mock backend and points every path — cache, chat log — at
a `tmp_path`). Coverage:

| File | What it locks down |
|---|---|
| `test_knowledge.py` | section parsing, TOC exclusion, `find_section`, system prompt contents |
| `test_failure_capture.py` | every rule signal, fuzzy repeat detection, triage label validity |
| `test_chatlog.py` | JSONL round-trip, `.failed` / `.failed_user_questions()` |
| `test_jira_client.py` | ADF structure, blank-line spacers, description fields |
| `test_jira_dedup_and_kpis.py` | cosine properties, duplicate match, KPI run |
| `test_llm.py` | cache hit-once, offline raises on miss / serves warm, `Chat` history, embed determinism |
| `test_bot_and_grounding.py` | answer path, refusal path, verification short-circuit |
| `test_eval_run.py` | bootstrap CI bounds, Cohen's κ, `run_case`, scorecard slices |
| `test_service.py` | health, answer flow, refusal→ticket, 404s, validation (FastAPI `TestClient`) |

---

## 8. Design decisions (and the reasoning)

| Decision | Why |
|---|---|
| Full docs in the prompt, **no RAG** | ~8k tokens fit comfortably. Retrieval only adds a missed-chunk failure mode. Revisit at ~5–10× the doc size — the change is local to `knowledge.system_prompt()`. |
| **Separate verification pass** instead of trusting one call | A model is bad at self-policing "I don't know". A cheap independent check catches hallucinations; its threshold is tuned on the eval set. |
| **Rules** for failure detection, not a classifier | The refusal marker + a 👎 button catch most failures with zero ML. Train a model only once the logs show the rules missing failures. |
| Jira is **outbound-only**; dedup is the sole read | Reading tickets per turn adds latency, a sync pipeline, and stale-status risk for no benefit. Jira reaches the bot only as `Jira → docs → bot`. |
| Ticket type / category **suggested by the model, confirmed by a human** | Don't train a classifier for a field a person approves anyway; just track suggestion accuracy. |
| **Evaluation before features** | Every prompt or docs change is judged against a frozen scorecard with CIs. Without this the project is unfalsifiable. |
| A dedicated **"must refuse" eval slice** | The hallucination guard is only as good as its test set. |
| **Response cache + mock backend** | Free-tier quota is ~20 requests/day/model. The cache makes eval re-runs free; the mock lets the whole system (and the test suite) run with no key at all. |
| `engine.py` separate from `app.py` / `service.py` | The conversation logic is UI-independent, so the same flow backs both the Streamlit demo and the JSON API. |

Things **deliberately not built** (full table in `SugboDoc-Chatbot-Flowchart.md` §8): a
vector DB, a cross-encoder reranker, a sentiment classifier, an NLI entailment model for
grounding, fine-tuning, TextTiling for doc segmentation.

---

## 9. What each part demonstrates

- **Right-sizing the architecture** (`knowledge.py`, flowchart §0) — recognising the corpus
  fits in context and *not* reaching for RAG; knowing when a simpler tool wins.
- **Evaluation design** (`eval_run.py`) — a gold set with a refusal slice, LLM-as-judge
  with a rubric, judge/answer-model separation, **Cohen's κ calibration against human
  labels**, **bootstrap confidence intervals**, a frozen regression scorecard.
- **Grounding / hallucination control** (`grounding.py`) — a verification pass and a strict
  refusal contract, measured (over-refusal vs correct-refusal are both tracked).
- **Failure analytics** (`analytics_cluster.py`) — embedding + **HDBSCAN** density
  clustering of failed questions, cluster labelling, an **impact score**
  (frequency × stuckness × recency), coverage-gap ranking.
- **Generation-quality metrics** (`ticketing.py`, eval) — ticket-draft acceptance /
  edit-distance rather than vibes.
- **Cost engineering** (`llm.py`) — a request cache keyed by content hash, an offline mode,
  a mock backend, quota-aware retry that stops cleanly.
- **Production shape** (`service.py`, `engine.py`) — UI-independent state machine, a JSON
  API, session-store abstraction, an integration (`jira_client.py`) against a real REST API
  with ADF payloads and team-managed-project quirks handled.
- **Data cleaning** — the knowledge base was reconstructed from a raw ASR transcript +
  chapter timestamps, with mislabeled chapters corrected.

---

## 10. Known limitations / next steps

- **Quota** — the free Gemini tier caps daily requests per model; a full `eval_run.py` is
  ~180 calls. Use `--limit`, `--mock`, the cache, enable billing, or spread runs over days.
  A real scorecard has not been generated yet — do this first (`python eval_run.py`) and
  commit `eval_scorecard.md` as the baseline.
- **Clustering needs volume** — HDBSCAN is meaningful at a few hundred failed
  conversations, not the ~11 in the seeded demo (it currently collapses them to one group).
- **Sessions are in-memory** in `service.py` — fine for a demo, needs Redis/DB for real
  traffic.
- **No auth / rate limiting / PII redaction** on `service.py` yet — see the docstring.
- `app.py` could be refactored onto `engine.py` to remove the duplicated flow.
- The verification pass doubles per-turn latency and cost — worth A/B-ing a
  confidence-gated version (only verify when the answer model is unsure).

---

## 11. First-run checklist

```
pip install -r requirements-dev.txt
pytest                                   # 40 tests, offline, ~1s

cp .env.example .env                     # add GEMINI_API_KEY
python eval_run.py --limit 10            # sanity-check the real model
python eval_run.py                       # full scorecard  → commit eval_scorecard.md

streamlit run app.py                     # try the bot

# maintenance loop (offline-demoable):
python seed_demo_log.py
python analytics_kpis.py
python analytics_cluster.py
python docs_loop.py
```
