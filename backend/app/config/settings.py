import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


class Settings(BaseSettings):
    gcp_project_id: str = os.getenv("GCP_PROJECT_ID", "")
    gcp_location: str = os.getenv("GCP_LOCATION", "us-central1")
    gcs_bucket_name: str = os.getenv("GCS_BUCKET_NAME", "")

    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

    # When false the API trusts the X-Caregiver-Id header instead of a
    # Firebase ID token. Local development and demos only.
    auth_enabled: bool = os.getenv("AUTH_ENABLED", "false").lower() == "true"
    dev_caregiver_id: str = os.getenv("DEV_CAREGIVER_ID", "dev-caregiver")

    # Turns away caregivers who have not clicked the link in their sign-up
    # email. Off by default so local runs and demos are not blocked on a inbox.
    require_verified_email: bool = (
        os.getenv("REQUIRE_VERIFIED_EMAIL", "false").lower() == "true"
    )

    # Shared secret Cloud Scheduler sends on the internal worker endpoint.
    worker_token: str = os.getenv("WORKER_TOKEN", "local-worker-token")

    default_retry_after_minutes: int = 10
    default_max_attempts: int = 2

    # A snooze is a real answer, so it does not burn an attempt. These two stop
    # that exemption becoming a way to put a dose off forever.
    max_snoozes: int = 3
    escalate_after_minutes: int = 90

    # How a caregiver is reached, in order, each step tried only if the one
    # before it went unanswered. Push alone fails closed and silently: no
    # granted permission means the alert is a database row nobody sees.
    #
    # A delimited string, not a list: pydantic-settings parses list-typed env
    # vars as JSON before any validator runs, which stops the app booting.
    escalation_channels_raw: str = os.getenv("ESCALATION_CHANNELS", "push,email")

    # How long a step is given before the next one is tried.
    escalation_step_minutes: int = int(os.getenv("ESCALATION_STEP_MINUTES", "5"))

    @property
    def escalation_channels(self) -> list[str]:
        return [c.strip() for c in self.escalation_channels_raw.split(",") if c.strip()]

    # Email escalation. The password is never held here; it arrives from Secret
    # Manager as an env var, the same way the worker token does.
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from: str = os.getenv("SMTP_FROM", "")

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_password)

    @field_validator("worker_token")
    @classmethod
    def _trim_worker_token(cls, value: str) -> str:
        """A secret written from a shell carries a trailing newline.

        Cloud Run keeps it in the env var while the sender's command
        substitution strips it, so the two never compare equal. This must be a
        validator, not a stripped default: pydantic-settings reads the field
        straight from the environment and overwrites any default.
        """
        return value.strip()

    # Deliberately a string, not a list. pydantic-settings parses env vars for
    # list-typed fields as JSON at the source layer, before any validator runs,
    # so a plain delimited CORS_ORIGINS would stop the app from starting.
    # Semicolons are accepted because gcloud --set-env-vars claims the comma.
    cors_origins_raw: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:3000,http://127.0.0.1:3000"
    )

    @property
    def cors_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins_raw.replace(";", ",").split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
