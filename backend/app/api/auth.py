import logging

from fastapi import Depends, Header, HTTPException, status

from app.config import get_settings
from app.services.firestore_service import FirestoreService

logger = logging.getLogger(__name__)

try:
    import firebase_admin
    from firebase_admin import auth as firebase_auth

    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    FIREBASE_AVAILABLE = True
except Exception as exc:
    logger.warning("Firebase Auth unavailable: %s", exc)
    FIREBASE_AVAILABLE = False


def current_caregiver_id(
    authorization: str | None = Header(default=None),
    x_caregiver_id: str | None = Header(default=None),
) -> str:
    """Identifies the caller.

    With AUTH_ENABLED the caller must present a Firebase ID token. Without it
    the API accepts an X-Caregiver-Id header so the stack can be run locally
    and demoed without a Firebase web project.
    """
    settings = get_settings()

    if not settings.auth_enabled:
        return x_caregiver_id or settings.dev_caregiver_id

    if not FIREBASE_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is enabled but Firebase is not configured",
        )

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    try:
        claims = firebase_auth.verify_id_token(authorization.split(" ", 1)[1])
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    return claims["uid"]


def require_elder_access(
    elder_id: str,
    caregiver_id: str,
    firestore: FirestoreService,
) -> dict:
    """Client-supplied elder ids are never trusted on their own."""
    elder = firestore.get_elder(elder_id)

    if not elder:
        raise HTTPException(status_code=404, detail="Elder not found")

    if caregiver_id not in (elder.get("caregiver_ids") or []):
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this elder",
        )

    return elder


def require_worker_token(x_worker_token: str | None = Header(default=None)) -> None:
    """Guards the endpoint Cloud Scheduler calls."""
    settings = get_settings()

    if x_worker_token != settings.worker_token:
        raise HTTPException(status_code=403, detail="Invalid worker token")


CaregiverId = Depends(current_caregiver_id)
WorkerAuth = Depends(require_worker_token)


def current_elder_id(
    authorization: str | None = Header(default=None),
    x_elder_id: str | None = Header(default=None),
) -> str:
    """Identifies an elder device.

    Devices are paired by the caregiver, who mints a Firebase custom token for
    the elder; the device exchanges it for an ID token carrying an elder_id
    claim. Without AUTH_ENABLED the X-Elder-Id header stands in for that.
    """
    settings = get_settings()

    if not settings.auth_enabled:
        if not x_elder_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing X-Elder-Id header",
            )
        return x_elder_id

    if not FIREBASE_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is enabled but Firebase is not configured",
        )

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    try:
        claims = firebase_auth.verify_id_token(authorization.split(" ", 1)[1])
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    elder_id = claims.get("elder_id")
    if not elder_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This token is not paired to an elder",
        )

    return elder_id


def mint_elder_pairing_token(elder_id: str) -> str:
    if not FIREBASE_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase is not configured, so devices cannot be paired",
        )

    return firebase_auth.create_custom_token(
        f"elder:{elder_id}",
        {"elder_id": elder_id},
    ).decode()
