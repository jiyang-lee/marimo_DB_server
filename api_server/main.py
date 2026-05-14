import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

import httpx
import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from psycopg.rows import dict_row
from psycopg.types.json import Json


LLM_SERVER_URL = os.getenv("LLM_SERVER_URL", "http://llm-server:8000")
DATABASE_URL = os.getenv("DATABASE_URL", "")
DB_TIMEZONE = "Asia/Seoul"
KST = timezone(timedelta(hours=9), name="KST")
REALTIME_RETENTION_DAYS = 7
REALTIME_CLEANUP_INTERVAL_SECONDS = 7 * 24 * 60 * 60
SESSION_HISTORY_LIMIT = 16
last_realtime_cleanup_at: Optional[datetime] = None

app = FastAPI(title="Marimo API Server", version="0.2.0")
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
    water_raw: Optional[int] = Field(None, description="수위 센서 raw ADC 평균값")


class AskPayload(BaseModel):
    question: str
    sensor: SensorPayload
    session_id: Optional[UUID] = None
    use_sensor_context: bool = True


class VoiceAskPayload(BaseModel):
    text: str
    sensor: Optional[SensorPayload] = None
    session_id: Optional[UUID] = None
    use_sensor_context: bool = False


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


@app.on_event("startup")
def startup() -> None:
    init_db()
    cleanup_old_realtime_rows(force=True)


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


def now_kst() -> datetime:
    return datetime.now(KST)


def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(KST)


def normalize_response_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return normalize_datetime(value).isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: normalize_response_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_response_value(item) for item in value]
    if isinstance(value, tuple):
        return [normalize_response_value(item) for item in value]
    return value


def normalize_response_payload(payload: Any) -> Any:
    return normalize_response_value(payload)


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
        fallback["sound"] = realtime_payload.get("sound", fallback["sound"])

    return SensorPayload(**fallback)


def ensure_session(conn, session_id: UUID) -> tuple[dict[str, Any], bool]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO session (session_id)
            VALUES (%s)
            ON CONFLICT (session_id) DO UPDATE
            SET last_seen_at = NOW()
            RETURNING
                session_id,
                created_at,
                last_seen_at,
                ended_at,
                turn_count,
                meta,
                (xmax = 0) AS inserted
            """,
            (session_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=500, detail="session row could not be created")
        inserted = bool(row.pop("inserted", False))
        return row, inserted


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


def fetch_recent_session_messages(conn, session_id: UUID, limit: int = SESSION_HISTORY_LIMIT) -> list[dict[str, str]]:
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
        _, session_created = ensure_session(conn, resolved_session_id)
        history = fetch_recent_session_messages(conn, resolved_session_id)
        save_session_message(
            conn,
            resolved_session_id,
            "user",
            text,
            meta={"source": source, "use_sensor_context": use_sensor_context},
        )
        conn.commit()

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

    with get_db_connection() as conn:
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
        "db": normalize_response_payload(db_status),
    }


@app.post("/sensor/status")
def sensor_status(payload: SensorPayload) -> dict[str, Any]:
    return {"sensor": payload.model_dump(), "state": judge_sensor_state(payload)}


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


@app.post("/sensor/ingest")
def sensor_ingest(payload: RealtimeSensorPayload) -> dict[str, Any]:
    state = judge_realtime_state(payload)
    return save_sensor_reading(payload.model_dump(), "realtime", state)


@app.post("/sensor/realtime-ingest")
def sensor_realtime_ingest(payload: RealtimeSensorPayload) -> dict[str, Any]:
    state = judge_realtime_state(payload)
    return save_sensor_reading(payload.model_dump(), "realtime", state)


@app.post("/sensor/hourly-ingest")
def sensor_hourly_ingest(payload: HourlySensorPayload) -> dict[str, Any]:
    state = judge_hourly_state(payload)
    return save_sensor_reading(payload.model_dump(), "hourly", state)


@app.get("/sensor/latest")
def sensor_latest() -> dict[str, Any]:
    with get_db_connection() as conn:
        realtime_row = get_latest_sensor_row(conn, "realtime")
        hourly_row = get_latest_sensor_row(conn, "hourly")

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
            merged_payload["sound"] = realtime_payload.get("sound", merged_payload["sound"])
        merged = merged_payload

    return {
        "latest_realtime": normalize_response_payload(expand_sensor_row(realtime_row)),
        "latest_hourly": normalize_response_payload(expand_sensor_row(hourly_row)),
        "latest_merged": normalize_response_payload(merged),
    }


@app.post("/ask")
async def ask(payload: AskPayload) -> dict[str, Any]:
    return await handle_interaction(
        session_id=payload.session_id,
        text=payload.question.strip(),
        sensor=payload.sensor,
        use_sensor_context=payload.use_sensor_context,
        source="ask",
    )


@app.post("/voice/ask")
async def voice_ask(payload: VoiceAskPayload) -> dict[str, Any]:
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    return await handle_interaction(
        session_id=payload.session_id,
        text=text,
        sensor=payload.sensor,
        use_sensor_context=payload.use_sensor_context,
        source="voice",
    )
