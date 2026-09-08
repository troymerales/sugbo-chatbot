"""
Tiny HTTP wrapper around the fine-tuned Bisaya/Cebuano Whisper checkpoint, for a
free Hugging Face **Docker Space**. The SugboDoc app calls this from Streamlit
Community Cloud (which has no torch) via ``ASR_API_URL``.

    POST /transcribe        body: raw audio bytes, Content-Type: audio/*
                            -> {"text": "..."}
    GET  /                  -> {"status": "ok", ...}   (health check)

Environment (set as Space "Variables and secrets"):
    MODEL_ID        default troxyz1268/whisper-small-bisaya
    ASR_LANGUAGE    default "tl"  (Whisper's closest code to Cebuano)
    ASR_AUTH_TOKEN  optional; if set, callers must send  Authorization: Bearer <token>
"""

from __future__ import annotations

import os
import tempfile

from fastapi import FastAPI, HTTPException, Request

MODEL_ID = os.environ.get("MODEL_ID", "troxyz1268/whisper-small-bisaya")
LANGUAGE = os.environ.get("ASR_LANGUAGE", "tl")
AUTH_TOKEN = os.environ.get("ASR_AUTH_TOKEN", "").strip()

_SUFFIX = {
    "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/wave": ".wav",
    "audio/mpeg": ".mp3", "audio/mp3": ".mp3",
    "audio/mp4": ".m4a", "audio/x-m4a": ".m4a",
    "audio/ogg": ".ogg", "audio/opus": ".opus",
    "audio/webm": ".webm", "audio/flac": ".flac",
}

app = FastAPI(title="whisper-small-bisaya ASR")
_pipe = None


def _get_pipe():
    global _pipe
    if _pipe is None:
        from transformers import pipeline
        _pipe = pipeline(
            "automatic-speech-recognition",
            model=MODEL_ID,
            chunk_length_s=30,
            stride_length_s=5,
        )
    return _pipe


@app.get("/")
def health():
    return {"status": "ok", "model": MODEL_ID, "loaded": _pipe is not None}


@app.post("/transcribe")
async def transcribe(request: Request):
    if AUTH_TOKEN and request.headers.get("authorization", "") != f"Bearer {AUTH_TOKEN}":
        raise HTTPException(status_code=401, detail="missing or invalid bearer token")

    audio = await request.body()
    if not audio:
        raise HTTPException(status_code=400, detail="empty request body")

    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    suffix = _SUFFIX.get(ctype, ".wav")

    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fh:
            fh.write(audio)
            path = fh.name
        out = _get_pipe()(
            path, generate_kwargs={"language": LANGUAGE, "task": "transcribe"}
        )
        text = (out.get("text", "") if isinstance(out, dict) else "") or ""
        return {"text": text.strip(), "model": MODEL_ID, "language": LANGUAGE}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"transcription failed: {e}") from e
    finally:
        if path:
            try:
                os.remove(path)
            except OSError:
                pass
