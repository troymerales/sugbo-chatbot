# SugboDoc Support Assistant — Project Guide

A documentation-grounded support chatbot for **SugboDoc**, a clinic / practice-management
SaaS. The bot answers "how do I…" questions **only** from the product documentation, and
when it can't, it captures that failure and turns it into a Jira ticket and/or a
documentation-improvement task — so the knowledge base gets better over time.

This file is the walkthrough: what each piece does, why it's built that way, and how to run
it. The higher-level design rationale (with diagrams and the "techniques deliberately not
used" table) is in **`docs/SugboDoc-Chatbot-Flowchart.md`**.

---

## 1. The idea in one paragraph

The product docs are small (~8k tokens). So by default, instead of a vector database and
retrieval (RAG), the **whole document goes into the prompt every turn**. (A `USE_RAG=1`
toggle switches the *answer* prompt to embedding-cosine section retrieval — `core/retrieval.py`
— while the verification pass and eval judge keep seeing the full docs, so the two modes
are interchangeable.) A second, independent model call then checks the answer against the
docs — a *verification pass* — and if any claim isn't supported, the answer is replaced
with a fixed refusal. Every conversation is logged.
Failed conversations feed two loops: an **outbound Jira ticket** (created only when the user
asks) and an offline **docs-maintenance loop** that clusters failures, drafts documentation
fixes, and re-scores them against an evaluation harness before they ship. Jira is *never*
read during a chat — the only path from Jira back to the bot is `Jira → docs → bot`.

---

## 2. Repository layout

```
chatbot/
├── README.md                     one-page overview + quickstart
├── MERGE.md                      folding the widget into the umbrella "SugboDoc" app
├── config.py                     paths, model names, thresholds, feature toggles (stays at root)
├── streamlit_app.py              pure-Streamlit app: dashboard backdrop + floating assistant (entry point)
├── app.py                        older full-page Streamlit demo (still works, local only)
│
├── assistant/                    the Streamlit layer — the only place `import streamlit` appears
│   ├── widget.py                 render_floating_assistant() — the shared floating widget
│   ├── session.py                the widget's state machine (Streamlit sibling of core/engine.py)
│   ├── ticket_dialog.py          the support-ticket form, as an @st.dialog
│   ├── bootstrap.py              st.secrets → os.environ (MERGE SEAM #1)
│   └── styles.py                 the widget CSS (pins it bottom-right)
│
├── core/                         the library
│   ├── llm.py                    one interface to a model: generate / chat / embed + cache
│   ├── _gemini_backend.py        real Gemini calls (only llm.py imports it)
│   ├── _mock_backend.py          offline deterministic stand-in (no API key / quota)
│   ├── knowledge.py              load docs → sections → system prompt
│   ├── retrieval.py              RAG mode: embedding-cosine section retrieval  ← NEW
│   ├── grounding.py              the verification pass
│   ├── failure_capture.py        rule-based failure signals (no model call)
│   ├── ticketing.py              draft a ticket from a conversation
│   ├── jira_client.py            create Jira issues (outbound) + two batch reads
│   ├── jira_dedup.py             embed a draft vs open tickets → duplicate check
│   ├── chatlog.py                append / load finished conversations (JSONL or Postgres) + CSV mirror
│   ├── bot.py                    respond() — the inference pipeline (answer + verify)
│   ├── engine.py                 the conversation state machine (UI-independent) + serialize()
│   └── cli.py                    shared --mock / --offline / --no-cache flags
│
├── api/                          the FastAPI backend
│   ├── service.py                JSON API + serves web/index.html
│   ├── db.py                     SQLAlchemy engine + models (conversations, chat_logs) — opt-in
│   ├── db_init.py                create / check / reset the DB schema
│   └── schema.sql                equivalent raw DDL for psql users
│
├── evaluation/
│   ├── eval_set.jsonl            90 graded test cases (61 answerable + 29 must-refuse)
│   ├── eval_run.py               run the pipeline over eval_set → eval_scorecard.md
│   ├── eval_gen.py               draft synthetic eval questions from each doc section
│   └── eval_labels_template.csv  for judge-vs-human calibration (Cohen's κ)
│
├── analytics/
│   ├── analytics_kpis.py         KPIs from the chat log (no model calls)
│   ├── analytics_cluster.py      cluster failed questions → logs/doc_gap_queue.json
│   ├── docs_loop.py              queue + resolved Jira → drafted doc changes → doc_proposals/
│   └── seed_demo_log.py          synthetic chat log so the analytics scripts are demoable
│
├── scripts/                      llm_cache.py · jira_check.py · jira_test_ticket.py
├── web/index.html                SugboDoc dashboard mockup + the old JS widget (FastAPI backend only)
├── .streamlit/                   config.toml (theme) + secrets.toml.example
├── docs/                         PROJECT.md · SugboDoc-Chatbot-Flowchart.md · the knowledge base
└── tests/                        pytest suite (runs fully offline, 83 tests; AppTest for the widget)
```

Each subdirectory is a package. Modules import each other as `from core import bot`,
`from api import db`, etc.; `config.py` stays at the root so `import config` resolves
everywhere. Run scripts with `python -m evaluation.eval_run` (they also work as plain
files: `python evaluation/eval_run.py`).

---

## 3. Core library — file by file

### `config.py`
Single place that loads `.env` (once, **by absolute path** — `ROOT / ".env"` — so
`uvicorn api.service:app` picks it up no matter which directory it's launched from) and
holds every tunable. Nothing else calls `load_dotenv`.

Key names:
- `ANSWER_MODEL`, `UTILITY_MODEL`, `JUDGE_MODEL`, `EMBED_MODEL` — all overridable via env.
  The judge **must differ** from the answer model or the eval score is inflated.
- `QUESTIONS_BEFORE_TICKET` (default 3) — after this many questions without a 👍, the bot
  proactively offers a ticket.
- `DEDUP_SIMILARITY_THRESHOLD` (default 0.82) — cosine similarity above which a drafted
  ticket is treated as a duplicate.
- `REFUSAL_MARKER` — the exact sentence the bot must emit when it can't answer.
- `VERIFY_ANSWERS` (default 1) — run the verification pass. `0` halves the model calls
  per question at the cost of the grounding check.
- `LLM_BACKEND` (`gemini` | `mock`), `LLM_CACHE` (bool), `LLM_OFFLINE` (bool) — read
  **live on every call**, so scripts flip them at runtime via `cli.py`.
- On a read-only host, `LOG_DIR` (and the cache / JSONL paths under it) fall back to a
  temp dir so `import config` can't fail.

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
- `generate()` inspects the *system prompt* to tell which call it is (verify / judge /
  cluster-label / docs-loop — plus legacy triage/draft branches) and returns well-formed
  JSON for each; for a plain user question it does naive word-overlap retrieval over the
  doc sections (`_retrieve`) and returns that section's steps, or the refusal if nothing
  scores well.
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
- `system_prompt(query=None)` — assembles `PERSONA` (the answer rules + the exact refusal
  sentence) + the docs between fences. Default: the **full docs**. With `config.USE_RAG` on
  and a `query` given: only the top-`RAG_TOP_K` retrieved sections. **This is where the
  retrieval decision lives.**

### `retrieval.py` — RAG mode
Only used when `config.USE_RAG` is true. `top_sections(query, k)` / `rank_sections(query)`
embed every content section once (`llm.embed`, itself cached) and rank them against the
query embedding by plain cosine — no extra dependency; ChromaDB/FAISS would be the next
step past a few hundred sections. `bot.respond()` swaps the retrieved prompt into
`chat.system` per turn; `grounding.verify()` and the eval judge still read the full docs,
so full-context and RAG runs are directly comparable (the eval scorecard records which).

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
  `FailureSignals.as_list()` gives the short names above; `.reasons` gives the matching
  human-readable strings ("user re-asked the same question"). The engine keeps both on the
  conversation (`failure_signals` / `failure_reasons`) and logs both — `.reasons` is what you
  read during failure triage; the CSV mirror pipe-joins it into a `failure_reasons` column.
  *Rules first, model later:* a dissatisfaction classifier is only worth training once the
  logs show these rules missing failures.
  *(An LLM `triage()` call — docs-gap / product-bug / out-of-scope — used to run here; it
  was removed to cut per-conversation model cost.)*

### `ticketing.py` — no model calls in the runtime
- `default_draft(transcript) -> TicketDraft` — the ticket the user reviews, built with **no
  model call**: subject seeds from the user's first question, summary is left blank.
- `as_iso_date(text)` / `urgency_for_date(iso, today=?)` — validate the date picker's value
  and derive an urgency (`high` ≤ 3 days out, `medium` ≤ 14, else `low`).
- `draft_ticket()` (the LLM-drafted version) is kept in the file for reference but is no
  longer wired in.

### `jira_client.py`
- `create_issue(*, subject, category, summary, contact, transcript, question_count,
  submitter_name=?, due_date=?, urgency=?, extra_labels=?) -> "KAN-12"` — the outbound
  write. Payload fields: `project`, `summary`, `description` (ADF, carries *Submitter*,
  *Submitter email*, *Target date*, *Requested urgency*), `issuetype`, `labels`
  (`sugbodoc-assistant`, category, `urgency-<level>`); `duedate` (only when `due_date` is
  `YYYY-MM-DD`).
  - **`reporter`** (system field) is set only when `resolve_account_id(email)` finds a real
    Jira user. A chat submitter's *name* deliberately does **not** feed it (Jira needs a
    strict accountId) — so for external submitters the reporter stays the API-token user,
    which is the signal that the ticket came from the assistant.
  - The submitter's name / email / subject go to plain-text **custom columns** —
    `Submitter`, `Submitter Email`, `Subject` (names via `JIRA_SUBMITTER_FIELD` /
    `JIRA_SUBMITTER_EMAIL_FIELD` / `JIRA_SUBJECT_FIELD` env; resolved to `customfield_XXXXX`
    ids at runtime by `_field_id()`; skipped if the project doesn't have them).
  - **Graceful validation:** a 400 naming `reporter` / `duedate` / `priority` / any
    `customfield_*` drops those keys and retries once so the ticket still files.
- `resolve_account_id(name_or_email)` — `GET /rest/api/3/user/search` (matches display
  name *and* email), best-effort, cached. `None` for a non-Jira user is the normal case.
- `_field_id(name)` — one cached `GET /rest/api/3/field`, returns the field id for a
  field named `name` (prefers a custom field).
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
- `ConversationRecord` — one dataclass per conversation: id, timestamps, outcome
  (`unresolved` | `resolved` | `ticket_filed` | `linked_duplicate` | `abandoned`), question
  count, full messages, `failure_signals` (+ `failure_reasons`, the human-readable "why"),
  `grounding_checks`, `thumbs`, `ticket_id`, `ticket_category`,
  `needed_by` / `due_date`, `duplicate_of` (`triage_label` / `triage_confidence` are still
  fields but no longer populated — triage was removed). `.failed` and
  `.failed_user_questions()` are used by the analytics.
- **`append(record)` is an upsert keyed by `conversation_id`.** A chat is logged the moment
  it goes wrong — the engine writes an `unresolved` row on any failure (thumbs-down,
  refusal, stuck) — and the *same* row is updated in place if it later reaches a ticket /
  duplicate-link / resolution. So a thumbs-down that never becomes a ticket is still
  captured, and there's still one record per conversation. `load_all()` dedupes on
  `conversation_id` (newest wins) as a backstop.
- Storage depends on `config.DATABASE_URL`: unset → `logs/chats.jsonl` (rewritten on each
  upsert); set → one row in the `chat_logs` table via `db.upsert_chat_log()`. Same API
  either way, so the analytics scripts don't care.
- `reset_store()` wipes the log (file unlink or `DELETE FROM chat_logs`, plus the CSV) —
  used by `seed_demo_log.py --reset` and the tests. `new_conversation_id()`, `now_iso()`.
- **Local CSV mirror:** every `append()` rewrites `logs/chats.csv`
  (`config.CHAT_LOG_CSV_PATH`) from the primary store — one row per conversation, ~18
  columns (`outcome`, `failed`, `failure_signals`, `failure_reasons`, `thumbs`,
  `ticket_id`, `needed_by`, `due_date`, `first_user_question`, `last_assistant_message`, …).
  Nothing reads it back; it's for eyeballing in a spreadsheet. `python -m core.chatlog`
  rebuilds it explicitly (`export_csv()`) — handy after backfilling straight to Supabase.

### `db.py` — PostgreSQL persistence (opt-in)
Only active when `DATABASE_URL` is set (`postgresql+psycopg://user:pass@host:5432/sugbodoc`).
- `enabled()` — `bool(config.DATABASE_URL)`; every caller branches on this.
- Models: **`ConversationRow`** (`conversations` — one live session: `stage`, `started_at`,
  `question_count`, `state` JSONB = the serialised `engine.Conversation`, `updated_at`);
  **`ChatLogRow`** (`chat_logs` — one row per conversation, keyed by `conversation_id`:
  promoted `conversation_id` / `outcome` / timestamps for querying + the full `record`
  JSONB). JSONB on Postgres, plain JSON on SQLite (the test-suite).
- `_get_engine()` (adds `pool_pre_ping` + `pool_recycle=1800` for managed poolers like
  Supabase Supavisor, plus explicit `pool_size` / `max_overflow` from
  `config.DB_POOL_SIZE`/`DB_MAX_OVERFLOW` so the pool stays under Supabase's free-tier
  connection cap) / `session()` (transactional context manager) / `_run(op)` (runs
  `op` in a transaction, **retries once** on `OperationalError`/`DBAPIError` — a dropped
  idle pooler connection — before giving up loudly) / `reset()` / `init_db()` / `drop_db()`.
- `save_conversation()` / `load_conversation()` / `delete_conversation()` / `count_conversations()`
  / `delete_stale_conversations(hours)` (startup sweep of abandoned live rows).
- `ping()` — a `SELECT 1` that never raises (returns `False` on any error); backs the
  `/readyz` probe.
- `upsert_chat_log()` (insert, or update the row for this `conversation_id` in place) /
  `all_chat_logs()` / `clear_chat_logs()` (`insert_chat_log()` kept for back-compat). All
  go through `_run()`.

### `db_init.py` — schema management
`python -m api.db_init` (create, idempotent) · `--check` (report tables) · `--drop` (drop +
recreate, destructive). Reads `DATABASE_URL` from `.env`. `api/schema.sql` is the hand-written
equivalent for operators who apply DDL with `psql`.

`db._normalise_url()` turns a bare `postgresql://` URL into `postgresql+psycopg://` (or
`+psycopg2`, whichever driver is installed), so you can paste the string a provider gives you.
**Supabase:** use the *Session pooler* connection string — the direct host
`db.<ref>.supabase.co` is IPv6-only and won't resolve on most networks; the pooler
(`aws-0-<region>.pooler.supabase.com:5432`, user `postgres.<ref>`) is IPv4.

### `bot.py` — the inference pipeline
`respond(chat, question) -> AnswerResult`. The single code path for producing an answer,
used by **both** the app and the eval harness so they measure the same thing:
0. If `config.USE_RAG`: `chat.system = knowledge.system_prompt(query=question)` — re-ground
   on the sections retrieved for this turn.
1. `chat.send(question)` — the answer model, grounded in the docs.
2. `grounding.verify(question, draft)` — always against the full docs (skipped if
   `config.VERIFY_ANSWERS` is off).
3. If not supported → return the fixed refusal. Else return the draft.
`AnswerResult(text, draft, refused, grounding)`; `.log_entry()` produces the per-answer
record stored in the chat log. `fresh_chat()` = `llm.new_chat(knowledge.system_prompt())`.

`respond_stream(chat, question)` + `finalize_answer(question, draft)` — the streaming
split used by the Streamlit widget: `respond_stream` yields draft-answer chunks (RAG
prompt swap happens here; verification does **not**), then `finalize_answer` runs the
verification pass over the finished draft and returns the `AnswerResult`. Backed by
`llm.Chat.send_stream()` → `_gemini_backend.generate_stream()` (or the mock's chunked
stand-in). `respond()` is unchanged, so the FastAPI path and the eval harness are
unaffected.

### `engine.py` — the conversation state machine
UI-independent. `service.py` drives a `Conversation` through it; `app.py` implements the
same flow inline (it predates this module).
- `GREETING` — the opening line; `start()` puts it at `messages[0]` and `GET /widget/config`
  serves it, so the widget's greeting bubble and the logged transcript are the same string.
- `start(id?) -> Conversation` (greeting + a fresh `bot` chat)
- `ask(conv, text)` — appends turn, calls `bot.respond`, then routes to `feedback`,
  `offer_ticket` (on refusal or after N questions), else stays.
- `_enter_failure(conv, …)` — rule-based failure capture, move to `offer_ticket`, **and log
  the chat now** as `unresolved` (so a failed chat is captured even if no ticket follows).
- `feedback(conv, helpful)` — 👍 → appends *"Great — glad I could help!"*, `resolved` + log;
  👎 → `_enter_failure` (logs `unresolved`, offers a ticket).
- `tell_me_more(conv)` — back to `chat`.
- `ticket_draft(conv)` — `ticketing.default_draft` (no model call) + `jira_dedup.find_duplicate`.
- `submit_ticket(conv, *, email, subject, summary, category, needed_by="", name="")` —
  `needed_by` is a `YYYY-MM-DD` from the UI date picker (`ticketing.as_iso_date` validates
  → `conv.due_date`, `ticketing.urgency_for_date` → urgency); `name` is the submitter's
  name. All go to `create_issue` (`contact=email`, `submitter_name=name`, `due_date`,
  `urgency`). `link_duplicate(conv)` likewise. Both append their confirmation message and
  return a full `_state(conv)`.
- `_log(conv, outcome)` — upserts the `ConversationRecord` (called repeatedly: `unresolved`
  first, then the terminal outcome updates the same row). `log_abandoned(conv)` keeps a
  `not conv.logged` guard, so a chat that already reached any outcome is never relabelled
  `abandoned`.
- `serialize(conv) -> dict` / `deserialize(dict) -> Conversation` — plain JSON-able form
  (chat history included) that `service.py` stores in the `conversations` table.

Stages: `chat → feedback → offer_ticket → done`.

---

## 4. The ways to run it

*(Cloud deployment — Docker on Render + Supabase + GitHub Actions — is its own
document: `docs/architecture.md`. Folding the widget into the umbrella "SugboDoc"
multipage app is `MERGE.md`.)*

### A. Pure-Streamlit app — `streamlit_app.py`  (the primary path)
```
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # GEMINI_API_KEY (+ JIRA_*, DATABASE_URL)
streamlit run streamlit_app.py
#  or, with no key:   LLM_BACKEND=mock streamlit run streamlit_app.py
```
No server: the assistant runs in-process via `core/`. A static dashboard backdrop
(`web/index.html` with its old JS stripped) + a floating **💬 Support** widget pinned
bottom-right. Deployable to Streamlit Community Cloud as-is.

The `assistant/` package is the only place `import streamlit` appears:
- `assistant/widget.py` — `render_floating_assistant()`: a `st.popover` whose body is a
  `@st.fragment`; renders the transcript, `st.write_stream(session.stream_reply())` for
  the answer, then the feedback / ticket / "tell me more" controls per stage.
- `assistant/session.py` — the Streamlit sibling of `engine.py`. Same stages
  (`chat → feedback → offer_ticket → done`), same failure capture, same chat-log upsert,
  over `st.session_state` keys prefixed `asst_`. `resolve_pending(draft)` runs
  `bot.finalize_answer` and, if the verification pass walks a streamed draft back,
  **appends a visible correction** rather than silently swapping it.
- `assistant/ticket_dialog.py` — the ticket form as one `@st.dialog` (draft → dedup →
  form → `session.file_ticket` → `jira_client.create_issue`). Same Jira sink as before.
- `assistant/bootstrap.py` — `load_secrets()`: `st.secrets` → `os.environ` (MERGE SEAM #1).
- `assistant/styles.py` — the CSS that pins the widget bottom-right.

### A-legacy. Older full-page Streamlit demo — `app.py`
Still works (`streamlit run app.py`), still local-only. Its inline stage machine predates
both `engine.py` and `assistant/session.py`.

### B. FastAPI backend — `api/service.py`  (the "ship it to a website" path)
```
pip install -r requirements-service.txt
#  optional — persist sessions + logs to Postgres instead of memory + JSONL:
export DATABASE_URL=postgresql://user:pass@localhost:5432/sugbodoc
python -m api.db_init
uvicorn api.service:app --reload         # run from anywhere — config.py loads .env by absolute path
#  http://127.0.0.1:8000                 SugboDoc dashboard mockup + floating chat widget
#  http://127.0.0.1:8000/documentation   the docs viewer (left nav + rendered markdown)
#  http://127.0.0.1:8000/docs            OpenAPI explorer
```

### C. Docker Compose — the way production runs
```
docker compose up --build     # the API image + a throwaway PostgreSQL 16
#  http://localhost:8000       LLM_BACKEND=mock by default (no key needed)
docker compose down -v         # stop and wipe the local DB volume
```
Same image Render builds, against a real Postgres — dev/prod parity.
`web/index.html` is a **static** SugboDoc dashboard mockup (sidebar nav, stat cards, an
encounters table) with a fixed **floating chat bubble** in the lower-right. Clicking it
opens a chat card anchored above the bubble; a `×` collapses it. On open it shows the
assistant's greeting (`engine.GREETING`, fetched from `GET /widget/config`) as a bot
message, and resumes an in-progress conversation via `GET /session/{id}` after a reload.
The header subtitle reads *"Answers based on [documentation](/documentation)"*. Assistant
replies render as Markdown (`marked.js` + `DOMPurify`, both from cdnjs).

The widget renders new turns by **diffing `state.messages`** against what it has already
shown — so terminal replies like *"Great — glad I could help!"* (which carry no dedicated
`reply` field) appear with no special-casing, matching exactly what gets logged. While a
`/chat` or `/feedback` request is in flight a Messenger-style **three-dot "typing" bubble**
shows at the bottom of the log.

The **ticket form is a centred modal** (`openTicket()`): a full-viewport overlay dims and
blurs the page (dashboard *and* widget), with the form card in the middle — close via `×`,
Cancel, `Esc`, or a backdrop click. Clicking **"Submit a ticket"** in the chat first shows
a buffer — the button reads *"⏳ Preparing…"* and disables, and the typing bubble shows —
while the draft + duplicate check (a Jira read) load; then the modal opens. Submit inside
the modal disables the button ("Submitting…"), validates client-side, and on success
dismisses the modal and drops back to the chat, which now shows the *"✅ Ticket … created"*
confirmation.

`GET /documentation` renders `docs/SugboDoc-Documentation.md` with a sticky left-hand
section nav (built from `knowledge.content_sections()`, `##` + `###`, with scroll-spy) and
the body rendered by the same `marked.js` + `DOMPurify` pair.

Endpoints: `GET /`, `GET /documentation`, `GET /widget/config`, `GET /healthz`,
`GET /readyz`, `POST /chat`, `POST /feedback`, `POST /tell-me-more`, `GET /ticket/draft`,
`POST /ticket`, `POST /ticket/link-duplicate`, `GET|DELETE /session/{id}`.

**Health probes.** `/healthz` is **liveness** — 200 whenever the process is up, and
deliberately touches nothing external (it's Render's health check; coupling it to the DB
would cause restart loops when Supabase is paused). `/readyz` is **readiness** — runs
`db.ping()` (a `SELECT 1`) and returns 503 `database: down` if the DB is configured but
unreachable. The widget still works in that state (in-memory fallback), so `/readyz` is a
monitoring signal, not a gate.

**Middleware** (added in `service.py`): a request logger (`METHOD /path -> status (Nms)` to
stdout, and unhandled exceptions become a safe `500 {"detail":"internal error"}` with the
traceback logged server-side only), a per-IP in-process rate limiter (`RATE_LIMIT_PER_MIN`,
protects the Gemini quota; resets on redeploy), and CORS **only if `CORS_ORIGINS` is set**
(the bundled widget is same-origin, so the default is closed — never `*`). Optional Sentry
error tracking initialises only when `SENTRY_DSN` is set. Full cloud picture:
`docs/architecture.md`.

**Session store.** With `DATABASE_URL` unset, sessions live in an in-process dict (`_MEM`)
and finished conversations go to `logs/chats.jsonl` — fine for a single-process demo. With
it set, live sessions are rows in `conversations` (the serialised `engine.Conversation`,
`chat.history` included) and finished ones in `chat_logs`, so a restart or a second uvicorn
worker loses nothing. `service.py` reloads the conversation from the store on every request
and saves it back in a `finally:`; the row is dropped once the conversation ends (it's in
`chat_logs` by then), and a startup sweep clears live rows abandoned > 24 h. DB writes go
through `db._run()`, which retries once on a dropped pooler connection (`pool_pre_ping` +
`pool_recycle=1800`, small explicit `pool_size`/`max_overflow` for Supabase's connection
cap) rather than 500-ing or silently using a file. `/healthz` reports
`session_store: postgres | memory`.

> **Answering "do I need to rewrite this in TypeScript?"** — no. Streamlit is the only part
> that can't embed in an existing site; `service.py` gives you a JSON API your existing
> frontend calls, and the eval/analytics scripts stay in Python as offline jobs.

### C. Offline batch jobs (the maintenance side)
```
python -m analytics.seed_demo_log        # synthetic log so there's something to analyse
python -m analytics.analytics_kpis       # containment / refusal / repeat-question KPIs
python -m analytics.analytics_cluster    # failed questions → impact-ranked doc_gap_queue.json
python -m analytics.docs_loop            # top gaps + resolved Jira → doc_proposals/*.md
python -m evaluation.eval_run            # score the bot → eval_scorecard.md
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

**Calibration:** `python -m evaluation.eval_run --calibrate evaluation/eval_labels_template.csv` — you hand-label
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
duplicate-linked rate, unresolved rate (chat failed, no ticket filed), abandoned rate,
thumbs-up rate, refusal rate, verification-pass catch rate, repeat-question rate,
ticket categories.

---

## 7. Tests — `tests/`

`pip install -r requirements-dev.txt && pytest`. 83 tests, **fully offline** (the
`conftest.py` fixture forces the mock backend and points every path — cache, chat log — at
a `tmp_path`; the DB tests use a throwaway SQLite file, no server). Coverage:

| File | What it locks down |
|---|---|
| `test_knowledge.py` | section parsing, TOC exclusion, `find_section`, system prompt contents |
| `test_retrieval.py` | full-context vs RAG prompt, section ranking, bot answers + refuses with RAG on |
| `test_failure_capture.py` | every rule signal, fuzzy repeat detection |
| `test_chatlog.py` | JSONL round-trip, upsert-on-`conversation_id` (+ CSV mirror), `.failed` / `.failed_user_questions()` |
| `test_db.py` | chat-log round-trip via Postgres, `reset_store`, session persist/restore, `/healthz` store, drop-on-terminal |
| `test_ticketing.py` | deterministic `default_draft`, `as_iso_date`, `urgency_for_date` |
| `test_jira_client.py` | ADF structure, description fields, `duedate`/`urgency` mapping, name→`Submitter` (not `reporter`), custom-column ids resolved by name, drop-and-retry on a 400 |
| `test_jira_dedup_and_kpis.py` | cosine properties, duplicate match, KPI run |
| `test_llm.py` | cache hit-once, offline raises on miss / serves warm, `Chat` history, embed determinism |
| `test_bot_and_grounding.py` | answer path, refusal path, verification short-circuit |
| `test_eval_run.py` | bootstrap CI bounds, Cohen's κ, `run_case`, scorecard slices |
| `test_service.py` | health, answer flow, greeting in `messages[0]`, terminal reply in `messages[-1]`, `/widget/config`, `/session` resume + 404-after-done, `/documentation` page, ticket name/email/due-date pass-through, refusal→ticket, 404s, validation (FastAPI `TestClient`) |

---

## 8. Design decisions (and the reasoning)

| Decision | Why |
|---|---|
| Full docs in the prompt by default (RAG is opt-in) | ~8k tokens fit comfortably, and retrieval adds a missed-chunk failure mode. `USE_RAG=1` enables embedding-cosine section retrieval (`core/retrieval.py`) for the answer prompt only; the verification pass + eval judge still see everything, and the scorecard records the mode so the two are comparable. Worth turning on around ~5–10× the doc size. |
| **Separate verification pass** instead of trusting one call | A model is bad at self-policing "I don't know". A cheap independent check catches hallucinations; its threshold is tuned on the eval set. |
| **Rules** for failure detection, not a classifier | The refusal marker + a 👎 button catch most failures with zero ML. Train a model only once the logs show the rules missing failures. |
| Jira is **outbound-only**; dedup is the sole read | Reading tickets per turn adds latency, a sync pipeline, and stale-status risk for no benefit. Jira reaches the bot only as `Jira → docs → bot`. |
| Submitter identity goes to **plain-text custom columns**, not `reporter` | A chat user isn't a Jira account and `reporter` needs a strict accountId. Name/email land in `Submitter` / `Submitter Email` columns; `reporter` stays the API user, which flags the ticket as assistant-filed. |
| Ticket draft + failure triage are **deterministic, not model calls** | Cut to hold the per-conversation LLM budget at *answer + one verification pass*. Subject seeds from the first question; the user fills the rest. |
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
  fits in context and *not* reaching for RAG by default; knowing when a simpler tool wins.
- **A retrieval path that's actually swappable** (`retrieval.py`, `USE_RAG`) — one toggle,
  the rest of the pipeline unchanged, and an eval harness that scores both modes so the
  trade-off is measured rather than assumed.
- **Evaluation design** (`eval_run.py`) — a gold set with a refusal slice, LLM-as-judge
  with a rubric, judge/answer-model separation, **Cohen's κ calibration against human
  labels**, **bootstrap confidence intervals**, a frozen regression scorecard.
- **Grounding / hallucination control** (`grounding.py`) — a verification pass and a strict
  refusal contract, measured (over-refusal vs correct-refusal are both tracked).
- **Failure analytics** (`analytics_cluster.py`) — embedding + **HDBSCAN** density
  clustering of failed questions, cluster labelling, an **impact score**
  (frequency × stuckness × recency), coverage-gap ranking.
- **Cost engineering** (`llm.py`, `config.py`) — a request cache keyed by content hash, an
  offline mode, a mock backend, quota-aware retry that stops cleanly, per-model overrides,
  and a deliberately minimal per-turn call budget (answer + one verification pass; failure
  triage and ticket drafting are rule-based / deterministic).
- **Production shape** (`service.py`, `engine.py`) — UI-independent state machine, a JSON
  API, session-store abstraction, an integration (`jira_client.py`) against a real REST API
  with ADF payloads and team-managed-project quirks handled.
- **Data cleaning** — the knowledge base was reconstructed from a raw ASR transcript +
  chapter timestamps, with mislabeled chapters corrected.

---

## 10. Known limitations / next steps

- **Quota** — the free Gemini tier caps daily requests per model; a full `eval_run.py` is
  ~180 calls. Use `--limit`, `--mock`, the cache, enable billing, or spread runs over days.
  A real scorecard has not been generated yet — do this first (`python -m evaluation.eval_run`)
  and commit `evaluation/eval_scorecard.md` as the baseline (one per retrieval mode).
- **Clustering needs volume** — HDBSCAN is meaningful at a few hundred failed
  conversations, not the ~11 in the seeded demo (it currently collapses them to one group).
- **Sessions**: in-memory by default; set `DATABASE_URL` for the Postgres-backed
  `conversations` / `chat_logs` tables (`db.py`, `db_init.py`). The engine has
  `pool_pre_ping` + `pool_recycle` and `_run()` retries a dropped pooler connection once,
  but there are no Alembic migrations — `db_init.py` / `schema.sql` create the schema outright.
- **Security is portfolio-grade, not enterprise.** `service.py` has a per-IP in-process
  rate limiter (resets on redeploy, per-instance), closed-by-default CORS, safe error
  envelopes, and a non-root container — but **no end-user auth** (the chat is public by
  design) and no PII redaction of the transcript before it's logged. See
  `docs/architecture.md` → Security.
- `app.py` could be refactored onto `engine.py` to remove the duplicated flow.
- The verification pass doubles per-turn latency and cost — worth A/B-ing a
  confidence-gated version (only verify when the answer model is unsure).

---

## 11. First-run checklist

```
pip install -r requirements-dev.txt
pytest                                        # 83 tests, offline, ~2s

cp .env.example .env                          # add GEMINI_API_KEY
python -m evaluation.eval_run --limit 10      # sanity-check the real model
python -m evaluation.eval_run                 # full scorecard → commit eval_scorecard.md

streamlit run app.py                          # try the bot
uvicorn api.service:app --reload              # or the FastAPI backend + widget

# maintenance loop (offline-demoable with --mock):
python -m analytics.seed_demo_log
python -m analytics.analytics_kpis
python -m analytics.analytics_cluster --mock
python -m analytics.docs_loop --mock
```
