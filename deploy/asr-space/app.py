import os
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import tempfile
from transformers import pipeline

app = FastAPI()

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


@app.get("/")
async def health():
    return {"status": "ok"}


@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    if not file:
        raise HTTPException(status_code=400, detail="No audio file provided")

    try:
        pipe = get_pipe()

        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_path = temp_file.name

        try:
            result = pipe(
                temp_path,
                generate_kwargs={
                    "language": LANGUAGE,
                    "task": "transcribe",
                },
            )

            text = ""
            if isinstance(result, dict):
                text = result.get("text", "") or ""

            return {
                "text": text.strip(),
                "model": MODEL_ID,
                "language": LANGUAGE,
            }

        finally:
            # Clean up temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)

    except Exception as e:
        print(f"Transcription error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
