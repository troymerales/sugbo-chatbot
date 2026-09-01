"""
Docs-maintenance loop (§4 of the architecture doc).

Runs on your schedule, not per request. Takes the impact-ranked doc-gap queue
(from analytics_cluster.py) plus recently resolved Jira issues, and for the top
gaps drafts a concrete documentation change grounded in the actual failed
conversations. Writes one proposal file per gap to doc_proposals/ for a human to
review, edit, and merge into SugboDoc-Documentation.md.

This is the only path from Jira back to the bot:  Jira -> docs -> bot.

Usage:
    python -m analytics.docs_loop              # top 3 gaps
    python -m analytics.docs_loop --top 5
    python -m analytics.docs_loop --no-jira    # skip the resolved-issues pull
"""

from __future__ import annotations

# Allow `python analytics/docs_loop.py` as well as `python -m analytics.docs_loop`.
if not __package__:
    import pathlib
    import sys as _sys

    _sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import argparse
import json
import sys
from datetime import datetime, timezone

import config
from core import chatlog, cli, knowledge
from core.llm import LLMError, QuotaError, generate

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass


def _load_queue() -> dict:
    if not config.DOC_GAP_QUEUE_PATH.exists():
        raise SystemExit(
            f"{config.DOC_GAP_QUEUE_PATH.name} not found — run analytics_cluster.py first."
        )
    return json.loads(config.DOC_GAP_QUEUE_PATH.read_text(encoding="utf-8"))


def _transcripts_for(conversation_ids: list[str]) -> str:
    by_id = {c.conversation_id: c for c in chatlog.load_all()}
    blocks = []
    for cid in conversation_ids[:6]:
        c = by_id.get(cid)
        if not c:
            continue
        turns = "\n".join(
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in c.messages
        )
        blocks.append(f"--- {cid} (triage: {c.triage_label}) ---\n{turns}")
    return "\n\n".join(blocks)


def _relevant_doc_context(suggested_sections: list[str]) -> str:
    out = []
    for name in suggested_sections:
        sec = knowledge.find_section(name)
        if sec:
            out.append(f"## {sec.title}\n{sec.body}")
    return "\n\n".join(out) if out else "(no existing section matched — this may be new.)"


_RUBRIC = """You maintain the SugboDoc user documentation.

You are given: a cluster of real conversations where the assistant FAILED, the
existing documentation section(s) most related to it, and (optionally) resolved
Jira issues.

Produce a documentation change that would let the assistant answer these
questions next time — but only using information you can actually see in the
conversations or the resolved issues. Do NOT invent UI steps.

If the failures are caused by a product bug or missing feature (not a docs gap),
say so and stop — recommend it stays a Jira ticket instead.

Reply in markdown:

### Verdict
<docs-gap | product-bug | needs-more-info> — one sentence why.

### Proposed doc change
<the exact markdown to add or replace, with the target section heading. If you
lack the concrete steps, list the specific questions a SME must answer to write
this section.>

### Eval case to add first
<one JSON line for eval_set.jsonl covering this gap>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--no-jira", action="store_true")
    cli.add_llm_flags(ap)
    args = ap.parse_args()
    cli.apply_llm_flags(args)

    if config.LLM_BACKEND == "gemini" and not config.get_api_key():
        raise SystemExit("GEMINI_API_KEY is not set (see .env.example). Or run --mock.")

    queue = _load_queue()
    clusters = queue.get("clusters", [])[: args.top]
    if not clusters:
        print("Queue has no clusters. Nothing to draft.")
        return

    resolved_block = ""
    if not args.no_jira:
        try:
            from core import jira_client
            if jira_client.jira_configured():
                issues = jira_client.list_resolved_issues(days=60)
                if issues:
                    resolved_block = "\n".join(
                        f"- [{i['key']}] {i['summary']}" for i in issues[:20]
                    )
                    print(f"pulled {len(issues)} recently resolved Jira issues\n")
        except Exception as exc:  # noqa: BLE001
            print(f"(skipping Jira pull: {exc})\n")

    config.DOC_PROPOSALS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")

    for rank, cluster in enumerate(clusters, 1):
        print(f"[{rank}] drafting for: {cluster['label']}  (impact {cluster['impact']})")
        prompt = (
            f"CLUSTER: {cluster['label']}\n"
            f"GAP: {cluster.get('gap', '')}\n"
            f"IMPACT: {cluster['impact']} (n={cluster['size']})\n\n"
            f"RELATED EXISTING DOCS:\n{_relevant_doc_context(cluster.get('suggested_sections', []))}\n\n"
            f"FAILED CONVERSATIONS:\n{_transcripts_for(cluster.get('conversation_ids', []))}\n\n"
            f"RECENTLY RESOLVED JIRA ISSUES:\n{resolved_block or '(none pulled)'}"
        )
        try:
            body = generate(prompt, system=_RUBRIC, model=config.ANSWER_MODEL, temperature=0.3)
        except QuotaError:
            raise
        except LLMError as exc:
            body = f"(draft failed: {exc})"

        slug = "".join(ch if ch.isalnum() else "-" for ch in cluster["label"].lower())[:40].strip("-")
        path = config.DOC_PROPOSALS_DIR / f"{stamp}-{rank:02d}-{slug}.md"
        path.write_text(
            f"# Doc proposal: {cluster['label']}\n\n"
            f"- Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
            f"- Impact score: {cluster['impact']}  ·  conversations: {cluster['size']}\n"
            f"- Source conversations: {', '.join(cluster.get('conversation_ids', []))}\n\n"
            f"## Example failed questions\n\n"
            + "\n".join(f"- {q}" for q in cluster.get("example_questions", []))
            + f"\n\n---\n\n{body}\n",
            encoding="utf-8",
        )
        print(f"    wrote {path.relative_to(config.ROOT)}")

    print(
        "\nNext: review each proposal, add its eval case to evaluation/eval_set.jsonl,\n"
        "then run\n"
        "  python -m evaluation.eval_run\n"
        "and only merge the doc change if the scorecard doesn't regress."
    )


if __name__ == "__main__":
    try:
        main()
    except QuotaError as exc:
        raise SystemExit(str(exc))
