import re

from pydantic import BaseModel, Field, field_validator

from app.models.medication import FoodInstruction, Frequency

TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class CreateElderRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=32)
    preferred_language: str = Field(default="en", max_length=8)
    timezone: str = Field(default="Asia/Kolkata", max_length=64)


class CreateMedicationRequest(BaseModel):
    elder_id: str
    name: str = Field(min_length=1, max_length=120)
    dose: str = Field(min_length=1, max_length=60)
    food_instruction: FoodInstruction
    schedule_times: list[str] = Field(min_length=1, max_length=6)
    frequency: Frequency = Frequency.DAILY
    notes: str | None = Field(default=None, max_length=500)
    retry_after_minutes: int = Field(default=10, ge=1, le=120)
    max_attempts: int = Field(default=2, ge=1, le=5)

    @field_validator("schedule_times")
    @classmethod
    def validate_times(cls, values: list[str]) -> list[str]:
        for value in values:
            if not TIME_PATTERN.match(value):
                raise ValueError(f"{value!r} is not a 24-hour HH:MM time")
        return sorted(set(values))


class UpdateMedicationRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    dose: str | None = Field(default=None, min_length=1, max_length=60)
    food_instruction: FoodInstruction | None = None
    schedule_times: list[str] | None = Field(default=None, min_length=1, max_length=6)
    notes: str | None = Field(default=None, max_length=500)
    retry_after_minutes: int | None = Field(default=None, ge=1, le=120)
    max_attempts: int | None = Field(default=None, ge=1, le=5)
    active: bool | None = None

    @field_validator("schedule_times")
    @classmethod
    def validate_times(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        for value in values:
            if not TIME_PATTERN.match(value):
                raise ValueError(f"{value!r} is not a 24-hour HH:MM time")
        return sorted(set(values))


class RegisterDeviceRequest(BaseModel):
    elder_id: str
    fcm_token: str = Field(min_length=10, max_length=4096)
    platform: str = Field(default="ANDROID", max_length=16)


class RegisterCaregiverTokenRequest(BaseModel):
    fcm_token: str = Field(min_length=10, max_length=4096)


class SnoozeRequest(BaseModel):
    minutes: int = Field(default=10, ge=1, le=60)


class DeclineRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class AgentChatRequest(BaseModel):
    elder_id: str
    event_id: str | None = None
    message: str = Field(min_length=1, max_length=1000)


class TriggerReminderRequest(BaseModel):
    """Fires a medication now instead of waiting for its scheduled time."""

    medication_id: str
