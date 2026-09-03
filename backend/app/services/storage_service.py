import logging
from datetime import timedelta
from functools import lru_cache

import google.auth
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.cloud import storage

from app.config import get_settings

logger = logging.getLogger(__name__)

IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
AUDIO_TYPES = {"audio/mpeg", "audio/mp4", "audio/webm", "audio/wav", "audio/ogg"}

EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/webm": "webm",
    "audio/wav": "wav",
    "audio/ogg": "ogg",
}


class StorageService:

    def __init__(self, bucket_name: str | None = None):
        settings = get_settings()
        self.client = storage.Client(project=settings.gcp_project_id or None)
        self.bucket = self.client.bucket(bucket_name or settings.gcs_bucket_name)

    def _upload(
        self,
        content: bytes,
        object_name: str,
        content_type: str,
    ) -> str:
        blob = self.bucket.blob(object_name)
        blob.upload_from_string(content, content_type=content_type)
        return object_name

    def upload_medicine_photo(
        self,
        content: bytes,
        content_type: str,
        elder_id: str,
        medication_id: str,
    ) -> str:
        extension = EXTENSIONS[content_type]
        return self._upload(
            content,
            f"medicine-images/{elder_id}/{medication_id}.{extension}",
            content_type,
        )

    def upload_caregiver_audio(
        self,
        content: bytes,
        content_type: str,
        elder_id: str,
        medication_id: str,
    ) -> str:
        extension = EXTENSIONS[content_type]
        return self._upload(
            content,
            f"caregiver-audio/{elder_id}/{medication_id}.{extension}",
            content_type,
        )

    def read(self, object_name: str) -> tuple[bytes, str]:
        blob = self.bucket.blob(object_name)
        blob.reload()
        return blob.download_as_bytes(), blob.content_type or "application/octet-stream"

    def signed_url(self, object_name: str, minutes: int = 60) -> str | None:
        """Direct browser/app access without proxying through the API.

        On Cloud Run there is no private key to sign with — the runtime holds
        a token, not a key — so signing has to go through the IAM signBlob API
        instead, which needs the service account's own name and token passed
        in. Without that this raised every time and silently returned None,
        and every caller quietly fell back to the streaming endpoint. That
        endpoint needs an Authorization header, which an image loader and a
        media player do not send, so the elder saw no photo and heard no voice
        with nothing anywhere reporting a failure.
        """
        blob = self.bucket.blob(object_name)
        expiration = timedelta(minutes=minutes)

        try:
            return blob.generate_signed_url(
                version="v4", expiration=expiration, method="GET"
            )
        except Exception as exc:
            logger.info("Direct signing unavailable (%s); trying IAM", exc)

        try:
            credentials, _ = google.auth.default()
            credentials.refresh(GoogleAuthRequest())

            return blob.generate_signed_url(
                version="v4",
                expiration=expiration,
                method="GET",
                service_account_email=credentials.service_account_email,
                access_token=credentials.token,
            )
        except Exception as exc:
            # Loudly. A silent None here costs the elder the photo and the
            # voice, which is most of what the reminder is.
            logger.warning("Could not sign %s: %s", object_name, exc)
            return None


@lru_cache
def get_storage_service() -> StorageService:
    return StorageService()
