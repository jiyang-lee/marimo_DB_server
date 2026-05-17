from typing import Any, Optional
from uuid import UUID, uuid4

import httpx
from fastapi import HTTPException
from psycopg.types.json import Json

from config import LLM_SERVER_URL
from extensions.db import get_db_connection
from schemas import SensorPayload
from services.sensor_service import judge_sensor_state, load_latest_sensor_payload
from services.session_service import (
    ensure_session,
    fetch_recent_session_messages,
    save_session_message,
    update_session_turn,
)
from utils import normalize_datetime, normalize_response_payload


async def request_llm(
    question: str,
    sensor: Optional[SensorPayload],
    state: Optional[dict[str, Any]],
    use_sensor_context: bool,
    history: Optional[list[dict[str, str]]] = None,
) -> dict[str, Any]:
    request_body = {
        "question": question,
        "sensor": sensor.model_dump() if sensor is not None else None,
        "state": state,
        "history": history or [],
        "use_sensor_context": use_sensor_context,
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{LLM_SERVER_URL}/generate", json=request_body)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"LLM server error: {exc}") from exc
    return response.json()


async def handle_interaction(
    *,
    session_id: Optional[UUID],
    text: str,
    sensor: Optional[SensorPayload],
    use_sensor_context: bool,
    source: str,
) -> dict[str, Any]:
    resolved_session_id = session_id or uuid4()
    active_sensor: Optional[SensorPayload] = sensor
    state: dict[str, Any] = {"level": "chat", "alerts": []}

    if use_sensor_context:
        active_sensor = active_sensor or load_latest_sensor_payload()
        state = judge_sensor_state(active_sensor)

    with get_db_connection() as conn:
        session_row, session_created = ensure_session(conn, resolved_session_id)
        history = fetch_recent_session_messages(conn, resolved_session_id)
        save_session_message(
            conn,
            resolved_session_id,
            "user",
            text,
            meta={"source": source, "use_sensor_context": use_sensor_context},
        )

        llm = await request_llm(
            text,
            active_sensor,
            state,
            use_sensor_context=use_sensor_context,
            history=history,
        )
        answer = str(llm.get("answer", "")).strip()
        if not answer:
            raise HTTPException(status_code=502, detail="LLM response has no answer")

        save_session_message(conn, resolved_session_id, "assistant", answer, meta={"source": source})

        interaction_payload = active_sensor.model_dump() if active_sensor is not None else {}
        alerts = state.get("alerts") or []
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO interaction_log (
                    session_id, stt_text, llm_answer, tts_text, sensor_json, state_level, state_alerts, meta
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING interaction_id, created_at
                """,
                (
                    resolved_session_id,
                    text,
                    answer,
                    answer,
                    Json(interaction_payload),
                    state["level"],
                    Json(alerts),
                    Json({"source": source, "session_created": session_created}),
                ),
            )
            interaction_row = cur.fetchone()

        if interaction_row is None:
            raise HTTPException(status_code=500, detail="interaction log could not be saved")

        session_row = update_session_turn(conn, resolved_session_id)
        conn.commit()

    return {
        "saved": True,
        "session_id": str(resolved_session_id),
        "session_created": session_created,
        "interaction_id": interaction_row["interaction_id"],
        "created_at": normalize_datetime(interaction_row["created_at"]),
        "messages_saved": 2,
        "history_count": len(history),
        "stt_text": text,
        "llm_answer": answer,
        "tts_text": answer,
        "use_sensor_context": use_sensor_context,
        "sensor": normalize_response_payload(active_sensor.model_dump() if active_sensor is not None else None),
        "state": normalize_response_payload(state),
        "llm": normalize_response_payload(llm),
        "session": normalize_response_payload(session_row),
    }
