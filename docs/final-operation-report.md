# 최종 운영 정리 보고서

## 1) 시스템 구성(최종)

MiniPC 기준 실행 구성:

- **API 서버(FastAPI)**: `marimo-api-server` (Docker)
- **DB(PostgreSQL 16)**: `marimo-db` (Docker)
- **센서 노드**: Wemos(ESP8266, MicroPython)
- **(선택)** LLM 서버: Windows에서 별도 실행

핵심 compose 파일:

- `docker-compose.sensor-db.yml`

---

## 2) 네트워크/포트 정보

### Docker 서비스 포트

- API: `8000:8000`
- PostgreSQL: `5432:5432`

### DB 연결 문자열(API 내부)

- `postgresql://marimo:marimo@db:5432/marimo`

### Wemos API 전송 주소(현재 코드 기준)

- 실시간 적재: `http://192.168.219.56:8000/sensor/realtime-ingest`
- 시간대 적재: `http://192.168.219.56:8000/sensor/hourly-ingest`

---

## 3) 센서 수집 주기(최종 반영)

Wemos `arduino/wemos_sensor_node/main.py` 기준:

- **약 3초 주기**: 조도(`light`), 거리(`distance`), 소리(`sound`)
- **30분 주기**: 수위(`water_level`)
- **1시간 주기**: 온도(`temperature`), 습도(`humidity`)

보완 사항:

- 거리 센서가 일시적으로 `None`이어도 마지막 정상 거리값으로 실시간 전송하도록 처리됨

---

## 4) DB 적재 구조(테이블 분리)

현재 운영 테이블:

1. `realtime_sensor_readings`
   - 컬럼: `created_at`, `light`, `distance`, `sound`, `state_level`, `alerts`
   - 입력 경로: `POST /sensor/realtime-ingest` (및 호환 경로 `/sensor/ingest`)
2. `hourly_sensor_readings`
   - 컬럼: `created_at`, `temperature`, `humidity`, `water_level`, `state_level`, `alerts`
   - 입력 경로: `POST /sensor/hourly-ingest`
3. `voice_interactions`
   - 음성 질의 이력 저장

정리:

- 레거시 `sensor_readings` 테이블은 삭제 완료

---

## 5) 데이터 흐름(입력 → 저장)

1. Wemos가 센서 값을 읽음
2. 실시간 센서값(조도/거리/소리)을 API `/sensor/realtime-ingest`로 전송
3. 주기 도달 시 온습도/수위를 API `/sensor/hourly-ingest`로 전송
4. API가 PostgreSQL에 각각의 테이블로 INSERT
5. 조회 시 `/sensor/latest`에서 실시간/시간대/병합 최신값 반환

---

## 6) 보관 정책(용량 관리)

실시간 테이블 보관 정책:

- `realtime_sensor_readings`는 **7일 보관**
- API 서버 시작 시 1회 정리
- 이후 실시간 적재 요청 흐름에서 **1주 간격 자동 정리**

수동 정리 SQL:

```sql
DELETE FROM realtime_sensor_readings
WHERE created_at < NOW() - INTERVAL '7 days';
```

---

## 7) 운영/점검 명령어

### 컨테이너 상태

```bash
cd /home/kdt-aiot/project/arduino_server
docker compose -f docker-compose.sensor-db.yml ps
```

### API 헬스체크

```bash
curl http://127.0.0.1:8000/health
```

### DB 테이블/데이터 확인

```bash
docker exec marimo-db psql -U marimo -d marimo -c "\dt"
docker exec marimo-db psql -U marimo -d marimo -c "SELECT * FROM realtime_sensor_readings ORDER BY created_at DESC LIMIT 10;"
docker exec marimo-db psql -U marimo -d marimo -c "SELECT * FROM hourly_sensor_readings ORDER BY created_at DESC LIMIT 10;"
```

### API 재반영(코드 변경 시)

```bash
docker compose -f docker-compose.sensor-db.yml up -d --build api-server
```

---

## 8) Wemos 로그 확인

```bash
cd /home/kdt-aiot/project/arduino_server
source .venv312/bin/activate
python -m serial.tools.miniterm /dev/ttyUSB0 115200
```

- 종료: `Ctrl + ]`
- 정상 전송 예: `Realtime ingest: 200`, `Hourly ingest: 200`
