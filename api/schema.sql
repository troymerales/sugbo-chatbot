-- SugboDoc FastAPI backend — PostgreSQL schema.
-- Equivalent to running `python db_init.py`. Safe to run more than once.
--
--   psql "$DATABASE_URL" -f schema.sql
--
-- The authoritative definitions live in db.py (SQLAlchemy models); this file is
-- provided for operators who would rather apply DDL directly.

-- Live sessions. A row is deleted once its conversation reaches a terminal
-- stage (by then it has been copied into chat_logs).
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id  VARCHAR(64) PRIMARY KEY,
    stage            VARCHAR(32)  NOT NULL DEFAULT 'chat',
    started_at       VARCHAR(40)  NOT NULL,
    question_count   INTEGER      NOT NULL DEFAULT 0,
    state            JSONB        NOT NULL DEFAULT '{}'::jsonb,
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Finished conversations — the analytics / eval feed (was logs/chats.jsonl).
CREATE TABLE IF NOT EXISTS chat_logs (
    id               BIGSERIAL PRIMARY KEY,
    conversation_id  VARCHAR(64) NOT NULL,
    started_at       VARCHAR(40) NOT NULL,
    ended_at         VARCHAR(40) NOT NULL,
    outcome          VARCHAR(32) NOT NULL,
    question_count   INTEGER     NOT NULL DEFAULT 0,
    record           JSONB       NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_chat_logs_conversation_id ON chat_logs (conversation_id);
CREATE INDEX IF NOT EXISTS ix_chat_logs_outcome         ON chat_logs (outcome);
