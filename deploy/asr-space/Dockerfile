# Hugging Face Docker Space. HF builds this, runs it as UID 1000, and routes
# https://<user>-<space>.hf.space -> container port 7860.
FROM python:3.11-slim

# ffmpeg: transformers' ASR pipeline shells out to it to decode webm/mp3/m4a.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    HF_HOME=/home/user/.cache/huggingface \
    PYTHONUNBUFFERED=1

WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .

# Warm the model into the image layer so the first request isn't a cold download.
RUN python -c "from transformers import pipeline; \
    pipeline('automatic-speech-recognition', model='troxyz1268/whisper-small-bisaya')"

EXPOSE 7860
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
