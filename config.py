"""
Central configuration for the SugboDoc chatbot (`core/`, `assistant/`).

Paths, model names, thresholds and feature toggles live here. `.env` is loaded
exactly once, here. The STT side has its own `stt/config.py`.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

ROOT = Path(__file__).resolve().parent

# Load .env from the project root explicitly — not "wherever the process was
# started from". Running `uvicorn api.service:app` from another directory would
# otherwise silently miss it, and the backend would fall back to in-memory
# sessions + logs/chats.jsonl instead of Postgres.
load_dotenv(ROOT / ".env", override=True)

DOCS_DIR = ROOT / "docs"

# The knowledge base the assistant is grounded on. The full document is
# git-ignored (swap yours in at `docs/SugboDoc-Documentation.md`); the committed
# `.sample.md` excerpt is the fallback so a fresh clone / CI runs out of the box.
DOCS_PATH = DOCS_DIR / "SugboDoc-Documentation.md"
if not DOCS_PATH.exists():
    DOCS_PATH = DOCS_DIR / "SugboDoc-Documentation.sample.md"

# logs/ holds the local chat-log JSONL + its CSV mirror and the LLM response
# cache. On a read-only or ephemeral host (Streamlit Community Cloud) fall back
# to a temp dir so `import config` never fails — there the durable store is
# Postgres (DATABASE_URL) and these files are only a cache / local mirror.
LOG_DIR = ROOT / "logs"
try:
    LOG_DIR.mkdir(exist_ok=True)
except OSError:
    import tempfile

    LOG_DIR = Path(tempfile.gettempdir()) / "sugbodoc-logs"
    LOG_DIR.mkdir(exist_ok=True)

CHAT_LOG_PATH = LOG_DIR / "chats.jsonl"
# Local flattened mirror of every logged conversation, written even when the
# primary store is Postgres. For eyeballing in a spreadsheet; never read back.
CHAT_LOG_CSV_PATH = LOG_DIR / "chats.csv"

LLM_CACHE_PATH = LOG_DIR / "llm_cache.sqlite"

# --------------------------------------------------------------------------- #
# Models  (Gemini everywhere — override any of these in .env)
# --------------------------------------------------------------------------- #

# The model that answers users.
ANSWER_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")

# Cheap/fast model for the utility calls: verification pass, triage, ticket draft,
# cluster labelling. Keep it small — these run often.
UTILITY_MODEL = os.environ.get("GEMINI_UTILITY_MODEL", ANSWER_MODEL)

# The eval judge. MUST be a different (ideally stronger) model than ANSWER_MODEL —
# a judge that shares the answer model's blind spots inflates the score.
JUDGE_MODEL = os.environ.get("GEMINI_JUDGE_MODEL", "gemini-pro-latest")

# Embeddings for ticket dedup + failure clustering. Used offline, never per turn.
EMBED_MODEL = os.environ.get("GEMINI_EMBED_MODEL", "gemini-embedding-001")

# --------------------------------------------------------------------------- #
# LLM backend + cache  (these are read live on every call, so scripts can flip
# them at runtime via argparse — see eval_run.py --offline / --mock)
# --------------------------------------------------------------------------- #

# "gemini" = real API.  "mock" = deterministic offline stand-in (_mock_backend.py),
# good enough to exercise every code path without spending quota.
LLM_BACKEND = os.environ.get("LLM_BACKEND", "gemini")

# Cache every model response to logs/llm_cache.sqlite keyed by a hash of the
# request. Re-running the eval on unchanged prompts/docs then costs nothing.
LLM_CACHE = os.environ.get("LLM_CACHE", "1") != "0"

# Refuse to make a live call — raise on any cache miss instead. Lets you iterate
# on the harness/analytics all day against a warm cache with zero requests.
LLM_OFFLINE = os.environ.get("LLM_OFFLINE", "0") == "1"

# --------------------------------------------------------------------------- #
# Chat-log persistence  (core/chatlog.py -> core/chatlog_db.py)
# --------------------------------------------------------------------------- #

# SQLAlchemy URL. Unset -> finished conversations are written to
# logs/chats.jsonl (fine locally + for tests; ephemeral on Community Cloud).
# Set -> they go to the `chat_logs` table (created on first use). Use Supabase's
# Session-pooler string (IPv4):
#     postgresql://postgres.<ref>:<pass>@aws-0-<region>.pooler.supabase.com:5432/postgres
DATABASE_URL = os.environ.get("DATABASE_URL") or None

DB_ECHO = os.environ.get("DB_ECHO", "0") == "1"

# SQLAlchemy pool sizing — kept small, Supabase's free session pooler caps total
# connections per project.
DB_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "5"))
DB_MAX_OVERFLOW = int(os.environ.get("DB_MAX_OVERFLOW", "2"))

# --------------------------------------------------------------------------- #
# Retrieval  (RAG toggle — see core/retrieval.py and core/knowledge.py)
# --------------------------------------------------------------------------- #

# False (default): the whole documentation (~8k tokens) goes in the answer
#   model's system prompt every turn — simplest, and fine at this doc size.
# True: only the top-K most relevant ## / ### sections are retrieved (embedding
#   cosine) and injected. The verification pass and the eval judge still see the
#   full docs, so both modes are drop-in compatible with the rest of the pipeline.
USE_RAG = os.environ.get("USE_RAG", "0") == "1"

# How many sections RAG injects into the answer prompt when USE_RAG is True.
RAG_TOP_K = int(os.environ.get("RAG_TOP_K", "6"))

# --------------------------------------------------------------------------- #
# Answer verification  (core/grounding.py)
# --------------------------------------------------------------------------- #

# After the answer model replies, a second independent model call checks the
# draft answer against the docs and downgrades it to a refusal if a claim isn't
# supported. Catches hallucinated UI labels / steps at the cost of one extra
# Gemini call per question. "1" (default) = on. VERIFY_ANSWERS=0 trades that
# grounding check for speed + half the quota per turn.
VERIFY_ANSWERS = os.environ.get("VERIFY_ANSWERS", "1") != "0"

# --------------------------------------------------------------------------- #
# Behaviour thresholds
# --------------------------------------------------------------------------- #

# After this many user questions in one chat without a thumbs-up, the bot
# proactively offers a ticket ("this is taking a while").
QUESTIONS_BEFORE_TICKET = int(os.environ.get("QUESTIONS_BEFORE_TICKET", "3"))

# Cosine similarity above which a drafted ticket is treated as a duplicate of an
# existing open Jira issue. Tune on real data (§3 of the architecture doc).
DEDUP_SIMILARITY_THRESHOLD = float(os.environ.get("DEDUP_SIMILARITY_THRESHOLD", "0.82"))

# The exact string the bot must emit when it cannot answer from the docs.
REFUSAL_MARKER = "I don't have enough information in my records to answer that"


def get_api_key() -> str | None:
    """Gemini API key from the environment (populated from .env by load_dotenv)."""
    return os.environ.get("GEMINI_API_KEY")
