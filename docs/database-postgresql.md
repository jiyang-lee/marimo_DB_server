# PostgreSQL 사용 가이드 (sensor DB)

## 1) 접속 정보

`docker-compose.sensor-db.yml` 기준:

- DB: `marimo`
- USER: `marimo`
- PASSWORD: `marimo`
- 컨테이너명: `marimo-db`
- 포트: `5432:5432`

---

## 2) DB 접속 방법

### 가장 빠른 확인(테이블 이름 + 최근 데이터)

```bash
cd /home/kdt-aiot/project/arduino_server
docker exec marimo-db psql -U marimo -d marimo -c "\dt"
docker exec marimo-db psql -U marimo -d marimo -c "SELECT * FROM realtime_sensor_readings ORDER BY created_at DESC LIMIT 10;"
docker exec marimo-db psql -U marimo -d marimo -c "SELECT * FROM hourly_sensor_readings ORDER BY created_at DESC LIMIT 10;"
```

### 컨테이너 안에서 psql 접속

```bash
cd /home/kdt-aiot/project/arduino_server
docker exec -it marimo-db psql -U marimo -d marimo
```

### 호스트에서 1회 쿼리 실행

```bash
docker exec marimo-db psql -U marimo -d marimo -c "SELECT now();"
docker exec marimo-db psql -U marimo -d marimo -c "\dt"
docker exec marimo-db psql -U marimo -d marimo -c "SELECT * FROM realtime_sensor_readings ORDER BY created_at DESC LIMIT 5;"
docker exec marimo-db psql -U marimo -d marimo -c "SELECT * FROM hourly_sensor_readings ORDER BY created_at DESC LIMIT 5;"
```

---

## 3) 기본 확인 쿼리

테이블 목록:

```sql
\dt
```

실시간 센서(조도/거리/소리) 건수 + 최신 시각:

```sql
SELECT COUNT(*) AS total, MAX(created_at) AS latest_at
FROM realtime_sensor_readings;
```

1시간 센서(온도/습도/수위) 건수 + 최신 시각:

```sql
SELECT COUNT(*) AS total, MAX(created_at) AS latest_at
FROM hourly_sensor_readings;
```

최근 실시간 센서 데이터 10건:

```sql
SELECT *
FROM realtime_sensor_readings
ORDER BY created_at DESC
LIMIT 10;
```

실시간 테이블 1주 지난 데이터 수동 정리:

```sql
DELETE FROM realtime_sensor_readings
WHERE created_at < NOW() - INTERVAL '7 days';
```

최근 1시간 센서 데이터 10건:

```sql
SELECT *
FROM hourly_sensor_readings
ORDER BY created_at DESC
LIMIT 10;
```

최근 음성 상호작용 10건:

```sql
SELECT *
FROM voice_interactions
ORDER BY created_at DESC
LIMIT 10;
```

종료:

```sql
\q
```

---

## 4) API 통해서 확인하는 방법

최신 센서 레코드 조회:

```bash
curl http://127.0.0.1:8000/sensor/latest
```

헬스체크(DB 연결 포함):

```bash
curl http://127.0.0.1:8000/health
```

---

## 5) 현재 확인된 동작 상태

실운영 확인 시점에 다음이 검증됨:

- `marimo-db`: healthy
- `marimo-api-server`: up
- `realtime_sensor_readings`/`hourly_sensor_readings`에 데이터 누적 중
- `/sensor/latest`에서 최신 레코드 반환

---

## 6) 문제 해결 체크리스트

### 데이터가 안 쌓일 때

1. 컨테이너 상태 확인

```bash
docker compose -f docker-compose.sensor-db.yml ps
```

2. API 헬스 확인

```bash
curl http://127.0.0.1:8000/health
```

3. DB 내부 직접 확인

```bash
docker exec marimo-db psql -U marimo -d marimo -c "SELECT COUNT(*) FROM realtime_sensor_readings;"
docker exec marimo-db psql -U marimo -d marimo -c "SELECT COUNT(*) FROM hourly_sensor_readings;"
```

4. Wemos 시리얼 로그에서 `Ingest:` 상태코드 확인 (`200` 정상)

---

## 7) 실시간 테이블 보관 정책

- `realtime_sensor_readings`는 **7일 보관**
- API 서버가 켜질 때 1회 정리
- 이후 실시간 적재 요청 기준으로 **1주 간격**으로 오래된 데이터 자동 삭제
