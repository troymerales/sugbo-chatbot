"""
PostgreSQL backend for SOAP notes persistence (shared Supabase database).

Mirrors the SQLite interface in notes_db.py but uses SQLAlchemy ORM.
Reuses the chatbot's database connection via core.chatlog_db.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Integer, Numeric, String, create_engine, delete, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

import config


_JSON = JSON().with_variant(JSONB(), "postgresql")
_engine = None
_Session = None


class Base(DeclarativeBase):
    pass


class SoapNoteRow(Base):
    __tablename__ = "soap_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(255), default="")
    patient_ref: Mapped[str] = mapped_column(String(255), default="")
    context: Mapped[str] = mapped_column(String(1024), default="")
    audio_filename: Mapped[str] = mapped_column(String(255), default="")
    duration_s: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    transcript: Mapped[str] = mapped_column(String(4096), default="")
    soap_json: Mapped[dict] = mapped_column(_JSON, default={})
    extract_json: Mapped[dict] = mapped_column(_JSON, default={})
    review_json: Mapped[dict] = mapped_column(_JSON, default={})
    whisper_model: Mapped[str] = mapped_column(String(255), default="")
    soap_model: Mapped[str] = mapped_column(String(255), default="")
    tags: Mapped[str] = mapped_column(String(1024), default="")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _get_engine():
    global _engine, _Session
    if _engine is None:
        if not config.DATABASE_URL:
            raise RuntimeError("Postgres backend requires DATABASE_URL")

        from core.chatlog_db import _normalise_url

        url = _normalise_url(config.DATABASE_URL)
        _engine = create_engine(
            url,
            pool_pre_ping=True,
            pool_recycle=1800,
            pool_size=getattr(config, "DB_POOL_SIZE", 5),
            max_overflow=getattr(config, "DB_MAX_OVERFLOW", 2),
        )
        _Session = sessionmaker(bind=_engine, expire_on_commit=False)
        Base.metadata.create_all(_engine)
    return _engine


def init_db() -> None:
    _get_engine()


def _row_to_dict(row: SoapNoteRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "title": row.title,
        "patient_ref": row.patient_ref,
        "context": row.context,
        "audio_filename": row.audio_filename,
        "duration_s": row.duration_s,
        "transcript": row.transcript,
        "soap": row.soap_json or {},
        "extract": row.extract_json or {},
        "review": row.review_json or {},
        "whisper_model": row.whisper_model,
        "soap_model": row.soap_model,
        "tags": row.tags,
    }


def create_note(**fields: Any) -> int:
    data = _prepare_fields(fields)
    data.setdefault("created_at", _now())
    data["updated_at"] = _now()

    row = SoapNoteRow(**data)
    _get_engine()  # Ensure engine is initialized
    with _Session() as sess:
        sess.add(row)
        sess.commit()
        row_id = row.id
    return row_id


def update_note(note_id: int, **fields: Any) -> None:
    data = _prepare_fields(fields)
    if not data:
        return
    data["updated_at"] = _now()

    _get_engine()  # Ensure engine is initialized
    with _Session() as sess:
        row = sess.execute(select(SoapNoteRow).where(SoapNoteRow.id == note_id)).scalar_one_or_none()
        if row:
            for k, v in data.items():
                setattr(row, k, v)
            sess.commit()


def get_note(note_id: int) -> dict[str, Any] | None:
    _get_engine()  # Ensure engine is initialized
    with _Session() as sess:
        row = sess.execute(select(SoapNoteRow).where(SoapNoteRow.id == note_id)).scalar_one_or_none()
    return _row_to_dict(row) if row else None


def delete_note(note_id: int) -> None:
    _get_engine()  # Ensure engine is initialized
    with _Session() as sess:
        sess.execute(delete(SoapNoteRow).where(SoapNoteRow.id == note_id))
        sess.commit()


def list_notes(
    *, search: str | None = None, limit: int = 50, offset: int = 0
) -> list[dict[str, Any]]:
    _get_engine()  # Ensure engine is initialized
    stmt = select(SoapNoteRow)

    if search and search.strip():
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            (SoapNoteRow.title.ilike(pattern))
            | (SoapNoteRow.patient_ref.ilike(pattern))
            | (SoapNoteRow.transcript.ilike(pattern))
            | (SoapNoteRow.tags.ilike(pattern))
        )

    stmt = stmt.order_by(SoapNoteRow.created_at.desc(), SoapNoteRow.id.desc()).limit(limit).offset(offset)

    with _Session() as sess:
        rows = sess.execute(stmt).scalars().all()
    return [_row_to_dict(r) for r in rows]


def count_notes(*, search: str | None = None) -> int:
    _get_engine()  # Ensure engine is initialized
    stmt = select(func.count(SoapNoteRow.id))

    if search and search.strip():
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            (SoapNoteRow.title.ilike(pattern))
            | (SoapNoteRow.patient_ref.ilike(pattern))
            | (SoapNoteRow.transcript.ilike(pattern))
            | (SoapNoteRow.tags.ilike(pattern))
        )

    with _Session() as sess:
        return int(sess.execute(stmt).scalar() or 0)


def _prepare_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Map user-facing field names to ORM columns."""
    _WRITABLE = (
        "title",
        "patient_ref",
        "context",
        "audio_filename",
        "duration_s",
        "transcript",
        "soap",
        "extract",
        "review",
        "whisper_model",
        "soap_model",
        "tags",
    )
    out: dict[str, Any] = {}
    for k, v in fields.items():
        if k == "soap":
            out["soap_json"] = v or {}
        elif k == "extract":
            out["extract_json"] = v or {}
        elif k == "review":
            out["review_json"] = v or {}
        elif k in _WRITABLE:
            out[k] = v
    return out
