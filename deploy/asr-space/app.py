"""
Gradio + FastAPI for Bisaya/Cebuano Whisper on free HuggingFace Spaces.
Exposes both a Gradio UI and a /transcribe API endpoint for Streamlit Cloud.

Environment (set as Space "Variables and secrets"):
    MODEL_ID        default troxyz1268/whisper-small-bisaya
    ASR_LANGUAGE    default "tl"  (Whisper's closest code to Cebuano)
"""

from __future__ import annotations

import os
import tempfile

import gradio as gr
from fastapi import FastAPI, HTTPException
from transformers import pipeline

MODEL_ID = os.environ.get("MODEL_ID", "troxyz1268/whisper-small-bisaya")
LANGUAGE = os.environ.get("ASR_LANGUAGE", "tl")

_pipe = None


def _get_pipe():
    global _pipe
    if _pipe is None:
        _pipe = pipeline(
            "automatic-speech-recognition",
            model=MODEL_ID,
            chunk_length_s=30,
            stride_length_s=5,
        )
    return _pipe


def transcribe_audio(audio_file):
    """Transcribe audio file to text. Used by Gradio UI and API."""
    if audio_file is None:
        return "No audio provided"
    try:
        out = _get_pipe()(
            audio_file, generate_kwargs={"language": LANGUAGE, "task": "transcribe"}
        )
        text = (out.get("text", "") if isinstance(out, dict) else "") or ""
        return text.strip()
    except Exception as e:
        return f"Error: {str(e)}"


# Gradio interface for the UI
demo = gr.Interface(
    fn=transcribe_audio,
    inputs=gr.Audio(type="filepath", label="Upload audio"),
    outputs=gr.Textbox(label="Transcript"),
    title="Bisaya/Cebuano Speech-to-Text",
    description=f"Powered by {MODEL_ID}",
)

# Wrap in FastAPI to add the /transcribe endpoint for Streamlit
app = gr.mount_gradio_app(FastAPI(), demo, path="/")


@app.post("/transcribe")
async def transcribe_endpoint(request):
    """API endpoint for raw audio bytes (used by Streamlit)."""
    audio = await request.body()
    if not audio:
        raise HTTPException(status_code=400, detail="empty request body")

    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fh:
            fh.write(audio)
            path = fh.name
        text = transcribe_audio(path)
        return {"text": text, "model": MODEL_ID, "language": LANGUAGE}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"transcription failed: {e}") from e
    finally:
        if path:
            try:
                os.remove(path)
            except OSError:
                pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
