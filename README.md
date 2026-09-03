# SugboDoc Support Assistant

<!-- update OWNER/REPO once pushed -->
[![CI](https://github.com/OWNER/REPO/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/ci.yml)

A documentation-grounded support chatbot for **SugboDoc**, a clinic / practice-management
SaaS. It answers user questions strictly from the product docs, verifies its own answers
against those docs, refuses cleanly when it can't help, and turns the failures into a
docs-improvement loop (failure clustering → drafted doc changes → an eval gate → Jira).

Full walkthrough — every module and key function — is in **[`docs/PROJECT.md`](docs/PROJECT.md)**.
Design rationale and diagrams are in **[`docs/SugboDoc-Chatbot-Flowchart.md`](docs/SugboDoc-Chatbot-Flowchart.md)**.
Cloud architecture, deployment, and cost controls are in **[`docs/architecture.md`](docs/architecture.md)**.

> **Two front ends, one library.** `streamlit run streamlit_app.py` is the pure-Streamlit
> app — a floating assistant widget, no server, deployable to Streamlit Community Cloud.
> `uvicorn api.service:app` is the original FastAPI backend + browser widget (Docker / Render).
> Both call the same `core/` pipeline. Folding the widget into the umbrella "SugboDoc"
> multipage app is documented in **[`MERGE.md`](MERGE.md)**.

> **Knowledge base.** The repo ships a trimmed public excerpt at
> `docs/SugboDoc-Documentation.sample.md` so everything runs out of the box. Drop the full
> document at `docs/SugboDoc-Documentation.md` (git-ignored) to use it instead —
> `config.DOCS_PATH` picks it up automatically.

## Project layout

```
config.py                 paths, model names, thresholds, feature toggles  (stays at root)
streamlit_app.py          pure-Streamlit app: dashboard backdrop + floating assistant  (entry point)
app.py                    older full-page Streamlit demo UI                 (still works, local only)

assistant/   the Streamlit layer — the ONLY place `import streamlit` appears
  widget.py        render_floating_assistant() — the shared floating widget
  session.py       the widget's conversation state machine (Streamlit sibling of core/engine.py)
  ticket_dialog.py the support-ticket form, as an @st.dialog
  bootstrap.py     st.secrets -> os.environ, so core/ stays Streamlit-free (MERGE SEAM #1)
  styles.py        the widget CSS (pins it bottom-right)

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
web/         index.html — SugboDoc dashboard mockup + the old JS widget (FastAPI backend only)
docs/        PROJECT.md, the flowchart, architecture.md, the knowledge base (sample excerpt)
.streamlit/  config.toml (theme) + secrets.toml.example
MERGE.md     how the widget folds into the umbrella "SugboDoc" multipage app
tests/       83 offline pytest tests (mock backend, tmp paths, throwaway SQLite, AppTest)

Dockerfile            container image (FastAPI backend + widget)   — Render builds this
docker-compose.yml    local dev: the image + a throwaway PostgreSQL
render.yaml            Render Blueprint (infra as code)
.github/workflows/     ci.yml (test + docker build + deploy), keepalive.yml (cron)
```

Modules live in packages; run scripts with `python -m <package>.<module>` (they also work
as plain files, e.g. `python analytics/seed_demo_log.py`). `config.py` stays at the root so
`import config` resolves everywhere.

## Quickstart

```bash
pip install -r requirements.txt          # Streamlit runtime
pip install -r requirements-dev.txt      # + pytest / httpx for the test-suite
pytest                                   # 83 tests, fully offline (~4s) — no keys needed

cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # add GEMINI_API_KEY (+ JIRA_*, DATABASE_URL)
streamlit run streamlit_app.py           #  or:  LLM_BACKEND=mock streamlit run streamlit_app.py
```

The assistant is the floating **💬 Support** button, bottom-right. It answers from
the product docs, streams the reply, runs an independent verification pass, and
turns a stuck chat into a Jira ticket. State lives in `st.session_state` — no server.

### Deploy to Streamlit Community Cloud

Point a new app at `streamlit_app.py`, paste the contents of
`.streamlit/secrets.toml` into **App → Settings → Secrets**, deploy. Free tier,
no credit card. Set `DATABASE_URL` (Supabase Session-pooler string) so chat logs
survive a reboot — without it they go to an ephemeral file. Run
`python -m api.db_init` once against that URL to create the tables.

### FastAPI backend (the original — embed the assistant in a site)

```bash
pip install -r requirements-service.txt
uvicorn api.service:app --reload         #  http://127.0.0.1:8000  → dashboard mockup + widget
#  optional — persist sessions + chat logs to PostgreSQL:
export DATABASE_URL=postgresql://user:pass@host:5432/db
python -m api.db_init
```

Or run it the way production does — the container plus a real PostgreSQL:

```bash
docker compose up --build                #  http://localhost:8000  (LLM_BACKEND=mock by default)
docker compose down -v                    #  stop + wipe the local DB
```

### Cloud deployment (FastAPI path)

Deployed as a single Docker **Web Service on Render** (free tier, no credit card),
backed by **Supabase PostgreSQL** (free), with **GitHub Actions** running
tests → docker build → deploy-on-green. The browser widget is served by the API
itself, so there's no separate frontend host. Full design + step-by-step:
**[`docs/architecture.md`](docs/architecture.md)**.

```
Browser → Render (FastAPI + widget) → Supabase Postgres
                                    → Gemini API
                                    → Jira REST (outbound, optional)
```

### Offline maintenance loop (needs no API key with `--mock`)

```bash
python -m analytics.seed_demo_log --reset
python -m analytics.analytics_kpis
python -m analytics.analytics_cluster --mock
python -m analytics.docs_loop --mock
python -m evaluation.eval_run --mock --no-judge
```

## Feature toggles (`config.py` / `.env` / `.streamlit/secrets.toml`)

| Env | Default | Effect |
|---|---|---|
| `LLM_BACKEND` | `gemini` | `mock` = deterministic offline stand-in (no key / quota) |
| `VERIFY_ANSWERS` | `1` | `0` = skip the independent verification pass (1 Gemini call/question instead of 2, faster, no hallucination catch) |
| `USE_RAG` | `0` | `1` = inject only the top-`RAG_TOP_K` retrieved doc sections instead of the whole doc. The verification pass and eval judge still see the full docs, so both modes are drop-in. |
| `RAG_TOP_K` | `6` | sections retrieved per question in RAG mode |
| `DATABASE_URL` | *(unset)* | set → sessions + chat logs go to Postgres instead of memory + `logs/chats.jsonl` |
| `LLM_CACHE` / `LLM_OFFLINE` | `1` / `0` | response cache in `logs/llm_cache.sqlite`; offline = cache-only |
| `ENV` / `LOG_LEVEL` | `dev` / `INFO` | environment tag + backend log verbosity |
| `RATE_LIMIT_PER_MIN` | `30` | per-IP request cap (protects the Gemini free-tier quota); `0` disables |
| `CORS_ORIGINS` | *(unset)* | only needed to embed the widget on another domain; never `*` |
| `SENTRY_DSN` | *(unset)* | set → error tracking via Sentry; unset → `sentry-sdk` not even imported |

Deployment-related variables are documented in full in
[`docs/architecture.md`](docs/architecture.md) and `.env.example`.
