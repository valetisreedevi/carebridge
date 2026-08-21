from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile

from app.api.auth import current_caregiver_id, require_elder_access
from app.api import deps
from app.api.schemas import (
    CreateMedicationRequest,
    MarkTakenRequest,
    UpdateMedicationRequest,
)
from app.services.storage_service import AUDIO_TYPES, IMAGE_TYPES

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_AUDIO_BYTES = 5 * 1024 * 1024

router = APIRouter(prefix="/api", tags=["medications"])


def _authorized_medication(medication_id: str, caregiver_id: str) -> dict:
    firestore = deps.firestore_service()
    medication = firestore.get_medication(medication_id)

    if not medication:
        raise HTTPException(status_code=404, detail="Medication not found")

    require_elder_access(medication["elder_id"], caregiver_id, firestore)
    return medication


def _same_medicine(firestore, elder_id: str, name: str) -> dict | None:
    """An active medicine for this elder already going by this name."""
    wanted = name.strip().casefold()

    for medication in firestore.list_medications_for_elder(elder_id):
        if (medication.get("name") or "").strip().casefold() == wanted:
            return medication

    return None


@router.post("/medications", status_code=201)
def create_medication(
    request: CreateMedicationRequest,
    caregiver_id: str = Depends(current_caregiver_id),
):
    """Adds a medicine, refusing a second one by the same name by default.

    Five identically named entries is not clutter — to the person taking them
    it reads as five separate medicines and invites a double dose. Almost
    always the caregiver meant another time on the medicine they already have,
    which is why the refusal carries what they would need to do that instead.
    """
    firestore = deps.firestore_service()
    elder = require_elder_access(request.elder_id, caregiver_id, firestore)

    if not request.allow_duplicate:
        existing = _same_medicine(firestore, request.elder_id, request.name)
        if existing:
            times = existing.get("schedule_times") or []
            raise HTTPException(
                status_code=409,
                detail={
                    "message": (
                        f"{elder['name']} already has {existing['name']} at "
                        f"{', '.join(times) or 'no set time'}."
                    ),
                    "existing_id": existing["id"],
                    "existing_name": existing["name"],
                    "existing_times": times,
                },
            )

    data = request.model_dump(mode="json", exclude={"allow_duplicate"})
    # The first scheduled time is the one shown in single-time UIs.
    data["schedule_time"] = data["schedule_times"][0]

    medication_id = firestore.create_medication(data)
    return {"id": medication_id, **data}


@router.get("/elders/{elder_id}/medications")
def list_medications(
    elder_id: str,
    caregiver_id: str = Depends(current_caregiver_id),
):
    firestore = deps.firestore_service()
    require_elder_access(elder_id, caregiver_id, firestore)
    return firestore.list_medications_for_elder(elder_id, active_only=False)


@router.get("/medications/{medication_id}")
def get_medication(
    medication_id: str,
    caregiver_id: str = Depends(current_caregiver_id),
):
    return _authorized_medication(medication_id, caregiver_id)


@router.put("/medications/{medication_id}")
def update_medication(
    medication_id: str,
    request: UpdateMedicationRequest,
    caregiver_id: str = Depends(current_caregiver_id),
):
    _authorized_medication(medication_id, caregiver_id)

    updates = request.model_dump(mode="json", exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    if "schedule_times" in updates:
        updates["schedule_time"] = updates["schedule_times"][0]

    firestore = deps.firestore_service()
    firestore.update_medication(medication_id, updates)
    return firestore.get_medication(medication_id)


@router.delete("/medications/{medication_id}", status_code=204)
def delete_medication(
    medication_id: str,
    caregiver_id: str = Depends(current_caregiver_id),
):
    """Stops a medication, including any reminder already waiting on an answer.

    Deactivating the schedule alone leaves today's events live: they keep
    reminding, and escalate, a medicine the caregiver just removed.
    """
    _authorized_medication(medication_id, caregiver_id)
    deps.firestore_service().delete_medication(medication_id)
    deps.event_service().cancel_outstanding_for_medication(medication_id)


@router.post("/medications/{medication_id}/remind-now")
def remind_now(
    medication_id: str,
    caregiver_id: str = Depends(current_caregiver_id),
):
    """Sends a medication's reminder immediately instead of waiting for it.

    This used to live at /api/demo/trigger-reminder. It is a real feature the
    dashboard offers, and a door marked "demo" has no business standing open in
    front of medical data.
    """
    medication = _authorized_medication(medication_id, caregiver_id)
    return deps.reminder_service().remind_immediately(medication)


@router.post("/medications/{medication_id}/mark-taken")
def mark_taken_by_caregiver(
    medication_id: str,
    request: MarkTakenRequest,
    caregiver_id: str = Depends(current_caregiver_id),
):
    """Records a dose the caregiver knows was taken.

    Covers the ordinary case of phoning and hearing "yes, I took it". Works
    whether or not a reminder ever went out: a dose that was missed entirely
    has no event yet, so one is created and closed in the same breath.
    """
    medication = _authorized_medication(medication_id, caregiver_id)

    return deps.reminder_service().confirm_on_behalf(
        medication=medication,
        local_time=request.local_time,
        caregiver_id=caregiver_id,
    )


async def _read_upload(
    file: UploadFile,
    allowed: set[str],
    max_bytes: int,
) -> bytes:
    if file.content_type not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported content type. Allowed: {', '.join(sorted(allowed))}",
        )

    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds {max_bytes // (1024 * 1024)} MB",
        )
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    return content


@router.post("/medications/{medication_id}/image-upload")
async def upload_image(
    medication_id: str,
    file: UploadFile = File(...),
    caregiver_id: str = Depends(current_caregiver_id),
):
    medication = _authorized_medication(medication_id, caregiver_id)
    content = await _read_upload(file, IMAGE_TYPES, MAX_IMAGE_BYTES)

    object_name = deps.storage_service().upload_medicine_photo(
        content=content,
        content_type=file.content_type,
        elder_id=medication["elder_id"],
        medication_id=medication_id,
    )
    deps.firestore_service().update_medication(
        medication_id, {"photo_object_name": object_name}
    )

    return {"medication_id": medication_id, "photo_object_name": object_name}


@router.post("/medications/{medication_id}/audio-upload")
async def upload_audio(
    medication_id: str,
    file: UploadFile = File(...),
    caregiver_id: str = Depends(current_caregiver_id),
):
    """The caregiver's own voice, played to the elder at reminder time."""
    medication = _authorized_medication(medication_id, caregiver_id)
    content = await _read_upload(file, AUDIO_TYPES, MAX_AUDIO_BYTES)

    object_name = deps.storage_service().upload_caregiver_audio(
        content=content,
        content_type=file.content_type,
        elder_id=medication["elder_id"],
        medication_id=medication_id,
    )
    deps.firestore_service().update_medication(
        medication_id, {"caregiver_audio_object_name": object_name}
    )

    return {"medication_id": medication_id, "caregiver_audio_object_name": object_name}


@router.get("/medications/{medication_id}/image")
def get_image(
    medication_id: str,
    caregiver_id: str = Depends(current_caregiver_id),
):
    medication = _authorized_medication(medication_id, caregiver_id)
    return _stream(medication.get("photo_object_name"), "No photo uploaded")


@router.get("/medications/{medication_id}/audio")
def get_audio(
    medication_id: str,
    caregiver_id: str = Depends(current_caregiver_id),
):
    medication = _authorized_medication(medication_id, caregiver_id)
    return _stream(
        medication.get("caregiver_audio_object_name"), "No voice recording uploaded"
    )


def _stream(object_name: str | None, missing_detail: str) -> Response:
    if not object_name:
        raise HTTPException(status_code=404, detail=missing_detail)

    content, content_type = deps.storage_service().read(object_name)
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=300"},
    )
