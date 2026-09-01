"""
Inspect or clear the local LLM response cache (logs/llm_cache.sqlite).

The cache is keyed by a hash of every request (model, system prompt, messages,
temperature, backend). A warm cache lets `eval_run.py --offline` and the
analytics scripts run with zero API calls.

Usage:
    python -m scripts.llm_cache            # show what's cached
    python -m scripts.llm_cache --clear    # wipe it
"""

from __future__ import annotations

# Allow `python scripts/llm_cache.py` as well as `python -m scripts.llm_cache`.
if not __package__:
    import pathlib
    import sys as _sys

    _sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import argparse
import sys

from core import llm

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clear", action="store_true")
    args = ap.parse_args()

    if args.clear:
        n = llm.clear_cache()
        print(f"cleared {n} cached responses")
        return

    s = llm.cache_stats()
    print(f"cache file : {s['path']}")
    print(f"entries    : {s['total']}")
    for kind, count in sorted(s["by_kind"].items()):
        print(f"  {kind:<10} {count}")
    if s["total"] == 0:
        print("\n(empty — run eval_run.py / analytics once online or with --mock to warm it)")


if __name__ == "__main__":
    main()
