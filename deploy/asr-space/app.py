import os
import gradio as gr
from transformers import pipeline

MODEL_ID = os.environ.get(
    "MODEL_ID",
    "troxyz1268/whisper-small-bisaya"
)

LANGUAGE = os.environ.get("ASR_LANGUAGE", "tl")

_pipe = None


def get_pipe():
    global _pipe

    if _pipe is None:
        print(f"Loading model: {MODEL_ID}", flush=True)

        _pipe = pipeline(
            "automatic-speech-recognition",
            model=MODEL_ID,
            chunk_length_s=30,
            stride_length_s=5,
        )

        print("Model loaded.", flush=True)

    return _pipe


def transcribe_audio(audio_file):
    if audio_file is None:
        return "No audio provided"

    try:
        pipe = get_pipe()

        result = pipe(
            audio_file,
            generate_kwargs={
                "language": LANGUAGE,
                "task": "transcribe",
            },
        )

        return result["text"].strip()

    except Exception as e:
        print(f"Transcription error: {e}", flush=True)
        return f"Error: {e}"


demo = gr.Interface(
    fn=transcribe_audio,
    inputs=gr.Audio(
        type="filepath",
        label="Upload audio",
    ),
    outputs=gr.Textbox(
        label="Transcript",
    ),
    title="Bisaya/Cebuano Speech-to-Text",
    api_name="transcribe",
)


if __name__ == "__main__":
    print("Starting Gradio app...", flush=True)

    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        ssr_mode=False,
    )