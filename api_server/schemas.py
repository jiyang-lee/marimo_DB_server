from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SensorPayload(BaseModel):
    temperature: float = Field(..., description="섭씨 온도")
    humidity: float = Field(..., description="상대습도 퍼센트")
    light: float = Field(..., description="조도 센서값")
    water_level: float = Field(..., description="수위 센서값")
    distance: float = Field(..., description="초음파 거리 cm")


class RealtimeSensorPayload(BaseModel):
    light: float = Field(..., description="조도 센서값")
    distance: float = Field(..., description="초음파 거리 cm")


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
