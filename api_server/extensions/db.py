from datetime import datetime
from typing import Optional

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row

from config import (
    DATABASE_URL,
    DB_TIMEZONE,
    REALTIME_CLEANUP_INTERVAL_SECONDS,
    REALTIME_RETENTION_DAYS,
)
from utils import now_kst

last_realtime_cleanup_at: Optional[datetime] = None


def get_db_connection():
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")
    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
        options=f"-c timezone={DB_TIMEZONE}",
    )


def init_db() -> None:
    if not DATABASE_URL:
        return

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS session (
                    session_id UUID PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    ended_at TIMESTAMPTZ NULL,
                    turn_count INTEGER NOT NULL DEFAULT 0,
                    meta JSONB NOT NULL DEFAULT '{}'::jsonb
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS session_message (
                    message_id BIGSERIAL PRIMARY KEY,
                    session_id UUID NOT NULL REFERENCES session(session_id) ON DELETE CASCADE,
                    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    meta JSONB NOT NULL DEFAULT '{}'::jsonb
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sensor_readings (
                    reading_id BIGSERIAL PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    sensor_type TEXT NOT NULL CHECK (sensor_type IN ('realtime', 'hourly')),
                    payload JSONB NOT NULL,
                    state_level TEXT NOT NULL CHECK (state_level IN ('normal', 'warning', 'danger')),
                    state_alerts JSONB NOT NULL DEFAULT '[]'::jsonb
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS interaction_log (
                    interaction_id BIGSERIAL PRIMARY KEY,
                    session_id UUID NOT NULL REFERENCES session(session_id) ON DELETE CASCADE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    stt_text TEXT NOT NULL,
                    llm_answer TEXT NOT NULL,
                    tts_text TEXT NOT NULL,
                    sensor_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    state_level TEXT NOT NULL CHECK (state_level IN ('normal', 'warning', 'danger', 'chat')),
                    state_alerts JSONB NOT NULL DEFAULT '[]'::jsonb,
                    meta JSONB NOT NULL DEFAULT '{}'::jsonb
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_session_last_seen_at ON session (last_seen_at DESC)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_session_message_session_created_at ON session_message (session_id, created_at DESC)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_sensor_readings_type_created_at ON sensor_readings (sensor_type, created_at DESC)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_interaction_log_session_created_at ON interaction_log (session_id, created_at DESC)"
            )
        conn.commit()


def cleanup_old_realtime_rows(force: bool = False) -> int:
    global last_realtime_cleanup_at

    now = now_kst()
    if (
        not force
        and last_realtime_cleanup_at is not None
        and (now - last_realtime_cleanup_at).total_seconds() < REALTIME_CLEANUP_INTERVAL_SECONDS
    ):
        return 0

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM sensor_readings
                WHERE sensor_type = 'realtime'
                  AND created_at < NOW() - (%s * INTERVAL '1 day')
                RETURNING reading_id
                """,
                (REALTIME_RETENTION_DAYS,),
            )
            deleted_count = cur.rowcount
        conn.commit()

    last_realtime_cleanup_at = now
    return deleted_count
