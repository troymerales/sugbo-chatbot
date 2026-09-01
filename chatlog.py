"""
Structured chat logging (feeds §6 eval and §7 analytics).

One JSON object per line in logs/chats.jsonl. A conversation is logged once, when
it reaches a terminal state (resolved, ticket filed, or abandoned via "new chat").
Everything the eval harness and the failure-clustering job need is in that record.

No PII handling beyond what the user typed — this is a local file. If this ever
runs server-side, redact `contact` and scrub the transcript first.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

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


def append(record: ConversationRecord) -> None:
    config.LOG_DIR.mkdir(exist_ok=True)
    with config.CHAT_LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")


def load_all() -> list[ConversationRecord]:
    if not config.CHAT_LOG_PATH.exists():
        return []
    out: list[ConversationRecord] = []
    for line in config.CHAT_LOG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        data = json.loads(line)
        known = {k: data.get(k) for k in ConversationRecord.__dataclass_fields__}
        out.append(ConversationRecord(**known))  # type: ignore[arg-type]
    return out


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
