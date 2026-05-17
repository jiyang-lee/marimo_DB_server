from typing import Any
from uuid import UUID

from fastapi import APIRouter

from extensions.db import get_db_connection
from services.session_service import fetch_session_detail, list_sessions
from utils import normalize_response_payload

router = APIRouter()


@router.get("/sessions")
def sessions(limit: int = 20) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 100))
    with get_db_connection() as conn:
        rows = list_sessions(conn, safe_limit)
    return {"sessions": normalize_response_payload(rows)}


@router.get("/sessions/{session_id}")
def session_detail(session_id: UUID) -> dict[str, Any]:
    with get_db_connection() as conn:
        payload = fetch_session_detail(conn, session_id)
    return normalize_response_payload(payload)
