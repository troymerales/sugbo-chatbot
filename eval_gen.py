"""
Grow the eval set (§6) with synthetic questions generated from each doc section.

For every ## / ### section, ask the model for a couple of realistic user
questions it should be able to answer from that section. Writes candidate JSONL
lines to eval_generated.jsonl — review them, then merge the good ones into
eval_set.jsonl. Synthetic cases supplement, never replace, the hand-authored set
(especially the must-refuse slice, which has to be authored).

Usage:
    python eval_gen.py                 # 2 questions per section
    python eval_gen.py --per 1
"""

from __future__ import annotations

import argparse
import json
import re
import sys

import cli
import config
import knowledge
from llm import LLMError, QuotaError, generate

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

OUT_PATH = config.ROOT / "eval_generated.jsonl"

_RUBRIC = """You write test questions for a SugboDoc support assistant.

Given one section of the product documentation, write {per} distinct questions a
real user would ask that this section answers. For each, list 2-3 short exact
strings from the section that a correct answer must contain (UI labels, field
names — not whole sentences).

JSON only:
{{"cases": [{{"question": "...", "must_include": ["...", "..."]}}]}}"""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per", type=int, default=2)
    cli.add_llm_flags(ap)
    args = ap.parse_args()
    cli.apply_llm_flags(args)

    if config.LLM_BACKEND == "gemini" and not config.get_api_key():
        raise SystemExit("GEMINI_API_KEY is not set (see .env.example). Or run --mock.")

    rubric = _RUBRIC.format(per=args.per)
    written = 0
    with OUT_PATH.open("w", encoding="utf-8") as fh:
        for sec in knowledge.content_sections():
            if len(sec.body) < 120:
                continue
            try:
                raw = generate(
                    f"SECTION: {sec.title}\n\n{sec.body}",
                    system=rubric, model=config.UTILITY_MODEL,
                    temperature=0.4, json_mode=True,
                )
                cases = json.loads(raw).get("cases", [])
            except (LLMError, json.JSONDecodeError, TypeError) as exc:
                print(f"  skip {sec.title!r}: {exc}")
                continue

            for i, c in enumerate(cases):
                line = {
                    "id": f"gen-{slug(sec.title)}-{i}",
                    "question": c.get("question", "").strip(),
                    "expected_behavior": "answer",
                    "expected_section": sec.title,
                    "must_include": [t for t in c.get("must_include", []) if t][:3],
                }
                if line["question"]:
                    fh.write(json.dumps(line, ensure_ascii=False) + "\n")
                    written += 1
            print(f"  {sec.title:<45} +{len(cases)}")

    print(f"\nwrote {written} candidate cases to {OUT_PATH.name} — review, then "
          "merge into eval_set.jsonl")


if __name__ == "__main__":
    try:
        main()
    except QuotaError as exc:
        raise SystemExit(str(exc))
