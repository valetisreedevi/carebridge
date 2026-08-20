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

    # Shared secret Cloud Scheduler sends on the internal worker endpoint.
    worker_token: str = os.getenv("WORKER_TOKEN", "local-worker-token")

    default_retry_after_minutes: int = 10
    default_max_attempts: int = 2

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
