# Consolidation notes — SugboDoc = one repo

**`troymerales/sugbo-chatbot` is the single SugboDoc app.** The support chatbot and
the Bisaya speech→SOAP tool (formerly `troymerales/stt_soap`) now live here as one
pure-Streamlit multipage app. Both `stt_soap` and the chatbot's old FastAPI /
Docker / Render backend are retired — keep `stt_soap` only as source history for
`stt/`.

```
streamlit_app.py                     home: dashboard backdrop + page links + floating assistant
pages/1_Consultation_Transcript.py   audio → transcript → SOAP → extract → review → save
pages/2_Past_Notes.py                browse / edit / re-run / export saved notes
pages/3_Evaluation.py                ASR (WER/CER) + SOAP grounding vs trial/
assistant/                           the chatbot's floating widget (on every page)
core/                                chatbot pipeline (bot, knowledge, llm, grounding, engine, …)
stt/                                 STT→SOAP library — ported from stt_soap/core/
stt_ui.py                            Streamlit helpers for the STT pages
trial/                               STT/SOAP evaluation fixtures
```

## What was ported from `stt_soap`, and how

| `stt_soap` source | here | change |
|---|---|---|
| `core/transcribe.py` | `stt/asr.py` + `stt/quality.py` | **local Whisper (torch/transformers) removed.** `stt/asr.py` POSTs the audio to the fine-tuned checkpoint `troxyz1268/whisper-small-bisaya` on the **HF Inference API** — no Gemini in the ASR path. `TranscriptionResult` + quality warnings moved to `stt/quality.py`. |
| `core/diarize.py` (pyannote) | *dropped* | no torch, no diarization. The SOAP prompt already handles an unlabelled transcript ("infer the roles from context"). |
| `core/gemini.py` | `stt/gemini.py` | reuses the chatbot's cached Gemini client (one key). SOAP / extract / review only. Honours `config.LLM_BACKEND == "mock"` — returns canned objects so the whole suite is offline. |
| `core/config.py` `Settings` | `stt/config.py` | same `Settings`/`get_settings()` shape; reads `os.environ` (populated by `assistant/bootstrap.py`). Dropped `chunk/stride`, `home_url`, `diar_num_speakers`; added `hf_inference_url`, `asr_available`. |
| `core/soap.py` `extract.py` `review.py` `schemas.py` `db.py` `export.py` `evaluation.py` `audio.py` | `stt/*` | near-verbatim; imports repointed `core.* → stt.*`. `db.py → stt/notes_db.py`. `audio.py` reads bytes + WAV-header duration (no ffmpeg). |
| `app.py` + `pages/1_Past_Notes.py` + `pages/2_Evaluation.py` | `pages/1_Consultation_Transcript.py`, `pages/2_Past_Notes.py`, `pages/3_Evaluation.py` | audio → bytes; `warm_pipeline()` + the diarize checkbox removed; `render_floating_assistant()` added to each. |
| `stt_ui.py` | `stt_ui.py` | dropped `load_pipeline` / `warm_pipeline`; sidebar shows the HF model + a link back to the dashboard. |
| `api/main.py` + `web/consult*.{html,js}` | *not ported* | the app is Streamlit-only. |
| `tests/test_{config,soap,db,export,evaluation,gemini,transcribe}.py` | `tests/test_stt_{core,gemini,page}.py` | ported + adapted. `test_diarize.py` / `test_api.py` dropped. |
| `docs/handbook.html`, `docs/build_handbook.py` | *not ported* | see `docs/PROJECT.md`. |
| `requirements.txt` (torch, transformers, torchvision, pyannote) | *removed* | `jiwer`, `reportlab`, `pandas`, `pydantic` kept. `packages.txt` (ffmpeg) gone. |

## What was removed from the chatbot side

The FastAPI backend (`api/service.py`), `api/db_init.py`, `api/schema.sql`,
`Dockerfile`, `docker-compose.yml`, `render.yaml`, `.dockerignore`,
`docs/architecture.md`, `keepalive.yml`, `app.py` (old full-page demo), the
offline eval harness (`evaluation/`), the failure-clustering / docs-loop
tooling (`analytics/`), `scripts/`, `core/cli.py`, and the JS/widget in
`web/index.html` (replaced by `web/dashboard.html`). `api/db.py` was trimmed to
just chat-log persistence and moved to `core/chatlog_db.py`. CI is now a single
test job.

## Config seams

- **Secrets:** every page calls `assistant.bootstrap.load_secrets()` first
  (st.secrets → os.environ). `stt/` and `core/` only read `os.environ`.
- **One Gemini key/client:** `stt/gemini._client()` reuses `core/_gemini_backend._client()`.
- **`GEMINI_API_KEY`** → chatbot answer/verify + SOAP / extract / review.
  **`HF_TOKEN`** → transcription. **`GEMINI_MODEL`** sets the chatbot answer model
  and the SOAP model; **`BISAYA_WHISPER_MODEL_ID`** sets the ASR checkpoint.

## Known follow-ups

- **SOAP notes are SQLite** (`stt/notes_db.py`), ephemeral on Community Cloud.
  Natural next step: a Postgres `soap_notes` table sharing the chatbot's Supabase
  — mirror the pattern in `core/chatlog_db.py`.
- **Verify the HF endpoint.** HF's *free* serverless Inference API often refuses
  custom small-Whisper models. If so, stand up a dedicated HF Inference Endpoint
  and set `HF_INFERENCE_URL`.
