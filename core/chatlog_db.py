"""
Optional PostgreSQL persistence for the chat log (`core/chatlog.py`).

One table, `chat_logs` — one row per finished conversation, keyed by
`conversation_id`, written the moment a chat goes wrong (outcome `unresolved`)
and updated in place if it later reaches a ticket / resolution.

Opt-in: with no `DATABASE_URL`, `db.enabled()` is False and `chatlog.py` falls
back to `logs/chats.jsonl`, so the app and the test-suite need no database.

    DATABASE_URL=postgresql://postgres.<ref>:<pass>@aws-0-<region>.pooler.supabase.com:5432/postgres

The table is created automatically on first use. Portable across dialects
(JSONB on PostgreSQL, plain JSON on SQLite, which the tests use).
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String, create_engine, delete, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

import config

_JSON = JSON().with_variant(JSONB(), "postgresql")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _pg_driver() -> str:
    """Pick whichever PostgreSQL driver is installed (psycopg v3 preferred)."""
    try:
        import psycopg  # noqa: F401
        return "psycopg"
    except ImportError:
        pass
    try:
        import psycopg2  # noqa: F401
        return "psycopg2"
    except ImportError:
        return "psycopg"


def _normalise_url(url: str) -> str:
    """Pin an explicit driver on a bare ``postgresql://`` / ``postgres://`` URL —
    the form Supabase / Neon / Heroku hand you."""
    scheme = url.split("://", 1)[0]
    if url.startswith("sqlite") or "+psycopg" in scheme or "+asyncpg" in scheme:
        return url
    for s in ("postgresql://", "postgres://"):
        if url.startswith(s):
            return f"postgresql+{_pg_driver()}://" + url[len(s):]
    return url


class Base(DeclarativeBase):
    pass


class ChatLogRow(Base):
    """One finished conversation. Replaces a line in logs/chats.jsonl."""

    __tablename__ = "chat_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[str] = mapped_column(String(40))
    ended_at: Mapped[str] = mapped_column(String(40))
    outcome: Mapped[str] = mapped_column(String(32), index=True)
    question_count: Mapped[int] = mapped_column(Integer, default=0)
    record: Mapped[dict] = mapped_column(_JSON)   # full asdict(chatlog.ConversationRecord)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# --------------------------------------------------------------------------- #
# Engine / session  (lazy, cached, resettable for tests)
# --------------------------------------------------------------------------- #

_engine = None
_Session: sessionmaker | None = None


def enabled() -> bool:
    return bool(getattr(config, "DATABASE_URL", None))


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
            # Managed poolers (Supabase Supavisor, PgBouncer) drop idle
            # connections; pre_ping revalidates, recycle avoids a stale one.
            kw["pool_pre_ping"] = True
            kw["pool_recycle"] = 1800
            kw["pool_size"] = getattr(config, "DB_POOL_SIZE", 5)
            kw["max_overflow"] = getattr(config, "DB_MAX_OVERFLOW", 2)
        _engine = create_engine(url, **kw)
        _Session = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
        Base.metadata.create_all(_engine)   # idempotent — create chat_logs on first use
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
    an idle connection between requests."""
    for attempt in range(2):
        try:
            with session() as s:
                return op(s)
        except (OperationalError, DBAPIError):
            if attempt == 1:
                raise
            reset()
            time.sleep(0.4)


def reset() -> None:
    """Drop the cached engine. Tests call this after swapping DATABASE_URL."""
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _Session = None


def init_db() -> None:
    """Create the table if it doesn't exist. Idempotent (also done lazily)."""
    Base.metadata.create_all(_get_engine())


def drop_db() -> None:
    Base.metadata.drop_all(_get_engine())


# --------------------------------------------------------------------------- #
# chat_logs
# --------------------------------------------------------------------------- #

def upsert_chat_log(record: dict) -> None:
    """Insert a finished-conversation row, or update the existing one for this
    ``conversation_id`` in place (newest wins — no unique constraint)."""
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
