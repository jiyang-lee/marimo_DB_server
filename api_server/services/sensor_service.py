from typing import Any, Optional

from fastapi import HTTPException
from psycopg.types.json import Json

from extensions.db import cleanup_old_realtime_rows, get_db_connection
from schemas import HourlySensorPayload, RealtimeSensorPayload, SensorPayload
from utils import normalize_datetime, normalize_response_payload


def judge_realtime_state(payload: RealtimeSensorPayload) -> dict[str, Any]:
    alerts: list[str] = []

    if payload.light <= 150:
        alerts.append("조도가 낮음")
    if payload.distance <= 10:
        alerts.append("물체가 가까움")
    level = "normal"
    if len(alerts) >= 2:
        level = "danger"
    elif alerts:
        level = "warning"
    return {"level": level, "alerts": alerts}


def judge_hourly_state(payload: HourlySensorPayload) -> dict[str, Any]:
    alerts: list[str] = []

    if payload.temperature >= 30:
        alerts.append("온도가 높음")
    elif payload.temperature <= 15:
        alerts.append("온도가 낮음")

    if payload.humidity >= 75:
        alerts.append("습도가 높음")
    elif payload.humidity <= 30:
        alerts.append("습도가 낮음")

    if payload.water_level <= 20:
        alerts.append("수위가 낮음")

    level = "normal"
    if len(alerts) >= 2:
        level = "danger"
    elif alerts:
        level = "warning"
    return {"level": level, "alerts": alerts}


def judge_sensor_state(sensor: SensorPayload) -> dict[str, Any]:
    realtime_state = judge_realtime_state(
        RealtimeSensorPayload(
            light=sensor.light,
            distance=sensor.distance,
        )
    )
    hourly_state = judge_hourly_state(
        HourlySensorPayload(
            temperature=sensor.temperature,
            humidity=sensor.humidity,
            water_level=sensor.water_level,
        )
    )

    alerts = realtime_state["alerts"] + hourly_state["alerts"]
    level = "normal"
    if len(alerts) >= 3:
        level = "danger"
    elif alerts:
        level = "warning"

    return {"level": level, "alerts": alerts}


def default_sensor_payload() -> SensorPayload:
    return SensorPayload(
        temperature=23.0,
        humidity=50.0,
        light=500.0,
        water_level=50.0,
        distance=100.0,
    )


def extract_payload(row: Optional[dict[str, Any]]) -> dict[str, Any]:
    if row is None:
        return {}
    payload = row.get("payload") or {}
    return dict(payload)


def expand_sensor_row(row: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    payload = extract_payload(row)
    return {
        "reading_id": row["reading_id"],
        "created_at": normalize_datetime(row["created_at"]),
        "sensor_type": row["sensor_type"],
        **payload,
        "state_level": row["state_level"],
        "alerts": row["state_alerts"],
    }


def get_latest_sensor_row(conn, sensor_type: str) -> Optional[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT reading_id, created_at, sensor_type, payload, state_level, state_alerts
            FROM sensor_readings
            WHERE sensor_type = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (sensor_type,),
        )
        return cur.fetchone()


def get_recent_sensor_rows(conn, sensor_type: str, limit: int = 24) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT reading_id, created_at, sensor_type, payload, state_level, state_alerts
            FROM sensor_readings
            WHERE sensor_type = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (sensor_type, limit),
        )
        rows = cur.fetchall() or []

    history: list[dict[str, Any]] = []
    for row in reversed(rows):
        history.append(expand_sensor_row(row))
    return history


def load_latest_sensor_payload() -> SensorPayload:
    fallback = default_sensor_payload().model_dump()
    try:
        with get_db_connection() as conn:
            hourly_row = get_latest_sensor_row(conn, "hourly")
            realtime_row = get_latest_sensor_row(conn, "realtime")
    except Exception:
        return default_sensor_payload()

    hourly_payload = extract_payload(hourly_row)
    realtime_payload = extract_payload(realtime_row)

    if hourly_payload:
        fallback["temperature"] = hourly_payload.get("temperature", fallback["temperature"])
        fallback["humidity"] = hourly_payload.get("humidity", fallback["humidity"])
        fallback["water_level"] = hourly_payload.get("water_level", fallback["water_level"])
    if realtime_payload:
        fallback["light"] = realtime_payload.get("light", fallback["light"])
        fallback["distance"] = realtime_payload.get("distance", fallback["distance"])

    return SensorPayload(**fallback)


def save_sensor_reading(
    payload: dict[str, Any],
    sensor_type: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    deleted_count = cleanup_old_realtime_rows() if sensor_type == "realtime" else 0
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sensor_readings (
                    sensor_type, payload, state_level, state_alerts
                )
                VALUES (%s, %s, %s, %s)
                RETURNING reading_id, created_at
                """,
                (
                    sensor_type,
                    Json(payload),
                    state["level"],
                    Json(state["alerts"]),
                ),
            )
            row = cur.fetchone()
        conn.commit()
    if row is None:
        raise HTTPException(status_code=500, detail="sensor reading could not be saved")
    return {
        "saved": True,
        "table": "sensor_readings",
        "sensor_type": sensor_type,
        "reading_id": row["reading_id"],
        "created_at": normalize_datetime(row["created_at"]),
        "cleanup_deleted_rows": deleted_count,
        "sensor": normalize_response_payload(payload),
        "state": normalize_response_payload(state),
    }


def build_merged_payload(
    realtime_row: Optional[dict[str, Any]],
    hourly_row: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    merged = None
    if realtime_row is not None or hourly_row is not None:
        merged_payload = default_sensor_payload().model_dump()
        if hourly_row is not None:
            hourly_payload = extract_payload(hourly_row)
            merged_payload["temperature"] = hourly_payload.get("temperature", merged_payload["temperature"])
            merged_payload["humidity"] = hourly_payload.get("humidity", merged_payload["humidity"])
            merged_payload["water_level"] = hourly_payload.get("water_level", merged_payload["water_level"])
        if realtime_row is not None:
            realtime_payload = extract_payload(realtime_row)
            merged_payload["light"] = realtime_payload.get("light", merged_payload["light"])
            merged_payload["distance"] = realtime_payload.get("distance", merged_payload["distance"])
        merged = merged_payload
    return merged
