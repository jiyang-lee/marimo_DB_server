import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from psycopg.rows import dict_row


LLM_SERVER_URL = os.getenv("LLM_SERVER_URL", "http://llm-server:8000")
DATABASE_URL = os.getenv("DATABASE_URL", "")
REALTIME_RETENTION_DAYS = 7
REALTIME_CLEANUP_INTERVAL_SECONDS = 7 * 24 * 60 * 60
last_realtime_cleanup_at: Optional[datetime] = None

app = FastAPI(title="Marimo API Server", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SensorPayload(BaseModel):
    temperature: float = Field(..., description="섭씨 온도")
    humidity: float = Field(..., description="상대습도 퍼센트")
    light: float = Field(..., description="조도 센서값")
    water_level: float = Field(..., description="수위 센서값")
    distance: float = Field(..., description="초음파 거리 cm")
    sound: float = Field(..., description="소리 센서값")


class RealtimeSensorPayload(BaseModel):
    light: float = Field(..., description="조도 센서값")
    distance: float = Field(..., description="초음파 거리 cm")
    sound: float = Field(..., description="소리 센서값")


class HourlySensorPayload(BaseModel):
    temperature: float = Field(..., description="섭씨 온도")
    humidity: float = Field(..., description="상대습도 퍼센트")
    water_level: float = Field(..., description="수위 센서값")


class AskPayload(BaseModel):
    question: str
    sensor: SensorPayload


class VoiceAskPayload(BaseModel):
    text: str
    sensor: Optional[SensorPayload] = None
    use_sensor_context: bool = False


def get_db_connection():
    if not DATABASE_URL:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db() -> None:
    if not DATABASE_URL:
        return

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS realtime_sensor_readings (
                    id BIGSERIAL PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    light DOUBLE PRECISION NOT NULL,
                    distance DOUBLE PRECISION NOT NULL,
                    sound DOUBLE PRECISION NOT NULL,
                    state_level TEXT NOT NULL,
                    alerts TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS hourly_sensor_readings (
                    id BIGSERIAL PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    temperature DOUBLE PRECISION NOT NULL,
                    humidity DOUBLE PRECISION NOT NULL,
                    water_level DOUBLE PRECISION NOT NULL,
                    state_level TEXT NOT NULL,
                    alerts TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS voice_interactions (
                    id BIGSERIAL PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    stt_text TEXT NOT NULL,
                    llm_answer TEXT NOT NULL,
                    tts_text TEXT NOT NULL,
                    sensor_json TEXT NOT NULL,
                    state_level TEXT NOT NULL,
                    state_alerts TEXT NOT NULL
                )
                """
            )
        conn.commit()


@app.on_event("startup")
def startup() -> None:
    init_db()
    cleanup_old_realtime_rows(force=True)


def cleanup_old_realtime_rows(force: bool = False) -> int:
    global last_realtime_cleanup_at

    now = datetime.now(timezone.utc)
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
                DELETE FROM realtime_sensor_readings
                WHERE created_at < NOW() - (%s * INTERVAL '1 day')
                RETURNING id
                """,
                (REALTIME_RETENTION_DAYS,),
            )
            deleted_count = cur.rowcount
        conn.commit()

    last_realtime_cleanup_at = now
    return deleted_count


def judge_realtime_state(payload: RealtimeSensorPayload) -> dict[str, Any]:
    alerts: list[str] = []

    if payload.light <= 150:
        alerts.append("조도가 낮음")
    if payload.distance <= 10:
        alerts.append("물체가 가까움")
    if payload.sound >= 700:
        alerts.append("소음이 큼")

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
            sound=sensor.sound,
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
        sound=0.0,
    )


def load_latest_sensor_payload() -> SensorPayload:
    fallback = default_sensor_payload().model_dump()
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT temperature, humidity, water_level
                    FROM hourly_sensor_readings
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
                hourly_row = cur.fetchone()
                cur.execute(
                    """
                    SELECT light, distance, sound
                    FROM realtime_sensor_readings
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                )
                realtime_row = cur.fetchone()
    except Exception:
        return default_sensor_payload()

    if hourly_row is not None:
        fallback["temperature"] = hourly_row["temperature"]
        fallback["humidity"] = hourly_row["humidity"]
        fallback["water_level"] = hourly_row["water_level"]
    if realtime_row is not None:
        fallback["light"] = realtime_row["light"]
        fallback["distance"] = realtime_row["distance"]
        fallback["sound"] = realtime_row["sound"]

    return SensorPayload(**fallback)


async def request_llm(
    question: str,
    sensor: Optional[SensorPayload],
    state: Optional[dict[str, Any]],
    use_sensor_context: bool,
) -> dict[str, Any]:
    request_body = {
        "question": question,
        "sensor": sensor.model_dump() if sensor is not None else None,
        "state": state,
        "use_sensor_context": use_sensor_context,
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{LLM_SERVER_URL}/generate", json=request_body)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"LLM server error: {exc}") from exc
    return response.json()


@app.get("/health")
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
        "db": db_status,
    }


@app.post("/sensor/status")
def sensor_status(payload: SensorPayload) -> dict[str, Any]:
    return {"sensor": payload.model_dump(), "state": judge_sensor_state(payload)}


def save_realtime_ingest(payload: RealtimeSensorPayload) -> dict[str, Any]:
    deleted_count = cleanup_old_realtime_rows()
    state = judge_realtime_state(payload)
    alerts = ", ".join(state["alerts"])
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO realtime_sensor_readings (
                    light, distance, sound, state_level, alerts
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, created_at
                """,
                (
                    payload.light,
                    payload.distance,
                    payload.sound,
                    state["level"],
                    alerts,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return {
        "saved": True,
        "table": "realtime_sensor_readings",
        "id": row["id"],
        "created_at": row["created_at"],
        "cleanup_deleted_rows": deleted_count,
        "sensor": payload.model_dump(),
        "state": state,
    }


def save_hourly_ingest(payload: HourlySensorPayload) -> dict[str, Any]:
    state = judge_hourly_state(payload)
    alerts = ", ".join(state["alerts"])
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO hourly_sensor_readings (
                    temperature, humidity, water_level, state_level, alerts
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, created_at
                """,
                (
                    payload.temperature,
                    payload.humidity,
                    payload.water_level,
                    state["level"],
                    alerts,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return {
        "saved": True,
        "table": "hourly_sensor_readings",
        "id": row["id"],
        "created_at": row["created_at"],
        "sensor": payload.model_dump(),
        "state": state,
    }


@app.post("/sensor/ingest")
def sensor_ingest(payload: RealtimeSensorPayload) -> dict[str, Any]:
    return save_realtime_ingest(payload)


@app.post("/sensor/realtime-ingest")
def sensor_realtime_ingest(payload: RealtimeSensorPayload) -> dict[str, Any]:
    return save_realtime_ingest(payload)


@app.post("/sensor/hourly-ingest")
def sensor_hourly_ingest(payload: HourlySensorPayload) -> dict[str, Any]:
    return save_hourly_ingest(payload)


@app.get("/sensor/latest")
def sensor_latest() -> dict[str, Any]:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM realtime_sensor_readings
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
            realtime_row = cur.fetchone()
            cur.execute(
                """
                SELECT *
                FROM hourly_sensor_readings
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
            hourly_row = cur.fetchone()

    merged = None
    if realtime_row is not None or hourly_row is not None:
        merged = load_latest_sensor_payload().model_dump()

    return {
        "latest_realtime": realtime_row,
        "latest_hourly": hourly_row,
        "latest_merged": merged,
    }


@app.post("/ask")
async def ask(payload: AskPayload) -> dict[str, Any]:
    state = judge_sensor_state(payload.sensor)
    llm = await request_llm(payload.question, payload.sensor, state, use_sensor_context=True)

    return {
        "sensor": payload.sensor.model_dump(),
        "state": state,
        "llm": llm,
    }


@app.post("/voice/ask")
async def voice_ask(payload: VoiceAskPayload) -> dict[str, Any]:
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    sensor: Optional[SensorPayload] = None
    state: dict[str, Any] = {"level": "chat", "alerts": []}
    if payload.use_sensor_context:
        sensor = payload.sensor or load_latest_sensor_payload()
        state = judge_sensor_state(sensor)

    llm = await request_llm(text, sensor, state, use_sensor_context=payload.use_sensor_context)
    answer = str(llm.get("answer", "")).strip()
    if not answer:
        raise HTTPException(status_code=502, detail="LLM response has no answer")

    alerts = ", ".join(state["alerts"])
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO voice_interactions (
                    stt_text, llm_answer, tts_text, sensor_json, state_level, state_alerts
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, created_at
                """,
                (
                    text,
                    answer,
                    answer,
                    json.dumps(sensor.model_dump(), ensure_ascii=False) if sensor is not None else "{}",
                    state["level"],
                    alerts,
                ),
            )
            row = cur.fetchone()
        conn.commit()

    return {
        "saved": True,
        "id": row["id"],
        "created_at": row["created_at"],
        "stt_text": text,
        "llm_answer": answer,
        "tts_text": answer,
        "use_sensor_context": payload.use_sensor_context,
        "sensor": sensor.model_dump() if sensor is not None else None,
        "state": state,
        "llm": llm,
    }
