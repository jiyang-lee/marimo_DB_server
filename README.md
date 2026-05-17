# Marimo Alpha Fix

> **Branch:** `alpha_fix`  
> IoT 센서(조도·거리·온습도·토양수분)를 수집하고 PostgreSQL에 저장하며, FastAPI 기반 REST API와 LLM 음성 대화를 연동하는 통합 서버입니다.

---

## Architecture

```
┌─────────────────┐      HTTP      ┌─────────────────────────┐
│  Wemos D1 mini  │ ◄────────────► │   Marimo API Server     │
│ (Sensor Node)   │  sensor data   │   (FastAPI + psycopg)   │
└─────────────────┘                └───────────┬─────────────┘
                                               │
                                               │ SQL
                                               ▼
                                      ┌────────────────┐
                                      │  PostgreSQL 16 │
                                      │   (Docker)     │
                                      └────────────────┘
                                               ▲
                                               │ HTTP
┌─────────────────┐                ┌───────────┴─────────────┐
│  Voice / Web    │ ◄────────────► │      LLM Server         │
│    Client       │   ask / voice  │   (External: :8001)     │
└─────────────────┘                └─────────────────────────┘
```

---

## Features

- **Sensor Ingestion**
  - `realtime`: 조도(BH1750) + 초음파 거리(HC-SR04) — 3초 주기
  - `hourly`: 온습도(DHT11) + 토양 수분 — 1시간 주기
- **Session Management**
  - UUID 기반 대화 세션 생성 및 히스토리 조회
- **LLM Interaction**
  - `/ask` — 텍스트 기반 질의
  - `/voice/ask` — 음성(STT) 기반 질의
  - 센서 컨텍스트를 함께 전달하여 상태 기반 응답
- **Auto DB Migration**
  - 서버 시작 시 `session`, `session_message`, `sensor_readings`, `interaction_log` 테이블 자동 생성
- **Data Retention**
  - `realtime` 데이터 7일 자동 정리

---

## Directory Structure

```
.
├── api_server/                 # FastAPI application
│   ├── app.py                  # App factory (create_app)
│   ├── config.py               # Env-based configuration
│   ├── extensions/
│   │   └── db.py               # psycopg connection + init_db + cleanup
│   ├── routers/
│   │   ├── health.py           # GET /health
│   │   ├── sensor.py           # POST /sensor/{ingest,realtime-ingest,hourly-ingest}
│   │   ├── sessions.py         # GET /sessions, /sessions/{id}
│   │   └── interaction.py      # POST /ask, /voice/ask
│   ├── services/
│   │   ├── sensor_service.py   # Sensor state judgement & persistence
│   │   ├── session_service.py  # Session CRUD
│   │   └── interaction_service.py  # LLM proxy & interaction logging
│   ├── tests/                  # pytest suite
│   ├── utils.py                # Response normalizer + KST helper
│   └── main.py                 # Entrypoint: uvicorn runner
├── arduino/
│   └── wemos_sensor_node/
│       └── main.py             # MicroPython firmware
├── docker-compose.sensor-db.yml
├── Dockerfile
├── requirements-api.txt
└── .github/workflows/api-ci.yml
```

---

## Quick Start

### 1. Clone & Checkout

```bash
git clone https://github.com/jiyang-lee/marimo_DB_server.git
cd marimo_DB_server
git checkout alpha_fix
```

### 2. Environment

No `.env` file is required for local Docker usage, but you can override:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql://marimo:marimo@db:5432/marimo` | Postgres connection string |
| `LLM_SERVER_URL` | `http://192.168.219.43:8001` | External LLM server endpoint |

### 3. Run with Docker Compose

```bash
docker compose -f docker-compose.sensor-db.yml up --build -d
```

- API Server → http://localhost:8000
- API Docs (Swagger) → http://localhost:8000/docs
- PostgreSQL → localhost:5432

### 4. Verify

```bash
curl http://localhost:8000/health
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | DB & LLM connectivity check |
| `POST` | `/sensor/status` | Evaluate a single sensor payload state |
| `POST` | `/sensor/realtime-ingest` | Ingest realtime sensor data |
| `POST` | `/sensor/hourly-ingest` | Ingest hourly sensor data |
| `GET` | `/sensor/latest` | Latest realtime + hourly merged |
| `GET` | `/sensor/history?limit=24` | Recent sensor history |
| `GET` | `/sessions?limit=20` | List sessions |
| `GET` | `/sessions/{session_id}` | Session detail with messages |
| `POST` | `/ask` | Text interaction with LLM |
| `POST` | `/voice/ask` | Voice interaction with LLM |

---

## Sensor Node (Wemos D1 mini)

Upload `arduino/wemos_sensor_node/main.py` via MicroPython.

**Wiring**

| Sensor | GPIO | Note |
|---|---|---|
| DHT11 | 13 | Temperature / Humidity |
| BH1750 (I2C) | SCL=5, SDA=4 | Light (lux) |
| HC-SR04 | TRIG=14, ECHO=12 | Distance |
| Soil Moisture | ADC0 | Power via GPIO 14 |
| I2C LCD | SCL=5, SDA=4 | 0x27 or 0x3F |

**Wi-Fi & API Target**

Edit in `main.py` before flashing:

```python
WIFI_SSID = "U+NetE3CC"
WIFI_PASSWORD = "G7D99A@476"
REALTIME_INGEST_URL = "http://192.168.219.56:8000/sensor/realtime-ingest"
HOURLY_INGEST_URL = "http://192.168.219.56:8000/sensor/hourly-ingest"
```

---

## Running Tests

```bash
cd api_server
python -m pytest tests/ -v
```

---

## CI

GitHub Actions workflow (`.github/workflows/api-ci.yml`) runs `pytest` on every push to `alpha_fix`.

---

## License

MIT
