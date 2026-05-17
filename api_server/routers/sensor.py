from typing import Any

from fastapi import APIRouter

from extensions.db import get_db_connection
from schemas import HourlySensorPayload, RealtimeSensorPayload, SensorPayload
from services.sensor_service import (
    build_merged_payload,
    expand_sensor_row,
    get_latest_sensor_row,
    get_recent_sensor_rows,
    judge_hourly_state,
    judge_realtime_state,
    judge_sensor_state,
    save_sensor_reading,
)
from utils import normalize_response_payload

router = APIRouter()


@router.post("/sensor/status")
def sensor_status(payload: SensorPayload) -> dict[str, Any]:
    return {"sensor": payload.model_dump(), "state": judge_sensor_state(payload)}


@router.post("/sensor/ingest")
def sensor_ingest(payload: RealtimeSensorPayload) -> dict[str, Any]:
    state = judge_realtime_state(payload)
    return save_sensor_reading(payload.model_dump(), "realtime", state)


@router.post("/sensor/realtime-ingest")
def sensor_realtime_ingest(payload: RealtimeSensorPayload) -> dict[str, Any]:
    state = judge_realtime_state(payload)
    return save_sensor_reading(payload.model_dump(), "realtime", state)


@router.post("/sensor/hourly-ingest")
def sensor_hourly_ingest(payload: HourlySensorPayload) -> dict[str, Any]:
    state = judge_hourly_state(payload)
    return save_sensor_reading(payload.model_dump(), "hourly", state)


@router.get("/sensor/latest")
def sensor_latest() -> dict[str, Any]:
    with get_db_connection() as conn:
        realtime_row = get_latest_sensor_row(conn, "realtime")
        hourly_row = get_latest_sensor_row(conn, "hourly")

    merged = build_merged_payload(realtime_row, hourly_row)
    return {
        "latest_realtime": normalize_response_payload(expand_sensor_row(realtime_row)),
        "latest_hourly": normalize_response_payload(expand_sensor_row(hourly_row)),
        "latest_merged": normalize_response_payload(merged),
    }


@router.get("/sensor/history")
def sensor_history(limit: int = 24) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 120))
    with get_db_connection() as conn:
        realtime_rows = get_recent_sensor_rows(conn, "realtime", safe_limit)
        hourly_rows = get_recent_sensor_rows(conn, "hourly", safe_limit)
        realtime_row = get_latest_sensor_row(conn, "realtime")
        hourly_row = get_latest_sensor_row(conn, "hourly")

    merged = build_merged_payload(realtime_row, hourly_row)
    return {
        "limit": safe_limit,
        "latest_realtime": normalize_response_payload(expand_sensor_row(realtime_row)),
        "latest_hourly": normalize_response_payload(expand_sensor_row(hourly_row)),
        "latest_merged": normalize_response_payload(merged),
        "realtime_history": normalize_response_payload(realtime_rows),
        "hourly_history": normalize_response_payload(hourly_rows),
    }
