# Marimo Alpha RAG FAQ

## 세션은 어떻게 유지하나?
- 세션은 UUID `session_id`로 유지한다.
- `session_message`에 user/assistant 메시지가 저장된다.
- 음성 클라이언트와 테스트 콘솔은 같은 `session_id`를 재사용한다.

## 센서 데이터는 어떻게 읽나?
- 최신 센서는 `sensor_readings`에서 읽는다.
- `realtime`는 조도/거리/소리 중심이다.
- `hourly`는 온도/습도/수위를 담는다.
- `sensor_readings.payload`는 JSONB다.

## 언제 센서 문맥을 답변에 넣나?
- `use_sensor_context`가 true일 때 넣는다.
- 센서 상태가 warning 또는 danger면 관련 안내를 짧게 붙인다.
- 센서 문맥이 없으면 일반 대화처럼 답한다.

## 음성 대화는 어떻게 저장되나?
- `/voice/ask`는 STT 텍스트, LLM 답변, TTS 텍스트를 `interaction_log`에 저장한다.
- 같은 세션의 최근 메시지도 `session_message`에 남는다.
- 음성 테스트 콘솔은 브라우저 `localStorage`로 `session_id`를 유지한다.

## 운영에서 주의할 점은?
- realtime 데이터는 장기 보관하지 않고 정리한다.
- hourly 데이터는 알파에서는 유지한다.
- 시간 표시는 KST로 본다.
- 웹훅이나 비밀값은 GitHub에 남기지 않는다.

## 지금 아직 없는 기능은?
- 명시적인 `session end API`는 아직 없다.
- 벡터DB 기반 RAG는 아직 넣지 않았다.
- FAQ는 우선 파일 기반 검색으로만 쓴다.
