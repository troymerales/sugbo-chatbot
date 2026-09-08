# Deploy the ASR endpoint (HF Space) and wire it to the app

Local dev is unaffected — with `transformers` installed the app keeps running
Whisper in-process. This is only for the **deployed** app (Streamlit Community
Cloud), where `torch` doesn't fit.

## 1. Create the Space

1. https://huggingface.co/new-space
2. Owner: you · Name: `sugbodoc-asr` (anything) · License: your choice
3. **SDK: Docker** · Template: Blank · Hardware: **CPU basic (free)**
4. Visibility: **Public** is simplest. Private also works — see step 4.
5. Create.

## 2. Push these files

The Space is a git repo. From the SugboDoc repo root:

```bash
git clone https://huggingface.co/spaces/<user>/sugbodoc-asr /tmp/sugbodoc-asr
cp deploy/asr-space/{Dockerfile,app.py,requirements.txt,README.md} /tmp/sugbodoc-asr/
cd /tmp/sugbodoc-asr
git add -A && git commit -m "Bisaya Whisper ASR endpoint" && git push
```

(Or drag the four files into the Space's **Files** tab in the browser.)

The first build takes ~10–15 min (it bakes the model into the image). Watch
**Logs**. When it says `Uvicorn running on ...`, open the Space URL — you should
get `{"status":"ok",...}`.

## 3. Smoke-test it

```bash
curl -X POST https://<user>-sugbodoc-asr.hf.space/transcribe \
     -H "Content-Type: audio/mpeg" \
     --data-binary @trial/audio_output/1_1.mp3
# -> {"text":"...","model":"troxyz1268/whisper-small-bisaya","language":"tl"}
```

## 4. Wire the app

In **Streamlit Community Cloud → your app → Settings → Secrets**, add:

```toml
ASR_API_URL = "https://<user>-sugbodoc-asr.hf.space/transcribe"
```

Private Space? Also set, in **both** the Space variables **and** the app secrets:

```toml
ASR_AUTH_TOKEN = "<a long random string you pick>"
```

Save. The app redeploys. `settings.asr_available` is now true because
`ASR_API_URL` is set, and `stt.asr.transcribe` POSTs the audio to the Space.

For local `.streamlit/secrets.toml` you can leave `ASR_API_URL` unset — local
Whisper is used — or set it to test the hosted path.

## Notes

- **Cold start:** a free Space sleeps after ~48 h idle and takes ~30–60 s to wake.
  The app retries through that (`stt/asr.py` → `_transcribe_via_api`), so the
  first transcription after a long gap just takes longer.
- **Cost:** free CPU Space = $0. No GPU needed for `whisper-small` on short
  consult clips (a few seconds of audio → a few seconds of compute).
- **Updating the model:** push a new `MODEL_ID` as a Space variable, or edit the
  default in `app.py` / `Dockerfile` and re-push.
