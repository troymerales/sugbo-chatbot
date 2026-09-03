"""
Central configuration for the SugboDoc assistant.

Every other module imports paths, model names and thresholds from here so the
runtime bot, the eval harness and the analytics scripts all agree on one setup.
`.env` is loaded exactly once, here.
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

SYSTEM_PROMPT_PATH = DOCS_DIR / "system-prompt.md"

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
DOC_GAP_QUEUE_PATH = LOG_DIR / "doc_gap_queue.json"

EVAL_DIR = ROOT / "evaluation"
EVAL_SET_PATH = EVAL_DIR / "eval_set.jsonl"
EVAL_GENERATED_PATH = EVAL_DIR / "eval_generated.jsonl"
SCORECARD_MD_PATH = EVAL_DIR / "eval_scorecard.md"
SCORECARD_JSON_PATH = EVAL_DIR / "eval_scorecard.json"

DOC_PROPOSALS_DIR = ROOT / "doc_proposals"

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
# Database  (FastAPI backend persistence — service.py + chatlog.py)
# --------------------------------------------------------------------------- #

# SQLAlchemy URL. When unset, the backend keeps sessions in an in-process dict
# and writes finished conversations to logs/chats.jsonl — fine for the Streamlit
# demo and the offline test-suite. When set, live sessions live in a
# `conversations` table and finished conversations in `chat_logs`, so several
# uvicorn workers can share state and nothing is lost on restart. PostgreSQL is
# the intended target:
#     postgresql+psycopg://user:pass@localhost:5432/sugbodoc
# Run `python db_init.py` once to create the schema.
DATABASE_URL = os.environ.get("DATABASE_URL") or None

# Echo every SQL statement to stderr (debugging only).
DB_ECHO = os.environ.get("DB_ECHO", "0") == "1"

# SQLAlchemy pool sizing. Deliberately small: a managed pooler (Supabase's free
# session pooler) caps total connections, and one Render instance opening a big
# pool can starve the others / the analytics scripts. pool_size = kept-open
# connections, max_overflow = extra it may open under load then discard.
DB_POOL_SIZE = int(os.environ.get("DB_POOL_SIZE", "5"))
DB_MAX_OVERFLOW = int(os.environ.get("DB_MAX_OVERFLOW", "2"))

# --------------------------------------------------------------------------- #
# Deployment / runtime  (api/service.py — see docs/architecture.md)
# --------------------------------------------------------------------------- #

# Free-text environment tag. Surfaced in logs and GET /healthz so you can tell a
# prod incident from a local one at a glance. No behaviour depends on it.
ENV = os.environ.get("ENV", "dev")

# Backend log verbosity. Logs are written to stdout (12-factor) so the hosting
# platform captures them; nothing is written to a log file in the cloud.
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# Cross-origin browsers allowed to call the API. The bundled widget is served
# from the same origin, so this stays empty unless you embed the widget on
# another site. Comma-separated. "*" is intentionally NOT a supported default.
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]

# Per-client-IP request cap (requests / minute), a cheap backstop against
# burning the Gemini free-tier quota. In-process, per-instance, resets on
# redeploy. 0 disables it. See the RateLimitMiddleware in api/service.py.
RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "30"))

# Sentry DSN for error tracking. Unset (default) => sentry-sdk is not imported
# and nothing is sent anywhere.
SENTRY_DSN = os.environ.get("SENTRY_DSN") or None

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
