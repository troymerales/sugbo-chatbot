"""
Shared command-line flags for the batch scripts (eval, analytics, docs loop).

Every script that calls a model accepts:
    --mock       use _mock_backend (no API key, no quota)
    --offline    only serve from the cache; raise on a miss
    --no-cache   bypass the response cache entirely

These flip config values that llm.py reads live on each call.
"""

from __future__ import annotations

import argparse

import config


def add_llm_flags(ap: argparse.ArgumentParser) -> None:
    g = ap.add_argument_group("model backend")
    g.add_argument("--mock", action="store_true",
                   help="use the offline mock backend (no API key / quota)")
    g.add_argument("--offline", action="store_true",
                   help="only use cached responses; error on a cache miss")
    g.add_argument("--no-cache", action="store_true",
                   help="ignore the response cache for this run")


def apply_llm_flags(args: argparse.Namespace) -> None:
    if getattr(args, "mock", False):
        config.LLM_BACKEND = "mock"
    if getattr(args, "offline", False):
        config.LLM_OFFLINE = True
    if getattr(args, "no_cache", False):
        config.LLM_CACHE = False
