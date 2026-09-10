# SugboDoc

[![CI](https://github.com/troymerales/sugbo-chatbot/actions/workflows/ci.yml/badge.svg)](https://github.com/troymerales/sugbo-chatbot/actions/workflows/ci.yml)

A pure-Streamlit multipage app for clinic consulting. Combines a documentation-grounded support chatbot with an Bisaya/Cebuano speech-to-text workflow that generates structured clinical notes.

## Features

**Support Assistant** — A floating 💬 on every page that answers questions strictly from the product knowledge base, runs an independent verification pass, and escalates stuck conversations to Jira tickets.

**Consultation Transcript → SOAP Note** — Record or upload Bisaya/Cebuano audio → transcribe with fine-tuned Whisper → auto-generate English SOAP note → extract structured data → verify grounding → save. Includes a past-notes viewer, editor, and export tool.

**Evaluation** — Backtest suite measuring ASR accuracy (WER/CER) and SOAP grounding quality on a labeled evaluation set. Result: **6.1% potential ticket deflection** across 33 historical tickets (95% CI: Wilson 1.7–19.6%, Clopper–Pearson 0.7–20.2%).

## Architecture

Streamlit-only (no backend server or container). All interaction is client-side; conversation logs optionally persist to Supabase. The app is two independent libraries:

- **`core/`** — Chatbot pipeline (knowledge retrieval, LLM interface, grounding, Jira ticketing)
- **`stt/`** — STT→SOAP workflow (transcription, note generation, extraction, review, persistence)

Both use Gemini for LLM operations and support a deterministic offline mock backend for testing.

## Installation & Quick Start

### Prerequisites
- Python 3.11+
- `pip`

### Local Development

```bash
# Install dependencies (includes test suite)
pip install -r requirements-dev.txt

# Run tests (109 tests, fully offline, no API keys needed)
pytest

# Set up secrets (copy template and fill in your keys)
cp .streamlit/secrets.toml.example .streamlit/secrets.toml

# Run the app locally
streamlit run streamlit_app.py

# Or run fully offline (mock backend, no keys needed)
LLM_BACKEND=mock streamlit run streamlit_app.py
```

## Configuration

Settings are read from environment variables (set in `.streamlit/secrets.toml` on Streamlit Community Cloud, or `.env` locally). Key variables:

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | — | **Required** for chatbot answers and SOAP generation. Without it, those features are disabled; mock mode still works. |
| `ASR_API_URL` | — | **Deployed transcription.** HTTP endpoint wrapping the Whisper checkpoint. See [deploy/asr-space/DEPLOY.md](deploy/asr-space/DEPLOY.md). |
| `ASR_AUTH_TOKEN` | — | Bearer token for a private ASR endpoint (optional if ASR_API_URL is public). |
| `HF_TOKEN` | — | **Local/fallback transcription.** Hugging Face API token if using the (slower) serverless Inference API. Ignored if `transformers` is installed locally. |
| `LLM_BACKEND` | `gemini` | `mock` = deterministic offline mode (no keys, no quota, canned responses). Useful for demos and testing. |
| `VERIFY_ANSWERS` | `1` | `0` = skip the chatbot's second-pass verification (costs 1 Gemini call/question). |
| `USE_RAG` | `0` | `1` = retrieve and inject doc sections into answer prompts. |
| `RAG_TOP_K` | `6` | Number of doc sections to retrieve per question (only if `USE_RAG=1`). |
| `DATABASE_URL` | — | Supabase connection string (Session pooler). Chat logs persist to `chat_logs` table. Without it, logs go to local JSONL. |
| `JIRA_*` | — | Jira Cloud credentials for ticket creation. Omit to disable ticketing. |
| `BISAYA_WHISPER_MODEL_ID` | `troxyz1268/whisper-small-bisaya` | HuggingFace checkpoint ID for the fine-tuned Whisper model. |
| `GEMINI_MODEL` | `gemini-3.6-flash` | LLM model for chatbot answers and SOAP generation. |
| `BISAYA_DB_PATH` | `soap_notes.db` | SQLite file for storing SOAP notes (local only; Streamlit Community Cloud instance wipes it on reboot). |

See `.env.example` and `.streamlit/secrets.toml.example` for complete, commented templates.

## Deployment

### Streamlit Community Cloud (Free)

1. Push the repo to GitHub
2. Create a new Streamlit app pointing at `streamlit_app.py`
3. In **App → Settings → Secrets**, paste the filled-in `.streamlit/secrets.toml`
4. Deploy

For durable chat-log storage, set `DATABASE_URL` to a Supabase Session-pooler connection string (free tier available). SOAP notes use SQLite, which is ephemeral on Community Cloud unless you mount a volume.

### Transcription in Production

By default, the app expects `ASR_API_URL` to point at a hosted transcription service. The repo includes a minimal Hugging Face Space wrapper:

```bash
cd deploy/asr-space
# Follow DEPLOY.md to create a free Docker Space
```

Then set `ASR_API_URL = "https://<user>-sugbodoc-asr.hf.space/transcribe"` in Streamlit secrets.

For local development, install `transformers` + `torch` to run Whisper in-process:

```bash
pip install transformers torch librosa soundfile
# ASR will use local Whisper instead of the HTTP endpoint
```

## Project Structure

```
streamlit_app.py               App router and home page
home.py                        Dashboard + page navigation + floating assistant

pages/
  1_Consultation_Transcript.py   Audio capture → transcribe → SOAP → extract → review → save
  2_Past_Notes.py               Browse, edit, re-run, or export saved notes
  3_Evaluation.py               View ASR/SOAP evaluation metrics vs. trial set

assistant/                       Floating chatbot widget
  widget.py                      Popover container, message history, feedback buttons
  session.py                     Conversation state and reply streaming
  styles.py                      CSS for the widget (portalled to the root container)
  ticket_dialog.py               "Create a ticket" dialog
  bootstrap.py                   Secret loading and initialization

core/                            Chatbot library (pure Python, Streamlit-independent)
  bot.py · engine.py             Main pipeline: retrieve docs → build prompt → call LLM
  knowledge.py · retrieval.py    Doc loading and semantic search (FAISS)
  grounding.py                   Verify answers against the source docs
  llm.py                         Gemini + mock interface; LLM result caching
  failure_capture.py             Log reasons why the chatbot refused a question
  ticketing.py · jira_*          Jira ticket creation and deduplication
  chatlog.py · chatlog_db.py     Conversation logging to JSONL or Supabase

stt/                             Speech-to-text → SOAP library (pure Python, no torch)
  asr.py                         Call the hosted ASR endpoint (or fallback to local Whisper)
  quality.py                     Audio quality checks and warnings
  soap.py · extract.py · review.py   SOAP note generation, structured extraction, grounding check
  schemas.py                     Pydantic models for SOAP structure
  notes_db.py                    SQLite persistence for saved notes
  export.py                      PDF export for SOAP notes
  evaluation.py                  WER/CER metrics vs. transcribed labels
  gemini.py                      Shared Gemini interface for SOAP tasks
  audio.py                       Audio file parsing and duration calculation
  config.py                      Settings (read from environment)

stt_ui.py                        Streamlit-specific helpers for the STT pages

web/
  dashboard.html                 Static home-page backdrop
  sugbodoc.png                   Project logo

docs/
  PROJECT.md                     Detailed architecture and module reference
  SugboDoc-Chatbot-Flowchart.md  Chatbot design diagrams and examples
  SugboDoc-Documentation.sample.md   Public knowledge base excerpt (fallback)

evaluation/
  backtest.py                    Deflection-rate evaluation engine
  dashboard_mock.py              Public demo dashboard (synthetic data)
  FINDINGS.md                    Evaluation results and confidence intervals
  jira_backtest.ipynb            Interactive evaluation notebook
  mock_results/                  Synthetic data for demo
  data/jira_tickets.sample.csv   Sample ticket data

trial/                           Bisaya audio clips + transcription references (eval fixtures)
.streamlit/                      Streamlit config (theme) + secrets template
.github/workflows/               CI configuration
tests/                           109 pytest tests (mock backend, isolated fixtures)
```

## Testing

All tests are offline (mock backend, no API keys needed):

```bash
pytest                  # Run all 109 tests (~5 seconds)
pytest -v              # Verbose output
pytest tests/test_bot.py::TestBotAndGrounding::test_something  # Single test
```

## Evaluation Results

A backtest across 33 historical Jira tickets showed:

| Metric | Value | CI (95%) |
|---|---|---|
| Potential deflection rate | 6.1% (2/33 FULL) | Wilson: 1.7–19.6% |
| | | Clopper–Pearson: 0.7–20.2% |
| Evaluator vs. human agreement | — | (not validated against real humans; LLM-judge error not quantified) |

See `evaluation/FINDINGS.md` for methodology, limitations, and next steps.

## Known Limitations

- **Transcription accuracy** depends on audio quality and the fine-tuned Whisper model. The `trial/` set serves as a smoke test, not a production benchmark.
- **SOAP grounding** is verified by re-reading the transcript; errors in transcription can mislead the grounding check.
- **LLM evaluator** (in the backtest) is itself an LLM — errors here are not quantified against human review.
- **Jira ticketing** requires live credentials; it's optional and can be omitted.
- **SOAP notes** are stored in ephemeral SQLite on Streamlit Community Cloud unless a volume is mounted.

## Future Improvements

- Replace in-process FAISS with a persistent vector DB (Supabase `pgvector`, Weaviate, etc.)
- Add multi-language support beyond Bisaya/Cebuano
- Integrate speaker diarization for multi-party consultations
- Build a real-human evaluation set to quantify LLM-judge bias
- Support streaming transcription (real-time captions)
- Add conversation export (PDF, DOCX)

## License

MIT

---

**Glossary:**

- **SOAP note** — Subjective, Objective, Assessment, Plan clinical documentation format
- **WER/CER** — Word / Character Error Rate (ASR accuracy metrics)
- **RAG** — Retrieval-Augmented Generation (inject retrieved docs into the LLM prompt)
- **FAISS** — Meta's approximate nearest-neighbor search library (used for doc retrieval)
- **Jira dedup** — Avoid creating duplicate tickets for the same issue
