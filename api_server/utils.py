from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from config import KST


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
