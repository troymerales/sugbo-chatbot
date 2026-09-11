"""
SOAP notes persistence — Postgres (prod) or SQLite (test).

Production: DATABASE_URL set → uses shared `soap_notes` table on Supabase
Testing: DATABASE_URL unset → falls back to SQLite (tests set DATABASE_URL=None explicitly)
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import config
from stt.config import get_settings


def _use_postgres() -> bool:
    """Check if Postgres should be used (DATABASE_URL is set)."""
    return bool(getattr(config, "DATABASE_URL", None))


def init_db(db_path: Path | None = None) -> None:
    if _use_postgres():
        from stt import notes_db_pg
        notes_db_pg.init_db()
    else:
        _sqlite_init_db(db_path)


def create_note(*, db_path: Path | None = None, **fields: Any) -> int:
    if _use_postgres():
        from stt import notes_db_pg
        return notes_db_pg.create_note(**fields)
    return _sqlite_create_note(db_path, **fields)


def update_note(note_id: int, *, db_path: Path | None = None, **fields: Any) -> None:
    if _use_postgres():
        from stt import notes_db_pg
        notes_db_pg.update_note(note_id, **fields)
    else:
        _sqlite_update_note(note_id, db_path, **fields)


def get_note(note_id: int, *, db_path: Path | None = None) -> dict[str, Any] | None:
    if _use_postgres():
        from stt import notes_db_pg
        return notes_db_pg.get_note(note_id)
    return _sqlite_get_note(note_id, db_path)


def delete_note(note_id: int, *, db_path: Path | None = None) -> None:
    if _use_postgres():
        from stt import notes_db_pg
        notes_db_pg.delete_note(note_id)
    else:
        _sqlite_delete_note(note_id, db_path)


def list_notes(*, search: str | None = None, limit: int = 50, offset: int = 0,
               db_path: Path | None = None) -> list[dict[str, Any]]:
    if _use_postgres():
        from stt import notes_db_pg
        return notes_db_pg.list_notes(search=search, limit=limit, offset=offset)
    return _sqlite_list_notes(search, limit, offset, db_path)


def count_notes(*, search: str | None = None, db_path: Path | None = None) -> int:
    if _use_postgres():
        from stt import notes_db_pg
        return notes_db_pg.count_notes(search=search)
    return _sqlite_count_notes(search, db_path)


# ============================================================================
# SQLite backend (test only)
# ============================================================================

_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    title           TEXT NOT NULL DEFAULT '',
    patient_ref     TEXT NOT NULL DEFAULT '',
    context         TEXT NOT NULL DEFAULT '',
    audio_filename  TEXT NOT NULL DEFAULT '',
    duration_s      REAL,
    transcript      TEXT NOT NULL DEFAULT '',
    soap_json       TEXT NOT NULL DEFAULT '{}',
    extract_json    TEXT NOT NULL DEFAULT '{}',
    review_json     TEXT NOT NULL DEFAULT '{}',
    whisper_model   TEXT NOT NULL DEFAULT '',
    soap_model      TEXT NOT NULL DEFAULT '',
    tags            TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_notes_created_at ON notes(created_at DESC);
"""

_JSON_FIELDS = ("soap_json", "extract_json", "review_json")
_WRITABLE = (
    "title", "patient_ref", "context", "audio_filename", "duration_s",
    "transcript", "soap_json", "extract_json", "review_json",
    "whisper_model", "soap_model", "tags",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _sqlite_connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = Path(db_path or get_settings().db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _sqlite_init_db(db_path: Path | None = None) -> None:
    with _sqlite_connect(db_path) as conn:
        conn.executescript(_SQLITE_SCHEMA)


def _sqlite_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for f in _JSON_FIELDS:
        try:
            d[f.removesuffix("_json")] = json.loads(d.pop(f) or "{}")
        except (json.JSONDecodeError, TypeError):
            d[f.removesuffix("_json")] = {}
    return d


def _sqlite_encode(fields: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in fields.items():
        if k in ("soap", "extract", "review"):
            out[f"{k}_json"] = json.dumps(v or {}, ensure_ascii=False)
        elif k in _WRITABLE:
            out[k] = v
    return out


def _sqlite_create_note(db_path: Path | None = None, **fields: Any) -> int:
    data = _sqlite_encode(fields)
    data.setdefault("created_at", _now())
    data["updated_at"] = _now()
    cols = ", ".join(data)
    ph = ", ".join(f":{c}" for c in data)
    with _sqlite_connect(db_path) as conn:
        cur = conn.execute(f"INSERT INTO notes ({cols}) VALUES ({ph})", data)
        return int(cur.lastrowid)


def _sqlite_update_note(note_id: int, db_path: Path | None = None, **fields: Any) -> None:
    data = _sqlite_encode(fields)
    if not data:
        return
    data["updated_at"] = _now()
    sets = ", ".join(f"{c} = :{c}" for c in data)
    data["id"] = note_id
    with _sqlite_connect(db_path) as conn:
        conn.execute(f"UPDATE notes SET {sets} WHERE id = :id", data)


def _sqlite_get_note(note_id: int, db_path: Path | None = None) -> dict[str, Any] | None:
    with _sqlite_connect(db_path) as conn:
        row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    return _sqlite_row_to_dict(row) if row else None


def _sqlite_delete_note(note_id: int, db_path: Path | None = None) -> None:
    with _sqlite_connect(db_path) as conn:
        conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))


def _sqlite_list_notes(search: str | None = None, limit: int = 50, offset: int = 0,
                       db_path: Path | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM notes"
    params: list[Any] = []
    if search and search.strip():
        like = f"%{search.strip()}%"
        sql += (" WHERE title LIKE ? OR patient_ref LIKE ? OR transcript LIKE ? "
                "OR soap_json LIKE ? OR tags LIKE ?")
        params += [like] * 5
    sql += " ORDER BY datetime(created_at) DESC, id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    with _sqlite_connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_sqlite_row_to_dict(r) for r in rows]


def _sqlite_count_notes(search: str | None = None, db_path: Path | None = None) -> int:
    sql = "SELECT COUNT(*) FROM notes"
    params: list[Any] = []
    if search and search.strip():
        like = f"%{search.strip()}%"
        sql += (" WHERE title LIKE ? OR patient_ref LIKE ? OR transcript LIKE ? "
                "OR soap_json LIKE ? OR tags LIKE ?")
        params += [like] * 5
    with _sqlite_connect(db_path) as conn:
        return int(conn.execute(sql, params).fetchone()[0])
