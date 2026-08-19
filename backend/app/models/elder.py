from dataclasses import dataclass
from datetime import datetime


@dataclass
class Elder:
    name: str
    caregiver_id: str
    phone: str | None = None
    preferred_language: str = "en"
    timezone: str = "Asia/Kolkata"
    created_at: datetime | None = None
