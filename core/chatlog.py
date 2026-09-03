"""
Structured chat logging (feeds §6 eval and §7 analytics).

A conversation is logged as soon as it goes wrong (outcome `unresolved` — a
thumbs-down, a refusal, or a stuck chat), then the SAME record is updated in
place if it later reaches a terminal state (resolved, ticket filed, linked to a
duplicate, or abandoned). So a user who thumbs-downs but never files a ticket is
still captured, and there's still only one record per conversation. `append()`
is an upsert keyed by `conversation_id`.

Primary store depends on config.DATABASE_URL:
  * unset  -> one JSON object per line in logs/chats.jsonl (the default; fine
             for the Streamlit demo and the tests).
  * set    -> one row per conversation in the `chat_logs` PostgreSQL table
             (see db.py / db_init.py).
Either way the API is the same: `append(record)` / `load_all()`.

Local CSV mirror: every `append()` rewrites config.CHAT_LOG_CSV_PATH
(logs/chats.csv) from the primary store, so it stays one row per conversation.
It's a convenience copy for eyeballing in a spreadsheet — nothing reads it back.
`python -m core.chatlog` rebuilds it explicitly (handy to backfill rows that
were written straight to Supabase).

No PII handling beyond what the user typed. If this runs server-side, redact
`contact` and scrub the transcript before it reaches here.
"""

from __future__ import annotations

import csv
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import config


def new_conversation_id() -> str:
    return f"conv-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:8]}"


@dataclass
class ConversationRecord:
    conversation_id: str
    started_at: str
    ended_at: str
    outcome: str                        # resolved | ticket_filed | abandoned
    question_count: int
    messages: list[dict]                # [{role, content}, ...]
    failure_signals: list[str] = field(default_factory=list)   # short names: "refused", ...
    failure_reasons: list[str] = field(default_factory=list)   # prose: "user re-asked the same question"
    grounding_checks: list[dict] = field(default_factory=list)  # per answer
    triage_label: str | None = None
    triage_confidence: float | None = None
    thumbs: str | None = None           # up | down | None
    ticket_id: str | None = None
    ticket_category: str | None = None
    needed_by: str | None = None        # user's "when do you need this?" answer
    due_date: str | None = None         # parsed target date (YYYY-MM-DD)
    duplicate_of: str | None = None

    @property
    def failed(self) -> bool:
        return bool(self.failure_signals) or self.outcome == "ticket_filed"

    def first_user_question(self) -> str:
        for m in self.messages:
            if m["role"] == "user":
                return m["content"]
        return ""

    def failed_user_questions(self) -> list[str]:
        """User questions worth mining for doc gaps (only if the chat failed)."""
        return [m["content"] for m in self.messages if m["role"] == "user"] if self.failed else []


def _from_dict(data: dict) -> ConversationRecord:
    known = {k: data.get(k) for k in ConversationRecord.__dataclass_fields__}
    return ConversationRecord(**known)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Primary store
# --------------------------------------------------------------------------- #

def _use_db() -> bool:
    return bool(getattr(config, "DATABASE_URL", None))


def append(record: ConversationRecord) -> None:
    """Upsert one conversation record (keyed by `conversation_id`), then refresh
    the local CSV mirror from the primary store."""
    if _use_db():
        from api import db
        db.upsert_chat_log(asdict(record))
    else:
        _file_upsert(record)
    _write_csv(config.CHAT_LOG_CSV_PATH, load_all())  # mirror: 1 row / conversation


def _file_upsert(record: ConversationRecord) -> None:
    """Rewrite logs/chats.jsonl with `record` replacing any line that has the
    same conversation_id (first-seen order preserved)."""
    config.LOG_DIR.mkdir(exist_ok=True)
    rows: dict[str, dict] = {}
    if config.CHAT_LOG_PATH.exists():
        for line in config.CHAT_LOG_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            rows[str(d.get("conversation_id", id(d)))] = d
    rows[record.conversation_id] = asdict(record)
    with config.CHAT_LOG_PATH.open("w", encoding="utf-8") as fh:
        for d in rows.values():
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")


def _dedupe(records: list[ConversationRecord]) -> list[ConversationRecord]:
    """One record per conversation_id, last value wins, first-seen order kept."""
    out: dict[str, ConversationRecord] = {}
    for r in records:
        out[r.conversation_id] = r
    return list(out.values())


def load_all() -> list[ConversationRecord]:
    if _use_db():
        from api import db
        return _dedupe([_from_dict(d) for d in db.all_chat_logs()])
    if not config.CHAT_LOG_PATH.exists():
        return []
    out: list[ConversationRecord] = []
    for line in config.CHAT_LOG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(_from_dict(json.loads(line)))
    return _dedupe(out)


def reset_store() -> None:
    """Wipe every chat log. Used by `seed_demo_log.py --reset` and the tests."""
    if _use_db():
        from api import db
        db.clear_chat_logs()
    elif config.CHAT_LOG_PATH.exists():
        config.CHAT_LOG_PATH.unlink()
    if config.CHAT_LOG_CSV_PATH.exists():
        config.CHAT_LOG_CSV_PATH.unlink()


# --------------------------------------------------------------------------- #
# Local CSV mirror  (logs/chats.csv — for eyeballing, never read back)
# --------------------------------------------------------------------------- #

CSV_FIELDS = [
    "conversation_id", "started_at", "ended_at", "outcome",
    "question_count", "n_messages", "failed", "failure_signals", "failure_reasons",
    "grounding_checks", "triage_label", "triage_confidence", "thumbs",
    "ticket_id", "ticket_category", "needed_by", "due_date", "duplicate_of",
    "first_user_question", "last_assistant_message",
]


def _csv_row(rec: ConversationRecord) -> dict:
    answers = [m["content"] for m in rec.messages if m.get("role") == "assistant"]
    return {
        "conversation_id": rec.conversation_id,
        "started_at": rec.started_at,
        "ended_at": rec.ended_at,
        "outcome": rec.outcome,
        "question_count": rec.question_count,
        "n_messages": len(rec.messages),
        "failed": rec.failed,
        "failure_signals": "|".join(rec.failure_signals),
        "failure_reasons": "|".join(rec.failure_reasons),
        "grounding_checks": len(rec.grounding_checks),
        "triage_label": rec.triage_label or "",
        "triage_confidence": "" if rec.triage_confidence is None else rec.triage_confidence,
        "thumbs": rec.thumbs or "",
        "ticket_id": rec.ticket_id or "",
        "ticket_category": rec.ticket_category or "",
        "needed_by": rec.needed_by or "",
        "due_date": rec.due_date or "",
        "duplicate_of": rec.duplicate_of or "",
        "first_user_question": rec.first_user_question(),
        "last_assistant_message": answers[-1] if answers else "",
    }


def _write_csv(dest: str | Path, records: list[ConversationRecord]) -> None:
    dest = Path(dest)
    dest.parent.mkdir(exist_ok=True)
    # utf-8-sig so Excel reads accented text correctly.
    with dest.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in records:
            w.writerow(_csv_row(r))


def export_csv(path: str | Path | None = None) -> int:
    """Rebuild the whole CSV from the primary store. Returns the row count."""
    records = load_all()
    _write_csv(path or config.CHAT_LOG_CSV_PATH, records)
    return len(records)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


if __name__ == "__main__":
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    src = "chat_logs table" if _use_db() else str(config.CHAT_LOG_PATH)
    n = export_csv()
    print(f"exported {n} conversation(s)")
    print(f"  from  {src}")
    print(f"  to    {config.CHAT_LOG_CSV_PATH}")
