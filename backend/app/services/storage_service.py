from datetime import timedelta
from functools import lru_cache

from google.cloud import storage

from app.config import get_settings

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

        Requires a service account with a private key. On user credentials
        (local ADC) signing is unavailable, and callers fall back to the
        streaming media endpoint.
        """
        try:
            return self.bucket.blob(object_name).generate_signed_url(
                version="v4",
                expiration=timedelta(minutes=minutes),
                method="GET",
            )
        except Exception:
            return None


@lru_cache
def get_storage_service() -> StorageService:
    return StorageService()
