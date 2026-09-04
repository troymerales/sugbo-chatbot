# SugboDoc

<!-- update OWNER/REPO once pushed -->
[![CI](https://github.com/OWNER/REPO/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/ci.yml)

One pure-Streamlit app for a clinic / practice-management SaaS. No server, no
container — `streamlit run streamlit_app.py`, deployable to Streamlit Community
Cloud as-is. Two capabilities over a shared `core/` + `stt/` library:

1. **Support assistant** — the floating 💬 on every page. A documentation-grounded
   chatbot: answers strictly from the product docs, runs an independent
   verification pass, refuses cleanly when it can't help, and turns a stuck chat
   into a Jira ticket.
2. **Consultation Transcript → SOAP** — Bisaya/Cebuano consult audio → transcript
   (fine-tuned Whisper `troxyz1268/whisper-small-bisaya` via the Hugging Face
   Inference API) → English SOAP note → structured extract → grounding review →
   saved note. Plus **Past Notes** (browse / edit / export) and **Evaluation**
   (ASR WER/CER + SOAP grounding vs the synthetic `trial/` set).

Full module walkthrough: **[`docs/PROJECT.md`](docs/PROJECT.md)**. Chatbot design
+ diagrams: **[`docs/SugboDoc-Chatbot-Flowchart.md`](docs/SugboDoc-Chatbot-Flowchart.md)**.
STT consolidation notes (from the old `stt_soap` repo): **[`MERGE.md`](MERGE.md)**.

> **Knowledge base.** The repo ships a trimmed public excerpt at
> `docs/SugboDoc-Documentation.sample.md` so everything runs out of the box. Drop the full
> document at `docs/SugboDoc-Documentation.md` (git-ignored) to use it instead —
> `config.DOCS_PATH` picks it up automatically.

## Quickstart

```bash
pip install -r requirements-dev.txt      # runtime + pytest
pytest                                   # 90 tests, fully offline (~5s) — no keys needed

cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # GEMINI_API_KEY, HF_TOKEN, JIRA_*, DATABASE_URL
streamlit run streamlit_app.py           #  or:  LLM_BACKEND=mock streamlit run streamlit_app.py
```

- `GEMINI_API_KEY` powers the chatbot **and** SOAP generation / extract / review.
- `HF_TOKEN` powers transcription (the fine-tuned Whisper checkpoint via HF). If
  the model isn't on HF's free serverless API, point `HF_INFERENCE_URL` at a
  dedicated Inference Endpoint.
- `LLM_BACKEND=mock` runs the whole app — chatbot answers *and* a canned
  transcript — with no keys and no quota.

## Deploy (Streamlit Community Cloud)

Point a new app at `streamlit_app.py`, paste your `.streamlit/secrets.toml` into
**App → Settings → Secrets**, deploy. Free tier, no credit card. Set
`DATABASE_URL` (Supabase Session-pooler string) so chat logs survive a reboot —
the `chat_logs` table is created automatically on first write. Saved SOAP notes
use a local SQLite file (`soap_notes.db`), which **is** wiped on reboot unless
`BISAYA_DB_PATH` points at a mounted volume.

## Project layout

```
streamlit_app.py          home: dashboard backdrop + page links + floating assistant
config.py                 chatbot model names, thresholds, feature toggles

pages/
  1_Consultation_Transcript.py   audio → transcript → SOAP → extract → review → save
  2_Past_Notes.py                browse / edit / re-run / export saved notes
  3_Evaluation.py                ASR WER/CER + SOAP grounding vs trial/

assistant/   the chatbot's Streamlit layer (the floating widget; imports streamlit)
  widget.py · session.py · ticket_dialog.py · bootstrap.py · styles.py

core/        the chatbot library (pure Python)
  llm.py · _gemini_backend.py · _mock_backend.py   one model interface + SQLite cache
  knowledge.py · retrieval.py · grounding.py · bot.py · engine.py
  failure_capture.py · ticketing.py · jira_client.py · jira_dedup.py
  chatlog.py · chatlog_db.py    conversation logging (JSONL, or Supabase chat_logs)

stt/         the STT → SOAP library (pure Python, no torch)
  config.py · asr.py · quality.py · gemini.py
  soap.py · extract.py · review.py · schemas.py
  notes_db.py · export.py · evaluation.py · audio.py
stt_ui.py    Streamlit helpers for the STT pages

web/dashboard.html   static SugboDoc dashboard (the home-page backdrop)
trial/               synthetic Bisaya audio + script.txt (the evaluation set)
docs/                PROJECT.md · SugboDoc-Chatbot-Flowchart.md · the knowledge base
.streamlit/          config.toml (theme) + secrets.toml.example
tests/               90 offline pytest tests (mock backend, tmp paths, AppTest)
```

## Feature toggles (`.env` / `.streamlit/secrets.toml`)

| Env | Default | Effect |
|---|---|---|
| `GEMINI_API_KEY` | — | chatbot answers + SOAP / extract / review. Absent → those disabled; `mock` still works |
| `HF_TOKEN` | — | transcription (fine-tuned Whisper via HF Inference API). Absent → Transcribe button disabled |
| `LLM_BACKEND` | `gemini` | `mock` = deterministic offline stand-in (no key / quota), incl. a canned transcript |
| `VERIFY_ANSWERS` | `1` | `0` = skip the chatbot's verification pass (1 Gemini call/question instead of 2) |
| `USE_RAG` | `0` | `1` = inject only the top-`RAG_TOP_K` retrieved doc sections into the answer prompt |
| `RAG_TOP_K` | `6` | sections retrieved per question in RAG mode |
| `DATABASE_URL` | — | set → chat logs go to the `chat_logs` Postgres table instead of `logs/chats.jsonl` |
| `GEMINI_MODEL` | `gemini-3.6-flash` | chatbot answer model + SOAP model |
| `BISAYA_WHISPER_MODEL_ID` | `troxyz1268/whisper-small-bisaya` | the HF checkpoint |
| `HF_INFERENCE_URL` | HF serverless API | override for a dedicated Inference Endpoint |
| `BISAYA_DB_PATH` | `soap_notes.db` | SOAP-notes SQLite location |
| `JIRA_BASE_URL` / `JIRA_EMAIL` / `JIRA_API_TOKEN` / `JIRA_PROJECT_KEY` | — | ticket creation; absent → the ticket form explains |

Full list with comments in `.env.example`.
