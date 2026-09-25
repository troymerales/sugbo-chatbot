"""
PostgreSQL persistence for the FastAPI backend (`service.py`) and the chat log
(`chatlog.py`).

Two tables, created by `db_init.py` (or `db.init_db()`):

    conversations   one row per *live* session. Holds the current stage and the
                    serialised `engine.Conversation` (including `chat.history`),
                    so a restart or a second uvicorn worker doesn't lose it. The
                    row is deleted once the conversation reaches a terminal
                    stage — by then it is in `chat_logs`.
    chat_logs       one row per conversation, keyed by conversation_id. Written
                    the moment a chat goes wrong (outcome `unresolved`) and
                    updated in place if it later reaches a ticket / resolution.
                    This is the analytics/eval feed that used to be
                    `logs/chats.jsonl`.

Everything here is opt-in. With no `DATABASE_URL` set, `db.enabled()` is False
and the callers fall back to the in-memory dict / JSONL file exactly as before,
so the Streamlit demo and the test-suite need no database.

    DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/sugbodoc

The models are dialect-portable: JSONB on PostgreSQL, plain JSON elsewhere (the
test-suite points `DATABASE_URL` at a throwaway SQLite file to exercise this
path without a server).
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import (JSON, DateTime, Integer, String, create_engine, delete,
                        func, select)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import (DeclarativeBase, Mapped, mapped_column, sessionmaker)

import config

# JSONB on PostgreSQL, plain JSON on every other dialect (e.g. SQLite in tests).
_JSON = JSON().with_variant(JSONB(), "postgresql")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _pg_driver() -> str:
    """Pick whichever PostgreSQL driver is installed (psycopg v3 preferred)."""
    try:
        import psycopg  # noqa: F401  (v3 — what requirements-service.txt ships)
        return "psycopg"
    except ImportError:
        pass
    try:
        import psycopg2  # noqa: F401
        return "psycopg2"
    except ImportError:
        return "psycopg"  # let SQLAlchemy raise a clear "not installed" error


def _normalise_url(url: str) -> str:
    """Pin an explicit driver on a bare ``postgresql://`` / ``postgres://`` URL.

    That's the form Supabase, Neon, Heroku etc. hand you; without a driver
    SQLAlchemy defaults to psycopg2, which may not be the one installed.
    """
    if url.startswith("sqlite") or "+psycopg" in url.split("://", 1)[0] \
            or "+asyncpg" in url.split("://", 1)[0]:
        return url
    for scheme in ("postgresql://", "postgres://"):
        if url.startswith(scheme):
            return f"postgresql+{_pg_driver()}://" + url[len(scheme):]
    return url


class Base(DeclarativeBase):
    pass


class ConversationRow(Base):
    """A live session. Deleted when the conversation reaches a terminal stage."""

    __tablename__ = "conversations"

    conversation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    stage: Mapped[str] = mapped_column(String(32), default="chat")
    started_at: Mapped[str] = mapped_column(String(40))
    question_count: Mapped[int] = mapped_column(Integer, default=0)
    # full engine.serialize(conv) blob — chat.history, messages, triage, ...
    state: Mapped[dict] = mapped_column(_JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class ChatLogRow(Base):
    """One finished conversation. Replaces a line in logs/chats.jsonl."""

    __tablename__ = "chat_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[str] = mapped_column(String(40))
    ended_at: Mapped[str] = mapped_column(String(40))
    outcome: Mapped[str] = mapped_column(String(32), index=True)
    question_count: Mapped[int] = mapped_column(Integer, default=0)
    # full asdict(chatlog.ConversationRecord)
    record: Mapped[dict] = mapped_column(_JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# --------------------------------------------------------------------------- #
# Engine / session management  (lazy, cached, resettable for tests)
# --------------------------------------------------------------------------- #

_engine = None
_Session: sessionmaker | None = None


def enabled() -> bool:
    """True when a DATABASE_URL is configured — callers persist to Postgres."""
    return bool(getattr(config, "DATABASE_URL", None))


def ping() -> bool:
    """Cheap `SELECT 1` for the /readyz probe. True if the DB answers, False on
    any error (paused Supabase project, wrong credentials, network). Never
    raises — the caller decides what a False means."""
    if not enabled():
        return False
    try:
        with session() as s:
            s.execute(select(1))
        return True
    except Exception:
        return False


def _get_engine():
    global _engine, _Session
    if _engine is None:
        if not config.DATABASE_URL:
            raise RuntimeError("db access requested but DATABASE_URL is not set")
        url = _normalise_url(config.DATABASE_URL)
        kw: dict = {"echo": bool(getattr(config, "DB_ECHO", False)), "future": True}
        if url.startswith("sqlite"):
            kw["connect_args"] = {"check_same_thread": False}
        else:
            # Managed poolers (Supabase Supavisor, PgBouncer, RDS proxy) drop idle
            # connections; pre_ping revalidates and recycle avoids handing out a
            # stale one in the first place.
            kw["pool_pre_ping"] = True
            kw["pool_recycle"] = 1800
            # Keep the pool small — Supabase's free session pooler caps total
            # connections per project, and several Render instances + the local
            # analytics scripts all draw from the same budget.
            kw["pool_size"] = getattr(config, "DB_POOL_SIZE", 5)
            kw["max_overflow"] = getattr(config, "DB_MAX_OVERFLOW", 2)
        _engine = create_engine(url, **kw)
        _Session = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


@contextmanager
def session():
    """A transactional scope: commit on success, roll back on error."""
    _get_engine()
    assert _Session is not None
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def _run(op):
    """Run ``op(session)`` in a transaction, retrying once if the pooler dropped
    an idle connection between requests (`OperationalError`). A real outage still
    raises after the retry rather than silently falling back to a local file."""
    for attempt in range(2):
        try:
            with session() as s:
                return op(s)
        except (OperationalError, DBAPIError):
            if attempt == 1:
                raise
            reset()          # force a fresh engine/pool
            time.sleep(0.4)


def reset() -> None:
    """Drop the cached engine. Tests call this after swapping DATABASE_URL."""
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _Session = None


def init_db() -> None:
    """Create both tables if they do not exist. Idempotent."""
    Base.metadata.create_all(_get_engine())


def drop_db() -> None:
    """Drop both tables. Destructive — used by `db_init.py --drop`."""
    Base.metadata.drop_all(_get_engine())


# --------------------------------------------------------------------------- #
# conversations  (live session store)
# --------------------------------------------------------------------------- #

def save_conversation(*, conversation_id: str, stage: str, started_at: str,
                      question_count: int, state: dict) -> None:
    def op(s):
        row = s.get(ConversationRow, conversation_id)
        if row is None:
            row = ConversationRow(conversation_id=conversation_id)
            s.add(row)
        row.stage = stage
        row.started_at = started_at
        row.question_count = question_count
        row.state = state
    _run(op)


def load_conversation(conversation_id: str) -> dict | None:
    def op(s):
        row = s.get(ConversationRow, conversation_id)
        return dict(row.state) if row is not None else None
    return _run(op)


def delete_conversation(conversation_id: str) -> bool:
    def op(s):
        row = s.get(ConversationRow, conversation_id)
        if row is None:
            return False
        s.delete(row)
        return True
    return _run(op)


def count_conversations() -> int:
    return _run(lambda s: int(
        s.scalar(select(func.count()).select_from(ConversationRow)) or 0
    ))


def delete_stale_conversations(max_age_hours: int = 24) -> int:
    """Sweep live-session rows abandoned mid-conversation (page closed, no
    terminal state). Called on startup; safe to call any time."""
    cutoff = _utcnow() - timedelta(hours=max_age_hours)

    def op(s):
        res = s.execute(
            delete(ConversationRow).where(ConversationRow.updated_at < cutoff)
        )
        return res.rowcount or 0
    try:
        return _run(op)
    except Exception:
        return 0  # never let a housekeeping sweep break startup


# --------------------------------------------------------------------------- #
# chat_logs  (finished conversations — the analytics feed)
# --------------------------------------------------------------------------- #

def insert_chat_log(record: dict) -> None:
    def op(s):
        s.add(ChatLogRow(
            conversation_id=str(record.get("conversation_id", "")),
            started_at=str(record.get("started_at", "")),
            ended_at=str(record.get("ended_at", "")),
            outcome=str(record.get("outcome", "")),
            question_count=int(record.get("question_count", 0) or 0),
            record=record,
        ))
    _run(op)


def upsert_chat_log(record: dict) -> None:
    """Insert a finished-conversation row, or update the existing one for this
    ``conversation_id`` in place. A chat is logged the moment it goes wrong
    (outcome ``unresolved``) and the row is then updated if it later reaches a
    ticket / duplicate-link / resolution — so a thumbs-down that never becomes a
    ticket is still captured, without a duplicate row.

    Matched on ``conversation_id`` (there is no unique constraint — legacy rows
    may duplicate it, so the newest wins)."""
    cid = str(record.get("conversation_id", ""))

    def op(s):
        row = None
        if cid:
            row = s.scalar(
                select(ChatLogRow)
                .where(ChatLogRow.conversation_id == cid)
                .order_by(ChatLogRow.id.desc())
            )
        if row is None:
            s.add(ChatLogRow(
                conversation_id=cid,
                started_at=str(record.get("started_at", "")),
                ended_at=str(record.get("ended_at", "")),
                outcome=str(record.get("outcome", "")),
                question_count=int(record.get("question_count", 0) or 0),
                record=record,
            ))
        else:
            row.started_at = str(record.get("started_at", ""))
            row.ended_at = str(record.get("ended_at", ""))
            row.outcome = str(record.get("outcome", ""))
            row.question_count = int(record.get("question_count", 0) or 0)
            row.record = record
    _run(op)


def all_chat_logs() -> list[dict]:
    def op(s):
        rows = s.scalars(select(ChatLogRow).order_by(ChatLogRow.id)).all()
        return [dict(r.record) for r in rows]
    return _run(op)


def clear_chat_logs() -> int:
    def op(s):
        res = s.execute(delete(ChatLogRow))
        return res.rowcount or 0
    return _run(op)
