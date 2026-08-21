import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator

from app.models.medication import FoodInstruction, Frequency

TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _known_timezone(value: str) -> str:
    """Rejects a timezone the server cannot resolve.

    Without this an unknown name is accepted and silently treated as UTC, which
    schedules every reminder at the wrong hour with nothing to show for it.
    """
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"{value!r} is not a known IANA timezone")
    return value


class CreateElderRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=32)
    preferred_language: str = Field(default="en", max_length=8)
    timezone: str = Field(default="Asia/Kolkata", max_length=64)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        return _known_timezone(value)


class UpdateElderRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=32)
    preferred_language: str | None = Field(default=None, max_length=8)
    timezone: str | None = Field(default=None, max_length=64)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        return None if value is None else _known_timezone(value)


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
    # Set once the caregiver has been shown the medicine they already have and
    # has said they meant a separate one anyway.
    allow_duplicate: bool = False

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


class RegisterMyDeviceRequest(BaseModel):
    """A paired phone offering its own notification address.

    No elder_id: it comes from the device's credentials, so a phone cannot
    sign itself up for somebody else.
    """

    fcm_token: str = Field(min_length=10, max_length=4096)
    platform: str = Field(default="WEB", max_length=16)
    label: str | None = Field(default=None, max_length=60)


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


class MarkTakenRequest(BaseModel):
    """Which of a medicine's scheduled times the caregiver is closing."""

    local_time: str = Field(pattern=TIME_PATTERN.pattern)


class RemindNowRequest(BaseModel):
    """Which of today's scheduled doses to ring about.

    The dashboard knows the row that was pressed. Without it the nearest
    scheduled time is chosen, but never the current minute - that is not a
    dose anybody was prescribed.
    """

    local_time: str | None = Field(default=None, pattern=TIME_PATTERN.pattern)


class AcceptInviteRequest(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class RedeemPairingCodeRequest(BaseModel):
    """The code an elder types into their phone."""

    code: str = Field(min_length=6, max_length=32)
