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

load_dotenv(override=True)

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

ROOT = Path(__file__).resolve().parent

DOCS_PATH = ROOT / "SugboDoc-Documentation.md"
SYSTEM_PROMPT_PATH = ROOT / "system-prompt.md"

LOG_DIR = ROOT / "logs"
CHAT_LOG_PATH = LOG_DIR / "chats.jsonl"
DOC_GAP_QUEUE_PATH = LOG_DIR / "doc_gap_queue.json"

EVAL_SET_PATH = ROOT / "eval_set.jsonl"
SCORECARD_MD_PATH = ROOT / "eval_scorecard.md"
SCORECARD_JSON_PATH = ROOT / "eval_scorecard.json"

DOC_PROPOSALS_DIR = ROOT / "doc_proposals"

LLM_CACHE_PATH = LOG_DIR / "llm_cache.sqlite"

LOG_DIR.mkdir(exist_ok=True)

# --------------------------------------------------------------------------- #
# Models  (Gemini everywhere — override any of these in .env)
# --------------------------------------------------------------------------- #

# The model that answers users.
ANSWER_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

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
