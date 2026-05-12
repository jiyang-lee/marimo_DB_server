# Docker 실행 가이드 (MiniPC 기준)

## 1) 현재 구성 요약

이 프로젝트는 `docker-compose.sensor-db.yml`로 아래 2개 컨테이너를 실행합니다.

- `db`: PostgreSQL 16
- `api-server`: FastAPI 서버 (`uvicorn main:app`)

핵심 파일:

- `docker-compose.sensor-db.yml`
- `Dockerfile`
- `requirements-api.txt`
- `api_server/main.py`

---

## 2) 실행 전 확인

```bash
docker info
docker compose version
```

Compose 파일 문법 확인:

```bash
docker compose -f docker-compose.sensor-db.yml config --quiet
```

---

## 3) 컨테이너 실행

```bash
cd /home/kdt-aiot/project/arduino_server
docker compose -f docker-compose.sensor-db.yml up -d --build
```

상태 확인:

```bash
docker compose -f docker-compose.sensor-db.yml ps
```

정상 예시:

- `marimo-db` → `Up (healthy)`
- `marimo-api-server` → `Up`

---

## 4) API 헬스체크

```bash
curl http://127.0.0.1:8000/health
```

정상 응답 예시:

```json
{
  "ok": true,
  "server": "api",
  "db": {
    "configured": true,
    "ok": true
  }
}
```

---

## 5) LLM 서버를 Windows에서 띄우는 경우

현재 compose에는 `llm-server` 서비스가 없으므로, API 컨테이너 내부에서 `http://llm-server:8000`은 기본적으로 해석되지 않습니다.

권장 방식:

1. `LLM_SERVER_URL`을 외부 주소로 지정
2. 필요 시 `host.docker.internal` 사용

예시:

```bash
LLM_SERVER_URL=http://<WINDOWS_IP>:8000 docker compose -f docker-compose.sensor-db.yml up -d --build
```

참고:

- 센서 적재(`/sensor/ingest`)는 DB 경로만 사용하므로 LLM 서버가 없어도 동작합니다.
- `/ask`, `/voice/ask`는 LLM 서버 연결이 필요합니다.

---

## 6) 자주 발생한 문제와 해결

### 문제: Wemos에서 `ECONNRESET`

원인:

- MiniPC의 API 서버(`:8000`)가 떠 있지 않았음

해결:

```bash
docker compose -f docker-compose.sensor-db.yml up -d --build
curl http://127.0.0.1:8000/health
```

`/health` 응답이 정상인 뒤 Wemos 로그에서 `Ingest: 200` 확인.

---

## 7) 운영용 기본 명령

로그 보기:

```bash
docker compose -f docker-compose.sensor-db.yml logs -f api-server
docker compose -f docker-compose.sensor-db.yml logs -f db
```

중지:

```bash
docker compose -f docker-compose.sensor-db.yml down
```

중지 + 볼륨 삭제(데이터 초기화):

```bash
docker compose -f docker-compose.sensor-db.yml down -v
```
