"""
SQLite persistence for SOAP notes -- the "Past Notes" page. One table,
short-lived connections, JSON blobs for the nested bits.

Note: on an ephemeral host (Streamlit Community Cloud) this file resets on every
reboot. Point ``BISAYA_DB_PATH`` at a mounted volume to keep notes, or run the
app on the VM. (A Postgres-backed store, sharing the chatbot's Supabase, is the
natural follow-up -- mirroring ``api/db.py``.)
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from stt.config import get_settings

_SCHEMA = """
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
def _connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
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


def init_db(db_path: Path | None = None) -> None:
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA)


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for f in _JSON_FIELDS:
        try:
            d[f.removesuffix("_json")] = json.loads(d.pop(f) or "{}")
        except (json.JSONDecodeError, TypeError):
            d[f.removesuffix("_json")] = {}
    return d


def _encode(fields: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in fields.items():
        if k in ("soap", "extract", "review"):
            out[f"{k}_json"] = json.dumps(v or {}, ensure_ascii=False)
        elif k in _WRITABLE:
            out[k] = v
    return out


def create_note(*, db_path: Path | None = None, **fields: Any) -> int:
    data = _encode(fields)
    data.setdefault("created_at", _now())
    data["updated_at"] = _now()
    cols = ", ".join(data)
    ph = ", ".join(f":{c}" for c in data)
    with _connect(db_path) as conn:
        cur = conn.execute(f"INSERT INTO notes ({cols}) VALUES ({ph})", data)
        return int(cur.lastrowid)


def update_note(note_id: int, *, db_path: Path | None = None, **fields: Any) -> None:
    data = _encode(fields)
    if not data:
        return
    data["updated_at"] = _now()
    sets = ", ".join(f"{c} = :{c}" for c in data)
    data["id"] = note_id
    with _connect(db_path) as conn:
        conn.execute(f"UPDATE notes SET {sets} WHERE id = :id", data)


def get_note(note_id: int, *, db_path: Path | None = None) -> dict[str, Any] | None:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    return _row_to_dict(row) if row else None


def delete_note(note_id: int, *, db_path: Path | None = None) -> None:
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))


def list_notes(*, search: str | None = None, limit: int = 50, offset: int = 0,
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
    with _connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(r) for r in rows]


def count_notes(*, search: str | None = None, db_path: Path | None = None) -> int:
    sql = "SELECT COUNT(*) FROM notes"
    params: list[Any] = []
    if search and search.strip():
        like = f"%{search.strip()}%"
        sql += (" WHERE title LIKE ? OR patient_ref LIKE ? OR transcript LIKE ? "
                "OR soap_json LIKE ? OR tags LIKE ?")
        params += [like] * 5
    with _connect(db_path) as conn:
        return int(conn.execute(sql, params).fetchone()[0])
