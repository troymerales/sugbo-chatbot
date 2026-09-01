"""
Failure mining (§7 of the architecture doc).

Take every failed conversation from the log, embed the user's questions, cluster
them with HDBSCAN, label each cluster with the model, score it by impact
(how many users x how stuck they were x how recent), and write the ranked
doc-gap queue that the docs-maintenance loop (docs_loop.py) consumes.

Usage:
    python -m analytics.analytics_cluster
    python -m analytics.analytics_cluster --min-cluster-size 2
"""

from __future__ import annotations

# Allow `python analytics/analytics_cluster.py` as well as `python -m ...`.
if not __package__:
    import pathlib
    import sys as _sys

    _sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone

import config
from core import chatlog, cli, knowledge
from core.llm import LLMError, QuotaError, embed, generate

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass


def _recency_weight(started_at: str) -> float:
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return 0.5
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    days = max(0.0, (datetime.now(timezone.utc) - started).total_seconds() / 86400)
    return math.exp(-days / 30.0)  # ~1 today, ~0.37 at 30 days


def _cluster(vectors: list[list[float]], min_cluster_size: int) -> list[int]:
    """Return a cluster label per vector (-1 = noise). Falls back for tiny n."""
    n = len(vectors)
    if n < max(4, min_cluster_size + 1):
        return [0] * n  # not enough data to cluster — treat as one group
    try:
        import numpy as np
        from sklearn.cluster import HDBSCAN

        X = np.array(vectors, dtype=float)
        # L2-normalise so euclidean distance tracks cosine distance
        norms = np.linalg.norm(X, axis=1, keepdims=True)
        X = X / np.clip(norms, 1e-12, None)
        model = HDBSCAN(
            min_cluster_size=min_cluster_size,
            min_samples=1,
            cluster_selection_epsilon=0.0,
        )
        labels = model.fit_predict(X).tolist()
        if all(lbl == -1 for lbl in labels):
            # HDBSCAN found no density (common with few points or weak
            # embeddings) — fall back to treating everything as one gap.
            return [0] * n
        return labels
    except ImportError:
        print("  (scikit-learn/numpy not installed — falling back to one group)")
        return [0] * n


def _label_cluster(questions: list[str]) -> dict:
    sample = "\n".join(f"- {q}" for q in questions[:12])
    titles = ", ".join(knowledge.section_titles())
    try:
        raw = generate(
            f"These are user questions the SugboDoc assistant could not answer:\n\n{sample}\n\n"
            f"Existing doc sections: {titles}",
            system=(
                "Summarise the shared unmet need in these questions. JSON only: "
                '{"label": "<=8 words", "gap": "one sentence on what the docs are missing", '
                '"suggested_sections": ["existing section title to expand, or a new title"]}'
            ),
            model=config.UTILITY_MODEL, temperature=0.2, json_mode=True,
        )
        data = json.loads(raw)
        return {
            "label": str(data.get("label", "unlabelled")),
            "gap": str(data.get("gap", "")),
            "suggested_sections": list(data.get("suggested_sections", []))[:3],
        }
    except (LLMError, json.JSONDecodeError, TypeError):
        return {"label": "unlabelled cluster", "gap": "", "suggested_sections": []}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-cluster-size", type=int, default=2)
    cli.add_llm_flags(ap)
    args = ap.parse_args()
    cli.apply_llm_flags(args)

    if config.LLM_BACKEND == "gemini" and not config.get_api_key():
        raise SystemExit("GEMINI_API_KEY is not set (see .env.example). Or run --mock.")

    convs = [c for c in chatlog.load_all() if c.failed]
    if not convs:
        print("No failed conversations in the log yet.")
        return

    # one representative question per failed conversation (the first one)
    items = [(c.conversation_id, c.first_user_question(), c.question_count,
              _recency_weight(c.started_at)) for c in convs if c.first_user_question()]
    print(f"Embedding {len(items)} failed questions…")
    vectors = embed([q for _, q, _, _ in items])

    labels = _cluster(vectors, args.min_cluster_size)

    groups: dict[int, list[int]] = defaultdict(list)
    for idx, lbl in enumerate(labels):
        groups[lbl].append(idx)

    clusters = []
    for lbl, idxs in groups.items():
        if lbl == -1:
            continue
        qs = [items[i][1] for i in idxs]
        stuck = sum(items[i][2] for i in idxs) / len(idxs)
        recency = sum(items[i][3] for i in idxs) / len(idxs)
        impact = round(len(idxs) * (stuck / config.QUESTIONS_BEFORE_TICKET) * recency, 3)
        meta = _label_cluster(qs)
        clusters.append({
            **meta,
            "size": len(idxs),
            "avg_questions_before_giving_up": round(stuck, 2),
            "recency_weight": round(recency, 3),
            "impact": impact,
            "example_questions": qs[:5],
            "conversation_ids": [items[i][0] for i in idxs],
        })

    clusters.sort(key=lambda c: c["impact"], reverse=True)
    noise = [items[i][1] for i in groups.get(-1, [])]

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "failed_conversations": len(convs),
        "clusters": clusters,
        "unclustered_questions": noise,
    }
    config.DOC_GAP_QUEUE_PATH.write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\n{len(clusters)} clusters (impact-ranked):\n")
    for c in clusters:
        print(f"  [{c['impact']:>6}]  {c['label']}  (n={c['size']})")
        print(f"           gap: {c['gap']}")
    if noise:
        print(f"\n  {len(noise)} unclustered one-off questions")
    print(f"\nwrote {config.DOC_GAP_QUEUE_PATH}")


if __name__ == "__main__":
    try:
        main()
    except QuotaError as exc:
        raise SystemExit(str(exc))
