"""
Gradio interface for Bisaya/Cebuano Whisper on free HuggingFace Spaces.
Streamlit calls the Gradio API endpoint: /api/predict/

Environment (set as Space "Variables and secrets"):
    MODEL_ID        default troxyz1268/whisper-small-bisaya
    ASR_LANGUAGE    default "tl"  (Whisper's closest code to Cebuano)
"""

from __future__ import annotations

import os

import gradio as gr
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
    """Transcribe audio file to text."""
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


# Gradio interface
demo = gr.Interface(
    fn=transcribe_audio,
    inputs=gr.Audio(type="filepath", label="Upload audio"),
    outputs=gr.Textbox(label="Transcript"),
    title="Bisaya/Cebuano Speech-to-Text",
    description=f"Powered by {MODEL_ID}",
)

if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True,
        show_api=True,
    )
