"""
Product KPIs from the chat log (§7 of the architecture doc).

Reads logs/chats.jsonl and prints the containment / quality metrics you'd track
week over week. No model calls — pure aggregation.

Usage:
    python analytics_kpis.py
    python analytics_kpis.py --since 2026-08-01
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

import chatlog

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass


def pct(n: int, d: int) -> str:
    return f"{(100 * n / d):.1f}%" if d else "—"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None, help="ISO date, e.g. 2026-08-01")
    args = ap.parse_args()

    convs = chatlog.load_all()
    if args.since:
        convs = [c for c in convs if c.started_at >= args.since]

    if not convs:
        print("No conversations logged yet. Run the app (or seed_demo_log.py).")
        return

    n = len(convs)
    resolved = [c for c in convs if c.outcome == "resolved"]
    ticket_filed = [c for c in convs if c.outcome == "ticket_filed"]
    linked_dup = [c for c in convs if c.outcome == "linked_duplicate"]
    abandoned = [c for c in convs if c.outcome == "abandoned"]
    thumbs_up = [c for c in convs if c.thumbs == "up"]
    thumbs_down = [c for c in convs if c.thumbs == "down"]
    any_refusal = [c for c in convs if "refused" in c.failure_signals]
    repeat_q = [c for c in convs if "repeated_question" in c.failure_signals]
    grounding_catch = [c for c in convs if "grounding_failed" in c.failure_signals]

    total_q = sum(c.question_count for c in convs)

    print(f"\nSugboDoc assistant — KPIs over {n} conversations")
    print("=" * 52)
    print(f"  containment (resolved, no ticket)   {pct(len(resolved), n)}")
    print(f"  ticket-filed rate                   {pct(len(ticket_filed), n)}")
    print(f"  duplicate-linked rate               {pct(len(linked_dup), n)}")
    print(f"  abandoned rate                      {pct(len(abandoned), n)}")
    print("-" * 52)
    print(f"  thumbs-up rate                      {pct(len(thumbs_up), len(thumbs_up) + len(thumbs_down))}")
    print(f"  conversations with >=1 refusal      {pct(len(any_refusal), n)}")
    print(f"  verification-pass catches           {pct(len(grounding_catch), n)}")
    print(f"  repeat-question rate                {pct(len(repeat_q), n)}")
    print(f"  avg questions / conversation        {total_q / n:.2f}")
    print("-" * 52)

    tri = Counter(c.triage_label for c in convs if c.triage_label)
    if tri:
        print("  triage mix (failed chats):")
        for label, count in tri.most_common():
            print(f"    {label:<16} {count:>3}  {pct(count, sum(tri.values()))}")

    cats = Counter(c.ticket_category for c in ticket_filed if c.ticket_category)
    if cats:
        print("  ticket categories:")
        for cat, count in cats.most_common():
            print(f"    {cat:<16} {count:>3}")
    print()


if __name__ == "__main__":
    main()
