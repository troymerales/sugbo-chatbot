"""
Create / verify / reset the database schema for the FastAPI backend.

    python -m api.db_init            # create the tables if missing  (idempotent)
    python -m api.db_init --check    # report what exists, change nothing
    python -m api.db_init --drop     # DROP both tables, then recreate  (DESTRUCTIVE)

Reads DATABASE_URL from .env / the environment (see config.py). PostgreSQL is
the intended target; any SQLAlchemy URL works:

    DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/sugbodoc

Tables created (see db.py for the authoritative definitions):
    conversations   live sessions   (conversation_id, stage, started_at,
                                     question_count, state JSONB, updated_at)
    chat_logs       finished convos  (id, conversation_id, started_at, ended_at,
                                     outcome, question_count, record JSONB,
                                     created_at)

Prefer raw SQL? `schema.sql` contains equivalent CREATE TABLE statements.
"""

from __future__ import annotations

# Allow `python api/db_init.py` as well as `python -m api.db_init`.
if not __package__:
    import pathlib
    import sys as _sys

    _sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import argparse
import sys

import config


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--drop", action="store_true",
                    help="drop the tables before creating them (DESTRUCTIVE)")
    ap.add_argument("--check", action="store_true",
                    help="report existing tables, make no changes")
    args = ap.parse_args()

    if not config.DATABASE_URL:
        sys.exit("DATABASE_URL is not set — nothing to initialise.\n"
                 "Add it to .env (see .env.example), e.g.\n"
                 "  DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/sugbodoc")

    from sqlalchemy import inspect

    from api import db

    # Hide credentials in the printed URL.
    shown = config.DATABASE_URL.rsplit("@", 1)[-1]
    print(f"target: ...{shown}")

    if args.check:
        insp = inspect(db._get_engine())
        for t in ("conversations", "chat_logs"):
            print(f"  {t:15s} {'present' if insp.has_table(t) else 'MISSING'}")
        return

    if args.drop:
        print("dropping tables: conversations, chat_logs ...")
        db.drop_db()

    db.init_db()
    print("schema ready: conversations, chat_logs")


if __name__ == "__main__":
    main()
