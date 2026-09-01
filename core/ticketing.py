"""
Ticket drafting (§3 of the architecture doc).

The ticket the user reviews is now built **without a model call** to keep LLM
cost down: the subject seeds from the user's first question, the summary is left
for the user to fill in. `draft_ticket()` (an LLM-drafted version) is kept for
reference but is no longer wired into the runtime.

`due_date` comes straight from a date picker in the UI — no free-text parsing —
so this module only validates it and derives an urgency from how soon it is.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date

import config
from core.llm import LLMError, QuotaError, generate

CATEGORIES = (
    "Scheduling", "Patients", "Clinical", "Billing",
    "Immunization", "Staff/Admin", "Account", "Other",
)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FIRST_USER_LINE = re.compile(r"^User:\s*(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class TicketDraft:
    subject: str
    category: str
    summary: str


def default_draft(transcript: str) -> TicketDraft:
    """A ticket draft with no model call: subject = the user's first question."""
    m = _FIRST_USER_LINE.search(transcript or "")
    subject = (m.group(1).strip() if m else "").strip()
    return TicketDraft(subject=subject[:80] or "SugboDoc support request",
                       category="Other", summary="")


def as_iso_date(text: str | None) -> str | None:
    """Return `text` if it is a real YYYY-MM-DD date, else None."""
    text = (text or "").strip()
    if not _ISO_DATE.match(text):
        return None
    try:
        date.fromisoformat(text)
    except ValueError:
        return None
    return text


def urgency_for_date(iso_date: str | None, *, today: date | None = None) -> str:
    """'high' | 'medium' | 'low' from how soon a target date is (default 'medium')."""
    if not iso_date:
        return "medium"
    try:
        target = date.fromisoformat(iso_date)
    except ValueError:
        return "medium"
    days = (target - (today or date.today())).days
    if days <= 3:
        return "high"
    if days <= 14:
        return "medium"
    return "low"


# --------------------------------------------------------------------------- #
# LLM-drafted ticket — kept for reference, NOT called by the runtime.
# --------------------------------------------------------------------------- #

_RUBRIC = f"""Draft a support ticket from a failed SugboDoc support conversation.

Return JSON only:
{{"subject": "<one short line, <=80 chars>",
  "category": "<one of: {', '.join(CATEGORIES)}>",
  "summary": "<2-4 sentences: what the user wanted, what they already tried, and
   what is blocking them>"}}"""


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
