# Cloud architecture

How the SugboDoc assistant runs in production, why each piece was chosen, and how
to operate it without spending money.

**Design principles**

- **Free tier only.** No service here needs a credit card. Where a free tier has
  limits, they're documented below along with what happens if you cross them.
- **Minimal.** One compute service, one database, one LLM API, one optional
  integration. No Kubernetes, no Terraform, no message queue, no object storage —
  none of it is needed at this scale, and each would be a thing to operate.
- **The app doesn't change to fit the cloud.** The same FastAPI process runs
  locally, in Docker, and on Render. Configuration is entirely through
  environment variables.

---

## Architecture

```
                         ┌─────────────┐
   Browser  ───────────▶ │  Render     │   HTTPS (Render-managed TLS, *.onrender.com)
   (widget: web/         │  Web Service│
    index.html, served   │             │   Docker container:
    by the API itself,   │  uvicorn ──▶ FastAPI  (api/service.py)
    same origin)         │             │   - serves the widget at  /
                         │             │   - JSON API at  /chat /feedback /ticket …
                         │             │   - /healthz (liveness) · /readyz (readiness)
                         └──┬───────┬───┘
                            │       │
              psycopg v3    │       │   HTTPS (google-genai SDK)
              (session      │       │
               pooler)      ▼       ▼
                 ┌──────────────┐  ┌──────────────────────┐   ┌──────────────────┐
                 │  Supabase    │  │  Gemini API          │   │  Atlassian Jira  │
                 │  PostgreSQL  │  │  generativelanguage  │   │  REST API        │
                 │              │  │  .googleapis.com     │   │  (outbound only, │
                 │ conversations│  │                      │   │   optional)      │
                 │ chat_logs    │  │  answer + verify     │   │  create issue    │
                 └──────────────┘  │  + embeddings        │   │  on user opt-in  │
                                   └──────────────────────┘   └──────────────────┘

   CI/CD:  git push main ─▶ GitHub Actions ─▶ [test] + [docker build] ─▶ [deploy]
                                                                          │
                                                    curl Render deploy hook (secret)
                                                                          ▼
                                                    Render pulls main, rebuilds, swaps revision

   Keepalive:  GitHub Actions cron (every 5 days) ─▶ GET /readyz  ─▶ keeps Supabase from pausing
   Uptime:     UptimeRobot (every 5 min)          ─▶ GET /healthz ─▶ uptime % + latency history
```

**Request path, in words.** A user opens `https://<app>.onrender.com/`. Render
routes it to the container; FastAPI returns `web/index.html`. The widget's
JavaScript calls the API at `location.origin` (same host — no CORS involved).
`POST /chat` → `engine.ask()` builds a prompt from the knowledge base, calls
Gemini for an answer, calls Gemini again to verify the answer is grounded, and
persists the conversation to Supabase. The reply goes back as JSON. If the user
later files a ticket, `POST /ticket` calls the Jira REST API once.

---

## Services

Each block answers: **what it does · why we need it · why this provider ·
free-tier limit · what happens if we exceed it · alternatives considered ·
the cloud concept it teaches.**

### 1. Compute / API hosting — Render (Web Service)

- **What.** Runs the Docker container (uvicorn → FastAPI). Terminates HTTPS,
  gives a stable `*.onrender.com` URL, streams logs, restarts the process if it
  crashes.
- **Why we need it.** The app is a long-lived HTTP server with in-process state
  (a connection pool, the LLM response cache, a lifespan startup hook). It needs
  a process that stays up — not a function that spins up per request.
- **Why Render.** Free tier needs **no credit card**. Native Docker builds,
  `render.yaml` blueprints, deploy hooks for CI/CD, built-in log streaming, and
  automatic TLS. The mental model (a container, env vars, a health check, a
  deploy) transfers directly to AWS App Runner / Fly.io / Cloud Run.
- **Free-tier limit.** 0.1 CPU, 512 MB RAM, 100 GB egress/month, 500 build
  minutes/month. **The instance sleeps after 15 minutes of no traffic**; the
  next request wakes it with a ~30–60 s cold start.
- **If exceeded.** Egress over 100 GB is billed (this is the main accidental-cost
  risk — see *Cost controls*). Build minutes over 500 just queue. RAM over
  512 MB → the process is OOM-killed and restarted.
- **Alternatives considered.** *Fly.io* and *Railway* — both now require a card.
  *Google Cloud Run* — the most "real cloud" and the best résumé line, but needs
  a GCP billing account (card on file). *Hugging Face Spaces* — genuinely free
  and good for ML demos, but its deploy/secret model is HF-specific and teaches
  less transferable cloud. *Koyeb* — closest free equivalent to Render; documented
  as the fallback if Render's free tier changes.
- **Concept learned.** Platform-as-a-Service compute: you hand over a container,
  the platform runs it. Also: cold starts, health checks, horizontal vs vertical
  limits, egress billing.

### 2. Managed database — Supabase (PostgreSQL)

- **What.** A hosted PostgreSQL instance holding two tables: `conversations`
  (live sessions, so a restart or a second worker loses nothing) and `chat_logs`
  (finished conversations — the analytics/eval feed).
- **Why we need it.** Without it, sessions live in a Python dict and die on every
  redeploy, and chat logs go to a file on the ephemeral container disk (also lost
  on redeploy). Anything that must survive a restart has to leave the container.
- **Why Supabase.** Free tier, **no card**, real PostgreSQL (not a proprietary
  clone), 500 MB is plenty for text conversations, and it gives you **two**
  projects so you can have separate dev and prod databases. The app was already
  wired for it (`api/db.py` handles the connection pooler and dropped-connection
  retries).
- **Free-tier limit.** 500 MB database, 5 GB egress/month, 2 projects.
  **A project pauses after 7 days with zero database queries.**
- **If exceeded.** Over 500 MB → writes start failing; you prune `chat_logs` or
  upgrade. Paused project → the app returns `/readyz` = 503 and falls back to
  in-memory sessions (chats still work, nothing persists) until you click
  *Resume* in the Supabase dashboard. The keepalive cron exists to prevent this.
- **Alternatives considered.** *Neon* (also free, no card, Postgres, scale-to-zero
  instead of a hard pause) — a fine swap; documented in `study/03`. *Render
  Postgres* — free for only 30 days then deleted, so unusable here. *SQLite on
  the container* — dies with the container.
- **Concept learned.** Managed databases: the provider runs the server, OS
  patching, backups, and failover; **you** still own schema design, migrations,
  indexes, connection pooling, credentials, and network access. See
  *"Where the abstraction ends"* in `study/03`.

### 3. LLM API — Google Gemini

- **What.** The model that answers questions, the second call that verifies the
  answer is grounded, and the embedding model used for RAG / ticket dedup /
  failure clustering.
- **Why we need it.** It's the actual intelligence in the product.
- **Why Gemini.** A genuinely free API tier from Google AI Studio (no card),
  generous enough for a portfolio demo, with a Python SDK (`google-genai`).
- **Free-tier limit.** Per-minute and per-day request caps that vary by model
  (roughly: a few requests/minute, a few hundred/day for the flash models).
- **If exceeded.** The SDK returns a 429; `core/llm.py` raises `QuotaError`; the
  API responds `503` and the widget shows "the assistant is busy, try again".
  Mitigations already in place: the SQLite response cache, the per-IP rate
  limiter, and `LLM_BACKEND=mock` as a hard fallback.
- **Alternatives considered.** *OpenAI / Anthropic* — no perpetual free tier.
  *Local Ollama* — free but needs a GPU/CPU budget the free compute tier doesn't
  have. Swapping providers is a one-file change in `core/llm.py`.
- **Concept learned.** Calling a third-party API as a hard dependency: rate
  limits, quota exhaustion, caching, graceful degradation, and keeping the
  credential out of the codebase.

### 4. External integration — Atlassian Jira (REST API)

- **What.** Creates a Jira issue when a user with an unresolved question opts in.
  **Outbound only** — the app never reads tickets during a chat.
- **Why we need it.** It's a product feature (turn a failed chat into tracked
  work), not infrastructure. It's entirely optional: unset the `JIRA_*` vars and
  `jira_client.jira_configured()` returns false and the ticket button disappears.
- **Free-tier limit.** Jira Cloud is free for up to 10 users; the REST API has
  generous rate limits well above this app's usage.
- **If exceeded.** A 429 from Jira → the ticket call fails and the user is asked
  to try later. No effect on chat.
- **Concept learned.** Integrating an external SaaS via API-token auth; treating
  an integration as optional and degradable.

### 5. CI/CD — GitHub Actions

- **What.** On every push/PR: run the test suite and build the Docker image. On a
  push to `main` that passes both: ping Render's deploy hook.
- **Why GitHub Actions.** The code is already on GitHub; Actions is **free and
  unlimited for public repositories**; the workflow file is readable YAML with no
  extra service to sign up for.
- **Free-tier limit.** Unlimited minutes for public repos. (Private repos: 2,000
  min/month.)
- **If exceeded.** N/A for a public repo.
- **Concept learned.** A deploy pipeline: what triggers it, where the build runs,
  how secrets are injected, and what a failed deploy does (see *CI/CD* below).

### 6. Monitoring — Render logs + UptimeRobot + optional Sentry

- **What.** Render captures stdout (structured request lines). UptimeRobot pings
  `/healthz` every 5 minutes for an uptime %/latency history and emails on an
  outage. Sentry (optional, off unless `SENTRY_DSN` is set) captures exception
  details with stack traces.
- **Why these.** All free, no card. Render logs come for free with the compute.
  UptimeRobot is the standard free uptime monitor. Sentry's free tier (5k
  errors/month) is enough to see real production errors without log-grepping.
- **Free-tier limits.** Render log retention is short (days) on the free plan.
  UptimeRobot: 50 monitors, 5-min interval. Sentry: 5k errors/month, 30-day
  retention.
- **If exceeded.** Render: old logs roll off — ship them elsewhere if you need
  history. Sentry: extra errors are dropped until the month resets.
- **Concept learned.** The three layers of "is it up?": liveness/readiness
  probes, black-box uptime polling, and error aggregation.

### Deliberately NOT used

| Not used | Why |
|---|---|
| Object storage (S3 / Supabase Storage) | The app has no file uploads. The knowledge base is one Markdown file, delivered as a Render Secret File. Adding a bucket would be a credential and a dependency for nothing. |
| Redis / a cache service | The only cache (LLM responses) is a local SQLite file and is fine to lose on redeploy. |
| A secrets manager (Vault / GCP SM) | Render's encrypted env vars + GitHub Actions secrets cover every secret here. A dedicated manager is worth it at multi-service / multi-team scale, not this. |
| Kubernetes / Terraform | One container and one database. `render.yaml` is the entire infra-as-code surface. |
| A CDN / custom domain | `*.onrender.com` with Render's TLS is enough for a portfolio. A custom domain costs money to register. |
| A separate frontend host (Vercel/Netlify) | The frontend is one static HTML file served by the API. Splitting it would add a deploy, a build, and CORS config for zero benefit. |

---

## Data: what lives where, and why

| Data | Location | Lifetime | Reasoning |
|---|---|---|---|
| Live sessions (`conversations` table) | Supabase Postgres | until the chat ends, then deleted | must survive a redeploy and be shared if there's ever >1 worker |
| Finished chats (`chat_logs` table) | Supabase Postgres | kept (append/upsert) | the eval + analytics feed; must be durable |
| LLM response cache (`logs/llm_cache.sqlite`) | container filesystem | **ephemeral** — gone on every redeploy | pure speed/cost optimization; correctness doesn't depend on it, so persisting it isn't worth a volume |
| Embeddings / RAG vectors | in-process memory | recomputed on each boot | the knowledge base is ~8k tokens; embedding it takes one API call. No vector database needed at this size |
| Knowledge base (`docs/SugboDoc-Documentation.md`) | Render **Secret File**, mounted at that path | for the life of the service | it's private product documentation (git-ignored). If absent, the app falls back to the committed `docs/SugboDoc-Documentation.sample.md` excerpt |
| Eval set (`evaluation/eval_set.jsonl`), sample KB | git | versioned with the code | test fixtures, no secrets |
| `doc_proposals/`, `logs/chats.csv` | local machine only (git-ignored) | as long as you keep them | artifacts of batch jobs an operator runs on a laptop, not the server |

The rule: **durable + shared → Postgres. Rebuildable → ephemeral. Private but
static → Secret File. Test data → git.**

---

## Local development

Two ways, both offline-capable.

### A. Plain Python (fastest inner loop)

```bash
pip install -r requirements-dev.txt -r requirements-service.txt
cp .env.example .env                       # fill in GEMINI_API_KEY (JIRA_* optional)
uvicorn api.service:app --reload           # http://127.0.0.1:8000
```

No `DATABASE_URL` → sessions in memory, chat logs to `logs/chats.jsonl`. Add a
`DATABASE_URL` (local Postgres or a Supabase **dev** project) to exercise the
database path.

### B. Docker Compose (matches production)

```bash
docker compose up --build                  # API + a local PostgreSQL 16
# http://localhost:8000
docker compose down -v                     # stop and wipe the local DB volume
```

This runs the **same image** Render runs, against a real Postgres, with
`LLM_BACKEND=mock` by default (no API key needed). This is dev/prod parity — the
thing that catches "works on my machine" bugs.

### Tests

```bash
pytest                                     # 73 tests, fully offline, ~2s, no keys
```

The suite forces the mock LLM backend, throwaway paths, and a throwaway SQLite
DB (`tests/conftest.py`). It never touches the real Gemini, Supabase, or Jira.

---

## Cloud deployment

Full click-path with troubleshooting: **`study/RUNBOOK.md`**. Summary:

1. **Database.** Create a Supabase project (region near your users). Copy the
   **Session pooler** connection string (Project Settings → Database → Connection
   string → *Session pooler*), which looks like
   `postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres`.
   *Not* the direct connection — that host is IPv6-only and Render can't reach it.
2. **Service.** Render → New → Blueprint → this repo (or New → Web Service →
   Docker). Render reads `render.yaml` and prompts for the `sync: false` values:
   paste `GEMINI_API_KEY`, `DATABASE_URL` (the string from step 1), and the
   `JIRA_*` vars if you want ticketing.
3. **Knowledge base (optional).** Service → Environment → Secret Files → add
   `docs/SugboDoc-Documentation.md` with the full document. Skip this and the
   demo runs on the committed sample excerpt.
4. **Schema.** The app runs `db.init_db()` (idempotent `CREATE TABLE IF NOT
   EXISTS`) on startup, so the tables appear on first boot. Or run
   `python -m api.db_init` locally against the same `DATABASE_URL`.
5. **CI/CD wiring.** Render service → Settings → Deploy Hook → copy the URL.
   GitHub repo → Settings → Secrets and variables → Actions → **Secret**
   `RENDER_DEPLOY_HOOK_URL` = that URL. Add a **Variable** `PROD_URL` =
   `https://<app>.onrender.com`.
6. **Uptime.** UptimeRobot → add an HTTP(s) monitor on
   `https://<app>.onrender.com/healthz`, 5-minute interval.
7. **Verify.** `curl https://<app>.onrender.com/healthz` → `200`. Open `/` in a
   browser, send a chat message. Check Render → Logs for the request line.

Deploys after that: push to `main` → Actions runs `test` + `docker-build` → on
green, `deploy` pings the hook → Render rebuilds from the Dockerfile and swaps in
the new revision (zero-downtime; the old revision serves until the new one passes
its health check).

---

## Environment variables

Every variable, its default, and whether it's a secret is in **`.env.example`**.
Never commit real values — `.env` is git-ignored; production values live in the
Render dashboard.

| Variable | Secret? | Where it's set in prod | Purpose |
|---|---|---|---|
| `GEMINI_API_KEY` | **yes** | Render env var | Gemini auth |
| `DATABASE_URL` | **yes** (has the DB password) | Render env var | Supabase session-pooler connection string |
| `JIRA_BASE_URL` / `JIRA_EMAIL` / `JIRA_API_TOKEN` / `JIRA_PROJECT_KEY` | token is a secret | Render env vars | Jira ticketing (optional) |
| `SENTRY_DSN` | semi (write-only key) | Render env var | error tracking (optional; unset = off) |
| `ENV` | no | `render.yaml` (`prod`) | environment tag in logs / `/healthz` |
| `LOG_LEVEL` | no | `render.yaml` (`INFO`) | backend log verbosity |
| `RATE_LIMIT_PER_MIN` | no | `render.yaml` (`30`) | per-IP request cap; 0 disables |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | no | `render.yaml` (`5` / `2`) | SQLAlchemy pool ceiling |
| `CORS_ORIGINS` | no | unset | only needed if embedding the widget on another domain |
| `PORT` | no | **injected by Render** | the port uvicorn binds; never set it manually |
| `USE_RAG` / `RAG_TOP_K` | no | unset (full-context default) | retrieval mode |

---

## CI/CD

Defined in `.github/workflows/ci.yml`. Three jobs:

| Job | Runs on | Does | Needs secrets? |
|---|---|---|---|
| `test` | every push + PR | `compileall` + `pytest` (offline suite) | no |
| `docker-build` | every push + PR | `docker build` (build only, nothing pushed) | no |
| `deploy` | push to `main` only, after both above pass | `curl` the Render deploy hook | `RENDER_DEPLOY_HOOK_URL` |

- **What triggers a deploy:** a push to `main` where `test` **and** `docker-build`
  are green. A PR never deploys.
- **Where the build happens:** the *image* build in CI is only a check. The
  **real** build runs on Render's servers from the `Dockerfile` when the hook is
  pinged. Nothing is pushed to a registry.
- **How secrets reach the deploy:** the hook URL is a GitHub Actions *secret*,
  injected as an env var for that one step. Render already holds the app's
  secrets (Gemini key, DB URL) as its own env vars — GitHub never sees those.
- **If deploy fails:** the `deploy` job goes red and GitHub emails you. The
  currently-running Render revision keeps serving traffic. If the *hook fires*
  but the *Render build* fails, Render keeps the old revision live and shows the
  build error in its dashboard.

A second workflow, `.github/workflows/keepalive.yml`, runs on a cron every 5 days
and `curl`s `PROD_URL/readyz` to keep the Supabase project from pausing.

---

## Monitoring

| Question | Where to look |
|---|---|
| Is the process up? | `GET /healthz` → `200`; UptimeRobot dashboard |
| Can it reach the database? | `GET /readyz` → `200` (ready) or `503` (`database: down`) |
| What requests is it serving? | Render → your service → **Logs** (one `METHOD /path -> status (Nms)` line per request) |
| Why did a request 500? | Render logs show the traceback (`unhandled error on …`). If `SENTRY_DSN` is set, Sentry has it with full context |
| Is Gemini rate-limiting us? | Render logs: `QuotaError` / `429`; the widget shows a busy message |
| Startup problems? | Render logs: the `starting SugboDoc API (env=… db=… rag=…)` line and anything before the first request |

---

## Cost controls

The whole stack is designed to be **$0**, but "free tier" is not "impossible to
be charged". Guardrails:

- **No card on file anywhere** = the hard ceiling. Render, Supabase, GitHub,
  UptimeRobot, Gemini (AI Studio), Sentry — none has your card. A service that
  can't charge you, won't.
- **Smallest instance** (`plan: free`, one uvicorn worker).
- **Sleep is on** — the Render instance idles to nothing after 15 min. We do
  *not* keep it awake 24/7 (the keepalive cron only pings every 5 days, and only
  to keep Supabase alive).
- **Rate limiter** caps per-IP requests, which caps Gemini calls.
- **Response cache** avoids repeat Gemini calls.
- **No always-on batch jobs.** The eval harness and analytics run on your
  laptop, on demand, with `--mock` by default.

### What could cause an unexpected charge

| Risk | Mitigation |
|---|---|
| **Render egress > 100 GB/month** (the realistic one — a scraper, a hotlinked asset, a load test) | UptimeRobot alerts on traffic spikes; check Render's Metrics tab; the rate limiter slows abusers |
| Adding a card to Render/GCP "just to try something" then leaving a paid resource running | Don't. If you must, set a billing budget alert first |
| Supabase database growing past 500 MB | `chat_logs` is text-only and small; prune old rows if it ever matters |
| Gemini billing enabled on the Google Cloud project behind the AI Studio key | Keep using an **AI Studio** key (free tier), not a billing-enabled Cloud project key |

### How to shut everything down

1. **Render** → your service → Settings → **Suspend** (keeps config, stops the
   instance and billing exposure) or **Delete**.
2. **Supabase** → Project Settings → General → **Pause project** (data kept) or
   **Delete project**.
3. **GitHub** → Actions → disable the `CI` and `Keepalive` workflows (or just
   delete `RENDER_DEPLOY_HOOK_URL` so deploys no-op).
4. **UptimeRobot** → pause or delete the monitor.
5. **Gemini / Jira** → revoke the API keys (`aistudio.google.com` /
   `id.atlassian.com/manage-profile/security/api-tokens`).

Nothing here bills after step 1–2, but revoking keys (step 5) is the clean
finish — a leaked key is the only thing that can cost money once the compute is
off.

---

## Security

Portfolio-grade, not enterprise. What's in place:

- **HTTPS everywhere.** Render terminates TLS on `*.onrender.com`; all outbound
  calls (Gemini, Supabase, Jira) are HTTPS.
- **No secrets in git.** `.env` and the private KB are git-ignored; a `git
  ls-files` audit is part of the release checklist. Prod secrets live only in
  Render's encrypted env store and GitHub Actions secrets.
- **Least privilege.** The container runs as a non-root user. The Supabase
  connection uses the `postgres` role scoped to one project (not a
  cross-project/admin credential). The Jira token is a personal API token, not an
  OAuth app with broad scopes.
- **Database is not publicly exposed as "open".** Access requires the
  password-bearing connection string; it's never in the frontend, a URL, or a
  log line.
- **CORS is closed by default** (`allow_origins=[]`). The widget is same-origin.
- **Input validation.** All request bodies are Pydantic models; the ticket
  endpoint validates required fields; the date field is parsed, not trusted.
- **Rate limiting.** Per-IP, in-process — enough to blunt casual abuse and
  protect the Gemini quota. Not a DDoS defense (that would need a CDN/WAF).
- **Safe error messages.** Unhandled exceptions return `{"detail": "internal
  error"}` — the traceback goes to the logs, never to the client.

Known gaps (acceptable for this project, listed so they're explicit): no
end-user authentication (the chat is public by design), the rate limiter doesn't
survive a redeploy or coordinate across instances, and there's no WAF.

---

## See also

- `docs/PROJECT.md` — the application walkthrough (every module).
- `docs/SugboDoc-Chatbot-Flowchart.md` — the ML/product design rationale.
- `study/` (local only) — the learning notes and the `cloud_lab.ipynb` hands-on lab.
