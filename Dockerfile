# syntax=docker/dockerfile:1
#
# Container image for the SugboDoc FastAPI backend (api/service.py), which also
# serves the browser widget (web/index.html) at "/".
#
# One stage, on purpose: the app is pure-Python with wheels for every dependency,
# so a build stage would save little and cost clarity. See study/01-containers-and-docker.md.
#
#   docker build -t sugbodoc .
#   docker run --rm -p 8000:8000 --env-file .env sugbodoc
#
# Render builds this same file. Render injects $PORT at runtime; locally it
# defaults to 8000.

FROM python:3.12-slim

# - PYTHONDONTWRITEBYTECODE: no .pyc files (the layer is read-only anyway)
# - PYTHONUNBUFFERED: flush stdout immediately so logs show up in real time
# - PIP_NO_CACHE_DIR: smaller image, we never pip again inside the container
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, in their own layer: this layer is only rebuilt when a
# requirements file changes, not on every code edit.
COPY requirements.txt requirements-service.txt ./
RUN pip install --upgrade pip && pip install -r requirements-service.txt

# Then the application code.
COPY . .

# Run as a non-root user. If the image is ever compromised, the process has no
# rights to the rest of the (host or container) system. `logs/` must be writable
# because config.py creates it on import (the LLM response cache lives there).
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/logs \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Shell form so ${PORT:-8000} is expanded. One uvicorn worker: the free instance
# has 0.1 CPU / 512 MB — a second worker would just contend. State that must be
# shared (sessions, chat logs) lives in Postgres, not in the worker.
CMD uvicorn api.service:app --host 0.0.0.0 --port ${PORT:-8000}
