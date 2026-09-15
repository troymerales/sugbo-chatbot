# SugboDoc Bisaya ASR (Automatic Speech Recognition)

FastAPI service for transcribing Bisaya/Cebuano audio using a fine-tuned Whisper model.

## Setup

### Requirements
- Python 3.10+
- ffmpeg
- torch, transformers, librosa, soundfile

### Installation

```bash
cd deploy/asr-space
pip install -r requirements.txt
```

### Running Locally

```bash
python app.py
# Starts FastAPI on http://localhost:8000
```

### Exposing via Cloudflare Tunnel

In a separate terminal:

```bash
cloudflared tunnel --url http://localhost:8000
# Output: https://your-tunnel-url.trycloudflare.com
```

## API Endpoints

### Health Check
```
GET /
```
Returns: `{"status": "ok"}`

### Transcribe Audio
```
POST /transcribe
```

**Request:** Multipart form with `file` field (audio file)

**Response:**
```json
{
  "text": "transcribed text here",
  "model": "troxyz1268/whisper-small-bisaya",
  "language": "tl"
}
```

## Wire to Streamlit Cloud

1. Get your tunnel URL from cloudflared output
2. Go to Streamlit Cloud → Your App → Settings → Secrets
3. Add:
```toml
ASR_API_URL = "https://your-tunnel-url/transcribe"
```
4. Save (auto-redeploy)

## Auto-Start (Windows)

Use `start_asr.bat` in the repo root to start both services:

```bash
start_asr.bat
```

This opens two terminals and starts:
- FastAPI service
- Cloudflare tunnel

## Notes

- Your machine must stay **on 24/7** for the service to remain live
- Model downloads on first run (~2GB)
- Subsequent requests take ~2-3 seconds
