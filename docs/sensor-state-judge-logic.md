# 센서 판정 로직 설명

## 위치
- 핵심 구현 파일: `api_server/services/sensor_service.py`
- 핵심 함수:
  - `judge_realtime_state(payload)`
  - `judge_hourly_state(payload)`
  - `judge_sensor_state(sensor)`

## 1) 실시간(realtime) 판정: `judge_realtime_state`

입력값
- `light`, `distance`

알림(alert) 규칙
- `light <= 150` → `"조도가 낮음"`
- `distance <= 10` → `"물체가 가까움"`

레벨(level) 규칙
- 알림 0개: `normal`
- 알림 1개: `warning`
- 알림 2개 이상: `danger`

## 2) 시간단위(hourly) 판정: `judge_hourly_state`

입력값
- `temperature`, `humidity`, `water_level`

알림(alert) 규칙
- `temperature >= 30` → `"온도가 높음"`
- `temperature <= 15` → `"온도가 낮음"`
- `humidity >= 75` → `"습도가 높음"`
- `humidity <= 30` → `"습도가 낮음"`
- `water_level <= 20` → `"수위가 낮음"`

레벨(level) 규칙
- 알림 0개: `normal`
- 알림 1개: `warning`
- 알림 2개 이상: `danger`

## 3) 통합 판정: `judge_sensor_state`

동작
1. 센서 전체(`SensorPayload`)를 realtime/hourly 입력 형태로 나눔
2. `judge_realtime_state`와 `judge_hourly_state`를 각각 실행
3. 두 결과의 `alerts`를 합쳐 최종 레벨 계산

최종 레벨(level) 규칙
- 알림 0개: `normal`
- 알림 1~2개: `warning`
- 알림 3개 이상: `danger`

## 4) API에서 사용되는 지점

- `api_server/routers/sensor.py`
  - `/sensor/status`
  - `/sensor/ingest`
  - `/sensor/realtime-ingest`
  - `/sensor/hourly-ingest`
- `api_server/services/interaction_service.py`
  - 대화 처리(`handle_interaction`)에서 `use_sensor_context=True`일 때 통합 판정 수행

## 참고
- 센서 판정 결과는 `{ "level": "...", "alerts": [...] }` 형태를 따름.
- 이 문서의 기준값을 변경하려면 `api_server/services/sensor_service.py`의 임계값 상수/조건을 함께 수정해야 함.
