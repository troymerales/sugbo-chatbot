# SugboDoc — Project Guide

One pure-Streamlit app for **SugboDoc**, a clinic / practice-management SaaS:

- a **documentation-grounded support chatbot** (the floating 💬 on every page) — answers
  "how do I…" questions **only** from the product docs, and when it can't, turns the
  failure into a Jira ticket;
- a **Bisaya speech → SOAP note** workflow (`pages/`) — consult audio → transcript
  (fine-tuned Whisper via HF) → English SOAP note → extract → grounding review → saved note.

This file is the module walkthrough. Chatbot design rationale + diagrams:
**`docs/SugboDoc-Chatbot-Flowchart.md`**. Consolidation history (from the old `stt_soap`
repo): **`MERGE.md`**.

---

## 1. The chatbot idea in one paragraph

The product docs are small (~8k tokens). So by default, instead of a vector database and
retrieval (RAG), the **whole document goes into the prompt every turn**. (A `USE_RAG=1`
toggle switches the *answer* prompt to embedding-cosine section retrieval — `core/retrieval.py`
— while the verification pass keeps seeing the full docs, so the two modes are
interchangeable.) A second, independent model call then checks the answer against the
docs — a *verification pass* — and if any claim isn't supported, the answer is replaced
with a fixed refusal. Every conversation is logged. A failed conversation becomes an
**outbound Jira ticket** (created only when the user asks). Jira is *never* read during a
chat — dedup against open issues is the sole read.

---

## 2. Repository layout

```
chatbot/
├── README.md                     overview + quickstart
├── MERGE.md                      consolidation history (from stt_soap + the old FastAPI backend)
├── config.py                     chatbot model names, thresholds, toggles (root)
├── streamlit_app.py              router — st.navigation([...], position="hidden")
├── home.py                       the dashboard page (web/dashboard.html body + assistant)
├── shell.py                      render_shell() — the eClinic chrome (left rail + top bar)
│
├── pages/                        the multipage app
│   ├── 1_Consultation_Transcript.py   audio → transcript → SOAP → extract → review → save
│   ├── 2_Past_Notes.py                browse / edit / re-run / export saved notes
│   └── 3_Evaluation.py                ASR (WER/CER) + SOAP grounding vs trial/
│
├── assistant/                    the chatbot's Streamlit layer (floating widget)
│   ├── widget.py                 render_floating_assistant() — on every page
│   ├── session.py                the widget's state machine (Streamlit sibling of core/engine.py)
│   ├── ticket_dialog.py          the support-ticket form, as an @st.dialog
│   ├── bootstrap.py              st.secrets → os.environ (keeps core/ + stt/ Streamlit-free)
│   └── styles.py                 the widget CSS (pins it bottom-right)
│
├── stt/                          STT → SOAP library — pure Python, no torch (from stt_soap)
│   ├── config.py                 Settings (models, HF_TOKEN, GEMINI_API_KEY, DB path)
│   ├── asr.py                    transcribe() — HF Inference API (fine-tuned Whisper)
│   ├── quality.py                TranscriptionResult + quality warnings
│   ├── gemini.py                 structured SOAP / extract / review (mock-aware)
│   ├── soap.py / extract.py / review.py / schemas.py   the Gemini pipeline
│   ├── notes_db.py               SQLite store for saved SOAP notes
│   ├── export.py                 Markdown / text / PDF
│   └── evaluation.py             WER/CER + SOAP grounding vs trial/
├── stt_ui.py                     Streamlit helpers for the STT pages
├── trial/                        synthetic Bisaya audio + script.txt (the eval set)
│
├── core/                         the chatbot library
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
│   ├── chatlog_db.py             SQLAlchemy engine + chat_logs table — opt-in (DATABASE_URL)
│   ├── bot.py                    respond() — the inference pipeline (answer + verify)
│   └── engine.py                 the conversation state machine (UI-independent) + serialize()
│
├── web/dashboard.html            static SugboDoc dashboard (the home-page backdrop)
├── .streamlit/                   config.toml (theme) + secrets.toml.example
├── docs/                         PROJECT.md · SugboDoc-Chatbot-Flowchart.md · the knowledge base
└── tests/                        pytest suite (runs fully offline, 90 tests; AppTest for the pages)
```

`config.py` stays at the root so `import config` resolves everywhere; `stt/` has
its own `stt/config.py`.

---

## 3. Core library — file by file

### `config.py`
Single place that loads `.env` (once, by absolute path — `ROOT / ".env"`) and holds every
chatbot tunable. Nothing else calls `load_dotenv`. The STT side has `stt/config.py`.

Key names:
- `ANSWER_MODEL`, `UTILITY_MODEL`, `EMBED_MODEL` — overridable via env (`GEMINI_MODEL` etc.).
- `QUESTIONS_BEFORE_TICKET` (default 3) — after this many questions without a 👍, the bot
  proactively offers a ticket.
- `DEDUP_SIMILARITY_THRESHOLD` (default 0.82) — cosine similarity above which a drafted
  ticket is treated as a duplicate.
- `REFUSAL_MARKER` — the exact sentence the bot must emit when it can't answer.
- `VERIFY_ANSWERS` (default 1) — run the verification pass. `0` halves the model calls
  per question at the cost of the grounding check.
- `LLM_BACKEND` (`gemini` | `mock`), `LLM_CACHE` (bool), `LLM_OFFLINE` (bool).
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
  upsert); set → one row in the `chat_logs` table via `chatlog_db.upsert_chat_log()`.
- `reset_store()` wipes the log (file unlink or `DELETE FROM chat_logs`, plus the CSV).
  `new_conversation_id()`, `now_iso()`.
- **Local CSV mirror:** every `append()` rewrites `logs/chats.csv` from the primary store
  — one row per conversation. Nothing reads it back; it's for eyeballing in a spreadsheet.

### `chatlog_db.py` — Postgres chat-log persistence (opt-in)
Only active when `DATABASE_URL` is set. One model, **`ChatLogRow`** (`chat_logs` — keyed
by `conversation_id`, promoted `outcome` / timestamps for querying + the full `record`
JSONB; plain JSON on SQLite for the tests). The table is created on first use.
- `enabled()` — `bool(config.DATABASE_URL)`.
- `_get_engine()` adds `pool_pre_ping` + `pool_recycle=1800` for managed poolers, plus a
  small `pool_size` / `max_overflow`. `_run(op)` runs `op` in a transaction and **retries
  once** on a dropped idle pooler connection. `session()`, `reset()`, `init_db()`, `drop_db()`.
- `upsert_chat_log()` / `all_chat_logs()` / `clear_chat_logs()`.
- `_normalise_url()` turns a bare `postgresql://` URL into `postgresql+psycopg://`.
  **Supabase:** use the *Session pooler* string (`aws-0-<region>.pooler.supabase.com:5432`,
  user `postgres.<ref>`) — the direct host is IPv6-only.

### `bot.py` — the inference pipeline
`respond(chat, question) -> AnswerResult`. The single code path for producing an answer:
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
stand-in). `respond()` is unchanged.

### `engine.py` — the conversation state machine
UI-independent — the canonical flow. `assistant/session.py` is a thin Streamlit sibling
(same stages, `st.session_state` instead of a `Conversation` object).
- `GREETING` — the opening line; `start()` puts it at `messages[0]`.
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
  (chat history included) — used by `assistant/session.py` to keep the `llm.Chat` in
  `st.session_state`.

Stages: `chat → feedback → offer_ticket → done`.

---

## 3b. The STT → SOAP side — `stt/`, `stt_ui.py`, `pages/`

Ported from the standalone `stt_soap` repo (see `MERGE.md`). Same split as the
chatbot: `stt/` is pure Python (no Streamlit, and — unlike the original — no
`torch`); `stt_ui.py` + `pages/` are the Streamlit layer.

**Pipeline:** `audio → stt.asr.transcribe → stt.soap.generate_soap_note →
stt.extract.extract_clinical_facts → stt.review.review_soap_note → stt.notes_db`.

- **`stt/config.py`** — `Settings` dataclass (`get_settings()` cached, `reload_settings()`
  drops the cache). `whisper_model_id`, `hf_inference_url`, `hf_token`,
  `soap_model_id`, `BISAYA_DB_PATH`, `BISAYA_TRIAL_DIR`. `asr_available` / `llm_available`.
  Reads `os.environ` only.
- **`stt/asr.py`** — `transcribe(audio_bytes, mime, *, duration_s) -> TranscriptionResult`.
  `POST`s the audio to the fine-tuned checkpoint on the **HF Inference API**
  (`Authorization: Bearer HF_TOKEN`), retrying the 503 "model loading" response with the
  server's `estimated_time`. No Gemini in this path. `LLM_BACKEND=mock` → a canned transcript.
- **`stt/quality.py`** — `TranscriptionResult` (word count, wps, repetition ratio,
  `quality_warnings()`). Plain text — no diarization.
- **`stt/gemini.py`** — reuses `core/_gemini_backend._client()` (one key).
  `generate_structured(prompt, PydanticModel)` (JSON mode + `response_schema`).
  `_call_with_retry` handles 429 → `LLMQuotaError`; no key → `LLMUnavailableError`.
  **Honours `config.LLM_BACKEND == "mock"`** — returns canned `SoapNote` /
  `ClinicalExtract` / `GroundingReview` so the STT tests + AppTests are fully offline.
- **`stt/soap.py` / `extract.py` / `review.py`** — one Gemini structured call each, with
  a prompt that tolerates ASR noise and never adds unsupported clinical facts.
  `soap.parse_soap_text` parses a pasted plain-text note.
- **`stt/schemas.py`** — `SoapNote`, `ClinicalExtract`, `GroundingReview` (pydantic;
  request schema + response validation + render shape).
- **`stt/notes_db.py`** — SQLite CRUD + search for saved notes (`BISAYA_DB_PATH`).
  Ephemeral on Community Cloud; a Postgres version mirroring `core/chatlog_db.py` is the follow-up.
- **`stt/export.py`** — Markdown / plain text / PDF (`reportlab`, optional).
- **`stt/evaluation.py`** — `load_reference_clips()` reads `trial/script.txt` +
  `trial/audio_output/`; `score_transcription` (WER/CER via `jiwer`); `evaluate_clip`
  runs the pipeline per clip; `aggregate` for the summary metrics.
- **`shell.py`** — `render_shell(active)`: the eClinic chrome shared by every page —
  a left nav rail (styled to match `web/dashboard.html`; Dashboard / Consultation
  Transcript / Past Notes / Evaluation are real destinations, the other modules are
  inert mockups), the indigo top bar, and full-screen layout (Streamlit header /
  padding removed). `alert_missing_keys()` pops a one-off dialog when `GEMINI_API_KEY`
  / `HF_TOKEN` is missing (no-op under the mock backend) — there is no status panel.

  The four real rail entries are `st.button`s calling `st.switch_page()`, styled by
  CSS to match the inert `<a>` rows around them. They were plain anchors at first,
  which measured ~3 s per page switch locally (worse on Community Cloud): an anchor
  is a full browser navigation, so it re-boots the Streamlit frontend and opens a new
  WebSocket session, discarding `st.session_state`. Switching over the open socket
  measures ~160 ms and keeps state. `st.page_link` is the obvious alternative but
  raises `KeyError: 'url_pathname'` when a page runs outside `st.navigation` — which
  is exactly how the AppTest suite runs them.
- **`stt_ui.py`** — `llm_guard` (quota/missing-key → clean message), `editable_soap`
  (the S/O/A/P sections as a keyed 2×2 grid, accent-striped by `shell.py`),
  `render_{extract,review}`.
- **`pages/1_Consultation_Transcript.py`** — the New Note workflow, laid out as the
  workflow reads: a narrow centred **recording card** (the `st.audio_input` mic is
  the big primary control; upload is a one-line link under it) is the focus until a
  transcript exists, then it collapses to a one-line summary and the wider
  **transcript** + **SOAP** cards take over. A stepper (Record → Transcribe →
  Document) tracks progress. `pages/2_Past_Notes.py`
  — browse / edit / re-run / export / delete. `pages/3_Evaluation.py` — the batch scorer.
  Each page: `load_secrets()` → `render_shell(...)` → page body → `render_floating_assistant()`.

---

## 4. Running it

```
pip install -r requirements-dev.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # GEMINI_API_KEY, HF_TOKEN, JIRA_*, DATABASE_URL
streamlit run streamlit_app.py
#  or, no keys:   LLM_BACKEND=mock streamlit run streamlit_app.py
```

`streamlit_app.py` is the router (`st.navigation([...], position="hidden")`); every
page paints the eClinic shell itself via `shell.render_shell()`. `home.py` is the
dashboard — the static `web/dashboard.html` body inside that shell + the floating
**💬 Support** widget. `pages/` adds the STT workflow. Deployable to Streamlit
Community Cloud as-is (see the README). `MERGE.md` has the consolidation history.

### The chatbot widget — `assistant/`

The only place `import streamlit` appears on the chatbot side:
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

### The STT pages — `pages/`

`pages/1_Consultation_Transcript.py` (upload/record audio → transcribe → SOAP →
extract → review → save), `pages/2_Past_Notes.py` (browse / edit / re-run / export /
delete), `pages/3_Evaluation.py` (batch-score the `trial/` clips). Each page:
`load_secrets()` → `render_shell(...)` (the eClinic chrome, from `shell.py`) → page
body → `render_floating_assistant()`. `stt_ui.py` holds the shared render helpers
(`llm_guard`, `editable_soap`, `render_{extract,review}`).

## 5. Tests — `tests/`

`pip install -r requirements-dev.txt && pytest`. 90 tests, **fully offline** — the
`conftest.py` fixture forces the mock backend and points every path (LLM cache, chat
log, SOAP-notes DB) at a `tmp_path`; DB tests use a throwaway SQLite file.

| File | What it locks down |
|---|---|
| `test_knowledge.py` | section parsing, TOC exclusion, `find_section`, system-prompt contents |
| `test_retrieval.py` | full-context vs RAG prompt, section ranking, bot answers + refuses with RAG on |
| `test_failure_capture.py` | every rule signal, fuzzy repeat detection |
| `test_chatlog.py` | JSONL round-trip, upsert-on-`conversation_id` (+ CSV mirror), `.failed` |
| `test_ticketing.py` | deterministic `default_draft`, `as_iso_date`, `urgency_for_date` |
| `test_jira_client.py` | ADF structure, description fields, `duedate`/`urgency`, name→`Submitter`, drop-and-retry on a 400 |
| `test_jira_dedup.py` | cosine dedup: not-configured, close match, below-threshold, empty list |
| `test_llm.py` | cache hit-once, offline raises on miss / serves warm, `Chat` history, embed determinism, streaming |
| `test_bot_and_grounding.py` | answer path, refusal path, verification short-circuit |
| `test_assistant.py` | widget state machine (AppTest): greeting, answer→feedback, refusal→ticket, thumbs, ticket upsert, reset |
| `test_stt_core.py` | STT config, schemas, SOAP parse, transcript quality, notes DB, export, evaluation vs `trial/` |
| `test_stt_gemini.py` | 429 retry/backoff, JSON coercion, mock fixtures, missing-key |
| `test_stt_page.py` | the 3 STT pages (AppTest): render, generate SOAP, save, Past Notes list, Evaluation |

---

## 6. Design decisions (and the reasoning)

| Decision | Why |
|---|---|
| Full docs in the prompt by default (RAG is opt-in) | ~8k tokens fit comfortably; retrieval adds a missed-chunk failure mode. `USE_RAG=1` switches only the answer prompt to embedding-cosine section retrieval; the verification pass still sees everything. |
| **Separate verification pass** instead of trusting one call | A model is bad at self-policing "I don't know". A cheap independent check catches hallucinations. `VERIFY_ANSWERS=0` turns it off. |
| **Rules** for failure detection, not a classifier | The refusal marker + a 👎 button catch most failures with zero ML. |
| Jira is **outbound-only**; dedup is the sole read | Reading tickets per turn adds latency and stale-status risk for no benefit. |
| Submitter identity → **plain-text custom columns**, not `reporter` | A chat user isn't a Jira account; `reporter` needs a strict accountId. |
| Ticket draft + failure triage are **deterministic** | Holds the per-conversation LLM budget at *answer + one verification pass*. |
| **Response cache + mock backend** | Free-tier quota is ~20 requests/day/model. The mock lets the whole app + test suite run with no key. |
| `engine.py` separate from the UI | The conversation logic is UI-independent; `assistant/session.py` is a thin Streamlit sibling. |
| **Transcription = the fine-tuned checkpoint via HF**, not Gemini | Gemini is general-multilingual; the fine-tune is the point. HF hosts it — no torch. |

---

## 7. Known limitations / next steps

- **HF serverless API** often refuses custom small-Whisper models. Verify the endpoint; if
  it's unavailable, stand up a dedicated HF Inference Endpoint and set `HF_INFERENCE_URL`.
- **SOAP notes are SQLite** — ephemeral on Community Cloud unless `BISAYA_DB_PATH` is a
  mounted volume. A Postgres `soap_notes` table sharing the chatbot's Supabase (mirroring
  `core/chatlog_db.py`) is the natural follow-up.
- **No end-user auth** — the chat and the transcript workspace are public by design. No PII
  redaction of a transcript before it's logged.
- The verification pass doubles the chatbot's per-turn latency/cost — worth A/B-ing a
  confidence-gated version.
- No real ASR accuracy numbers yet — run `pages/3_Evaluation.py` against a live `HF_TOKEN`.

---

## 8. First-run checklist

```
pip install -r requirements-dev.txt
pytest                                        # 90 tests, offline, ~5s

cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # GEMINI_API_KEY, HF_TOKEN, JIRA_*
LLM_BACKEND=mock streamlit run streamlit_app.py              # try it with no keys
streamlit run streamlit_app.py                               # then for real
```
