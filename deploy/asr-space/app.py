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
    print(f"[DEBUG] POST /transcribe received, file: {file.filename}", flush=True)

    if not file:
        print("[DEBUG] No file provided", flush=True)
        raise HTTPException(status_code=400, detail="No audio file provided")

    try:
        print("[DEBUG] Loading pipeline...", flush=True)
        pipe = get_pipe()

        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
            content = await file.read()
            temp_file.write(content)
            temp_path = temp_file.name

        print(f"[DEBUG] Temp file saved: {temp_path}, size: {len(content)} bytes", flush=True)

        try:
            print("[DEBUG] Running transcription...", flush=True)
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

            print(f"[DEBUG] Transcription complete: {text[:50]}...", flush=True)
            return {
                "text": text.strip(),
                "model": MODEL_ID,
                "language": LANGUAGE,
            }

        finally:
            # Clean up temp file
            if os.path.exists(temp_path):
                os.remove(temp_path)
                print(f"[DEBUG] Cleaned up temp file", flush=True)

    except Exception as e:
        print(f"[DEBUG] ERROR: {type(e).__name__}: {e}", flush=True)
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
