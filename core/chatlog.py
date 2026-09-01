"""
Structured chat logging (feeds §6 eval and §7 analytics).

A conversation is logged once, when it reaches a terminal state (resolved,
ticket filed, linked to a duplicate, or abandoned via "new chat"). Everything
the eval harness and the failure-clustering job need is in that record.

Primary store depends on config.DATABASE_URL:
  * unset  -> one JSON object per line in logs/chats.jsonl (the default; fine
             for the Streamlit demo and the tests).
  * set    -> one row per conversation in the `chat_logs` PostgreSQL table
             (see db.py / db_init.py).
Either way the API is the same: `append(record)` / `load_all()`.

Local CSV mirror: every `append()` ALSO writes a flattened row to
config.CHAT_LOG_CSV_PATH (logs/chats.csv) regardless of the primary store. It's
a convenience copy for eyeballing in a spreadsheet — nothing reads it back.
`python chatlog.py` rebuilds it from the primary store (handy to backfill rows
that were written straight to Supabase).

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
    failure_signals: list[str] = field(default_factory=list)
    grounding_checks: list[dict] = field(default_factory=list)  # per answer
    triage_label: str | None = None
    triage_confidence: float | None = None
    thumbs: str | None = None           # up | down | None
    ticket_id: str | None = None
    ticket_category: str | None = None
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
    if _use_db():
        from api import db
        db.insert_chat_log(asdict(record))
    else:
        config.LOG_DIR.mkdir(exist_ok=True)
        with config.CHAT_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
    _csv_append(record)  # local mirror, always


def load_all() -> list[ConversationRecord]:
    if _use_db():
        from api import db
        return [_from_dict(d) for d in db.all_chat_logs()]
    if not config.CHAT_LOG_PATH.exists():
        return []
    out: list[ConversationRecord] = []
    for line in config.CHAT_LOG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(_from_dict(json.loads(line)))
    return out


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
    "question_count", "n_messages", "failed", "failure_signals",
    "grounding_checks", "triage_label", "triage_confidence", "thumbs",
    "ticket_id", "ticket_category", "duplicate_of",
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
        "grounding_checks": len(rec.grounding_checks),
        "triage_label": rec.triage_label or "",
        "triage_confidence": "" if rec.triage_confidence is None else rec.triage_confidence,
        "thumbs": rec.thumbs or "",
        "ticket_id": rec.ticket_id or "",
        "ticket_category": rec.ticket_category or "",
        "duplicate_of": rec.duplicate_of or "",
        "first_user_question": rec.first_user_question(),
        "last_assistant_message": answers[-1] if answers else "",
    }


def _csv_append(record: ConversationRecord) -> None:
    path: Path = config.CHAT_LOG_CSV_PATH
    path.parent.mkdir(exist_ok=True)
    new = not path.exists()
    # utf-8-sig on first write so Excel reads accented text correctly; plain
    # utf-8 when appending (a BOM mid-file would corrupt it).
    with path.open("a", encoding="utf-8-sig" if new else "utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        if new:
            w.writeheader()
        w.writerow(_csv_row(record))


def export_csv(path: str | Path | None = None) -> int:
    """Rebuild the whole CSV from the primary store. Returns the row count."""
    dest = Path(path) if path else config.CHAT_LOG_CSV_PATH
    records = load_all()
    dest.parent.mkdir(exist_ok=True)
    with dest.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in records:
            w.writerow(_csv_row(r))
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
