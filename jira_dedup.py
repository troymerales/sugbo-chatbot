"""
Ticket dedup (§3 of the architecture doc) — the one place the bot reads Jira, and
only once per ticket submission.

Pull recent open assistant-filed issues, embed their summary+description, embed
the draft, and flag the closest match if cosine similarity clears the threshold.
Stops the backlog filling with ten copies of the same bug.
"""

from __future__ import annotations

from dataclasses import dataclass

import config
import jira_client
from llm import LLMError, QuotaError, embed


@dataclass(frozen=True)
class DuplicateMatch:
    key: str
    summary: str
    similarity: float


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def find_duplicate(draft_subject: str, draft_summary: str) -> DuplicateMatch | None:
    """Return the closest existing open ticket if it clears the threshold, else None."""
    if not jira_client.jira_configured():
        return None
    try:
        existing = jira_client.list_recent_open_issues()
    except Exception:  # noqa: BLE001 - dedup is best-effort, never block a ticket
        return None
    if not existing:
        return None

    draft_text = f"{draft_subject}\n{draft_summary}".strip()
    corpus = [f"{it['summary']}\n{it['description']}".strip() for it in existing]

    try:
        vectors = embed([draft_text, *corpus])
    except (LLMError, QuotaError):
        return None

    draft_vec, existing_vecs = vectors[0], vectors[1:]
    best: DuplicateMatch | None = None
    for it, vec in zip(existing, existing_vecs):
        sim = _cosine(draft_vec, vec)
        if best is None or sim > best.similarity:
            best = DuplicateMatch(it["key"], it["summary"], sim)

    if best and best.similarity >= config.DEDUP_SIMILARITY_THRESHOLD:
        return best
    return None
