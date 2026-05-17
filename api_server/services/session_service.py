from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from psycopg.types.json import Json

from config import SESSION_HISTORY_LIMIT
from utils import normalize_datetime, normalize_response_payload


def ensure_session(conn, session_id: UUID) -> tuple[dict[str, Any], bool]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO session (session_id)
            VALUES (%s)
            ON CONFLICT DO NOTHING
            RETURNING session_id, created_at, last_seen_at, ended_at, turn_count, meta
            """,
            (session_id,),
        )
        row = cur.fetchone()
        if row is not None:
            return row, True

        cur.execute(
            """
            UPDATE session
            SET last_seen_at = NOW()
            WHERE session_id = %s
            RETURNING session_id, created_at, last_seen_at, ended_at, turn_count, meta
            """,
            (session_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=500, detail="session row could not be created")
        return row, False


def save_session_message(
    conn,
    session_id: UUID,
    role: str,
    content: str,
    meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO session_message (session_id, role, content, meta)
            VALUES (%s, %s, %s, %s)
            RETURNING message_id, created_at
            """,
            (session_id, role, content, Json(meta or {})),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=500, detail="session message could not be saved")
    return row


def fetch_recent_session_messages(
    conn,
    session_id: UUID,
    limit: int = SESSION_HISTORY_LIMIT,
) -> list[dict[str, str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT role, content
            FROM session_message
            WHERE session_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (session_id, limit),
        )
        rows = cur.fetchall() or []

    history: list[dict[str, str]] = []
    for row in reversed(rows):
        role = (row.get("role") or "").strip().lower()
        content = (row.get("content") or "").strip()
        if role in {"user", "assistant", "system"} and content:
            history.append({"role": role, "content": content})
    return history


def list_sessions(conn, limit: int = 20) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                s.session_id,
                s.created_at,
                s.last_seen_at,
                s.ended_at,
                s.turn_count,
                s.meta,
                (
                    SELECT content
                    FROM session_message sm
                    WHERE sm.session_id = s.session_id
                      AND sm.role = 'user'
                    ORDER BY sm.created_at ASC
                    LIMIT 1
                ) AS first_user_message,
                (
                    SELECT content
                    FROM session_message sm
                    WHERE sm.session_id = s.session_id
                    ORDER BY sm.created_at DESC
                    LIMIT 1
                ) AS last_message,
                (
                    SELECT created_at
                    FROM session_message sm
                    WHERE sm.session_id = s.session_id
                    ORDER BY sm.created_at DESC
                    LIMIT 1
                ) AS last_message_at,
                (
                    SELECT COUNT(*)
                    FROM session_message sm
                    WHERE sm.session_id = s.session_id
                ) AS message_count
            FROM session s
            ORDER BY s.last_seen_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall() or []

    sessions: list[dict[str, Any]] = []
    for row in rows:
        first_user = (row.get("first_user_message") or "").strip()
        last_message = (row.get("last_message") or "").strip()
        preview = first_user or last_message or "New chat"
        sessions.append(
            {
                "session_id": str(row["session_id"]),
                "created_at": normalize_datetime(row["created_at"]),
                "last_seen_at": normalize_datetime(row["last_seen_at"]),
                "ended_at": normalize_datetime(row["ended_at"]) if row.get("ended_at") else None,
                "turn_count": row["turn_count"],
                "message_count": row["message_count"],
                "title": preview[:20],
                "preview": preview[:80],
                "last_message_at": normalize_datetime(row["last_message_at"]) if row.get("last_message_at") else None,
            }
        )
    return sessions


def fetch_session_detail(conn, session_id: UUID) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT session_id, created_at, last_seen_at, ended_at, turn_count, meta
            FROM session
            WHERE session_id = %s
            """,
            (session_id,),
        )
        session_row = cur.fetchone()
        if session_row is None:
            raise HTTPException(status_code=404, detail="session not found")

        cur.execute(
            """
            SELECT message_id, session_id, role, content, created_at, meta
            FROM session_message
            WHERE session_id = %s
            ORDER BY created_at ASC
            """,
            (session_id,),
        )
        message_rows = cur.fetchall() or []

    messages: list[dict[str, Any]] = []
    for row in message_rows:
        messages.append(
            {
                "message_id": row["message_id"],
                "session_id": str(row["session_id"]),
                "role": row["role"],
                "content": row["content"],
                "created_at": normalize_datetime(row["created_at"]),
                "meta": normalize_response_payload(row["meta"]),
            }
        )

    return {
        "session": {
            "session_id": str(session_row["session_id"]),
            "created_at": normalize_datetime(session_row["created_at"]),
            "last_seen_at": normalize_datetime(session_row["last_seen_at"]),
            "ended_at": normalize_datetime(session_row["ended_at"]) if session_row.get("ended_at") else None,
            "turn_count": session_row["turn_count"],
            "meta": normalize_response_payload(session_row["meta"]),
        },
        "messages": messages,
    }


def update_session_turn(conn, session_id: UUID) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE session
            SET last_seen_at = NOW(),
                turn_count = turn_count + 1
            WHERE session_id = %s
            RETURNING session_id, created_at, last_seen_at, ended_at, turn_count, meta
            """,
            (session_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=500, detail="session turn could not be updated")
    return row
