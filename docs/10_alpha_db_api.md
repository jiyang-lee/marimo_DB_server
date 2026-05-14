# 알파 1차 DB / API 반영 노트

## 반영 내용
- `session_id`는 UUID로 관리
- 대화는 `session` / `session_message`에 저장
- 센서 원본은 `sensor_readings`에 저장
- 음성/질의 요약은 `interaction_log`에 저장
- RAG용 `retrieval_chunk`는 아직 미반영

## API 흐름
1. 요청이 오면 세션을 생성하거나 갱신
2. user 메시지를 `session_message`에 저장
3. 최근 세션 메시지를 읽어 LLM history로 전달
4. assistant 응답을 `session_message`에 저장
5. `interaction_log`에 STT/LLM/TTS 요약 저장
6. 세션의 `turn_count`와 `last_seen_at` 갱신

## 센서 저장
- `/sensor/realtime-ingest`와 `/sensor/hourly-ingest`는 둘 다 `sensor_readings`로 적재
- `payload`는 JSONB로 저장
- 최신값 조회는 `sensor_type` 기준으로 분리

## 현재 상태
- 코드 반영 완료
- 컴파일 확인 완료
- 다음 단계는 센서 노드와 세션 유지 클라이언트 연동
