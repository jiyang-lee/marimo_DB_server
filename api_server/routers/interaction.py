from typing import Any

from fastapi import APIRouter, HTTPException

from schemas import AskPayload, VoiceAskPayload
from services.interaction_service import handle_interaction

router = APIRouter()


@router.post("/ask")
async def ask(payload: AskPayload) -> dict[str, Any]:
    return await handle_interaction(
        session_id=payload.session_id,
        text=payload.question.strip(),
        sensor=payload.sensor,
        use_sensor_context=payload.use_sensor_context,
        source="ask",
    )


@router.post("/voice/ask")
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
