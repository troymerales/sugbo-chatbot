"""
Ticket drafting (§3 of the architecture doc).

One model call turns a failed conversation into a structured draft the user
reviews before it is filed. Tracked metrics (see eval harness): how often the
draft is accepted with only minor edits, and the edit distance between draft and
final.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import config
from llm import LLMError, QuotaError, generate

CATEGORIES = (
    "Scheduling", "Patients", "Clinical", "Billing",
    "Immunization", "Staff/Admin", "Account", "Other",
)

_RUBRIC = f"""Draft a support ticket from a failed SugboDoc support conversation.

Return JSON only:
{{"subject": "<one short line, <=80 chars>",
  "category": "<one of: {', '.join(CATEGORIES)}>",
  "summary": "<2-4 sentences: what the user wanted, what they already tried, and
   what is blocking them>"}}"""


@dataclass(frozen=True)
class TicketDraft:
    subject: str
    category: str
    summary: str


def draft_ticket(transcript: str) -> TicketDraft:
    try:
        raw = generate(
            f"CONVERSATION:\n{transcript}",
            system=_RUBRIC,
            model=config.UTILITY_MODEL,
            temperature=0.2,
            json_mode=True,
        )
        data = json.loads(raw)
        category = data.get("category", "Other")
        if category not in CATEGORIES:
            category = "Other"
        return TicketDraft(
            subject=str(data.get("subject", "")).strip(),
            category=category,
            summary=str(data.get("summary", "")).strip(),
        )
    except (LLMError, QuotaError, json.JSONDecodeError, TypeError):
        return TicketDraft("SugboDoc support request", "Other", "")
