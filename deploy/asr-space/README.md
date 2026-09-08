---
title: SugboDoc Whisper Bisaya ASR
emoji: 🎙️
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# SugboDoc — Bisaya/Cebuano ASR endpoint

A minimal FastAPI wrapper around **`troxyz1268/whisper-small-bisaya`** so the
SugboDoc Streamlit app can transcribe consultations without shipping `torch`
(Streamlit Community Cloud can't fit it).

## API

| Method | Path          | Body                                   | Response            |
|--------|---------------|----------------------------------------|---------------------|
| `GET`  | `/`           | —                                      | `{"status":"ok"}`   |
| `POST` | `/transcribe` | raw audio bytes, `Content-Type: audio/*` | `{"text":"..."}`  |

```bash
curl -X POST https://<user>-<space>.hf.space/transcribe \
     -H "Content-Type: audio/mpeg" \
     --data-binary @consult.mp3
```

## Config (Space → Settings → Variables and secrets)

| Name             | Default                          | Notes                                        |
|------------------|----------------------------------|----------------------------------------------|
| `MODEL_ID`       | `troxyz1268/whisper-small-bisaya`| any HF ASR checkpoint                         |
| `ASR_LANGUAGE`   | `tl`                             | Whisper's closest code to Cebuano            |
| `ASR_AUTH_TOKEN` | *(unset)*                        | if set, callers must send `Authorization: Bearer <token>` |

Keep the Space **public** for the simplest setup, or set `ASR_AUTH_TOKEN` here
**and** as `ASR_AUTH_TOKEN` in the SugboDoc app secrets to lock it down.

See [`deploy/asr-space/DEPLOY.md`](DEPLOY.md) in the SugboDoc repo for the full
create-and-wire runbook.
