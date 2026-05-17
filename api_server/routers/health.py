from typing import Any

from fastapi import APIRouter

from config import DATABASE_URL, LLM_SERVER_URL
from extensions.db import get_db_connection
from utils import normalize_response_payload

router = APIRouter()


@router.get("/health")
def health() -> dict[str, Any]:
    db_status = {"configured": bool(DATABASE_URL), "ok": False}
    if DATABASE_URL:
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
            db_status["ok"] = True
        except Exception as exc:
            db_status["error"] = str(exc)

    return {
        "ok": True,
        "server": "api",
        "llm_server_url": LLM_SERVER_URL,
        "db": normalize_response_payload(db_status),
    }
