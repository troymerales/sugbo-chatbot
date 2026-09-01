# SugboDoc Support Assistant

A documentation-grounded support chatbot for **SugboDoc**, a clinic / practice-management
SaaS. It answers user questions strictly from the product docs, verifies its own answers
against those docs, refuses cleanly when it can't help, and turns the failures into a
docs-improvement loop (failure clustering → drafted doc changes → an eval gate → Jira).

Full walkthrough — every module and key function — is in **[`docs/PROJECT.md`](docs/PROJECT.md)**.
Design rationale and diagrams are in **[`docs/SugboDoc-Chatbot-Flowchart.md`](docs/SugboDoc-Chatbot-Flowchart.md)**.

## Project layout

```
config.py                 paths, model names, thresholds, feature toggles  (stays at root)
app.py                    Streamlit demo UI                                 (entry point)

core/        the library — inference pipeline + state machine
  llm.py            one interface to the model: generate / chat / embed + SQLite cache
  _gemini_backend.py / _mock_backend.py   real Gemini vs offline deterministic stand-in
  knowledge.py      docs → sections → system prompt
  retrieval.py      RAG mode: embedding-cosine section retrieval
  grounding.py      the verification pass
  bot.py            respond() — the single answer path (answer → verify → refuse-or-answer)
  engine.py         UI-independent conversation state machine
  failure_capture.py / ticketing.py / jira_client.py / jira_dedup.py / chatlog.py
  cli.py            shared --mock / --offline / --no-cache flags

api/         the FastAPI backend
  service.py        JSON API + serves web/index.html
  db.py             SQLAlchemy models + engine (conversations, chat_logs) — opt-in Postgres
  db_init.py        create / check / reset the schema      (python -m api.db_init)
  schema.sql        equivalent raw DDL

evaluation/  the regression gate
  eval_run.py        run the pipeline over eval_set.jsonl → eval_scorecard.md  (LLM judge, CIs)
  eval_gen.py        draft synthetic eval questions from each doc section
  eval_set.jsonl     90 graded cases (61 answerable + 29 must-refuse)

analytics/   the maintenance side (no per-request calls)
  analytics_kpis.py      containment / refusal / repeat-question KPIs
  analytics_cluster.py   failed questions → HDBSCAN → impact-ranked doc-gap queue
  docs_loop.py           top gaps + resolved Jira → drafted doc changes
  seed_demo_log.py       synthetic chat log for demoing the above

scripts/     operator utilities  (llm_cache.py, jira_check.py, jira_test_ticket.py)
web/         index.html — SugboDoc dashboard mockup + floating chat widget
docs/        PROJECT.md, the flowchart, the knowledge base
tests/       50 offline pytest tests (mock backend, tmp paths, throwaway SQLite)
```

Modules live in packages; run scripts with `python -m <package>.<module>` (they also work
as plain files, e.g. `python analytics/seed_demo_log.py`). `config.py` stays at the root so
`import config` resolves everywhere.

## Quickstart

```bash
pip install -r requirements-dev.txt
pytest                                   # 50 tests, fully offline (~2s)

cp .env.example .env                     # add GEMINI_API_KEY (+ JIRA_* for ticketing)
streamlit run app.py                     #  or:  LLM_BACKEND=mock streamlit run app.py
```

### FastAPI backend (embed the assistant in a site)

```bash
pip install -r requirements-service.txt
uvicorn api.service:app --reload         #  http://127.0.0.1:8000  → dashboard mockup + widget
#  optional — persist sessions + chat logs to PostgreSQL:
export DATABASE_URL=postgresql://user:pass@host:5432/db
python -m api.db_init
```

### Offline maintenance loop (needs no API key with `--mock`)

```bash
python -m analytics.seed_demo_log --reset
python -m analytics.analytics_kpis
python -m analytics.analytics_cluster --mock
python -m analytics.docs_loop --mock
python -m evaluation.eval_run --mock --no-judge
```

## Feature toggles (`config.py` / `.env`)

| Env | Default | Effect |
|---|---|---|
| `LLM_BACKEND` | `gemini` | `mock` = deterministic offline stand-in (no key / quota) |
| `USE_RAG` | `0` | `1` = inject only the top-`RAG_TOP_K` retrieved doc sections instead of the whole doc. The verification pass and eval judge still see the full docs, so both modes are drop-in. |
| `RAG_TOP_K` | `6` | sections retrieved per question in RAG mode |
| `DATABASE_URL` | *(unset)* | set → sessions + chat logs go to Postgres instead of memory + `logs/chats.jsonl` |
| `LLM_CACHE` / `LLM_OFFLINE` | `1` / `0` | response cache in `logs/llm_cache.sqlite`; offline = cache-only |
