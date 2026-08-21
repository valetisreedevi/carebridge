"""Sharing one elder between several family members.

Care is shared — between siblings, between a spouse and an adult child. Until
now the data model allowed it and nothing exposed it, so a single person was
the only one who could ever be told about a missed dose.

The invite is a short code the first caregiver reads out or forwards, in the
same shape as the elder pairing code the family already understands.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import CAREGIVER_EMAILS, current_caregiver_id, require_elder_access
from app.api import deps
from app.api.schemas import AcceptInviteRequest

router = APIRouter(prefix="/api", tags=["caregivers"])

# No 0/O/1/I: this gets read aloud over a phone call between family members.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 10
INVITE_LIFETIME = timedelta(hours=72)


def _new_code() -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    return f"{raw[:5]}-{raw[5:]}"


def _hash(code: str) -> str:
    """Invites are stored under this, never as the code itself.

    Anyone holding the code can read a family member's medication record, so a
    leaked database should not hand over working invites.
    """
    normalised = code.strip().upper().replace("-", "").replace(" ", "")
    return hashlib.sha256(normalised.encode()).hexdigest()


@router.post("/elders/{elder_id}/invites", status_code=201)
def create_invite(
    elder_id: str,
    caregiver_id: str = Depends(current_caregiver_id),
):
    """Mints a code that adds whoever redeems it as a second caregiver."""
    firestore = deps.firestore_service()
    elder = require_elder_access(elder_id, caregiver_id, firestore)

    code = _new_code()
    expires_at = datetime.now(timezone.utc) + INVITE_LIFETIME

    firestore.create_invite(
        code_hash=_hash(code),
        elder_id=elder_id,
        created_by=caregiver_id,
        expires_at=expires_at,
    )

    # The only time the code exists outside the caregiver's screen.
    return {
        "code": code,
        "elder_id": elder_id,
        "elder_name": elder["name"],
        "expires_at": expires_at,
    }


@router.post("/invites/accept")
def accept_invite(
    request: AcceptInviteRequest,
    caregiver_id: str = Depends(current_caregiver_id),
):
    """Joins the caller to an elder's care team."""
    firestore = deps.firestore_service()
    invite = firestore.get_invite(_hash(request.code))

    # One message for every failure: a wrong code and an expired one must not
    # be distinguishable, or the endpoint becomes a way to test guesses.
    refusal = HTTPException(
        status_code=404,
        detail="That invite code is not valid any more. Ask for a new one.",
    )

    if not invite or invite.get("accepted_at"):
        raise refusal

    expires_at = invite["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise refusal

    firestore.upsert_caregiver(
        caregiver_id, email=CAREGIVER_EMAILS.get(caregiver_id)
    )
    elder = firestore.add_caregiver_to_elder(invite["elder_id"], caregiver_id)
    if not elder:
        raise refusal

    firestore.accept_invite(_hash(request.code), caregiver_id)

    return {"elder_id": elder["id"], "elder_name": elder["name"]}


@router.get("/elders/{elder_id}/caregivers")
def list_caregivers(
    elder_id: str,
    caregiver_id: str = Depends(current_caregiver_id),
):
    firestore = deps.firestore_service()
    elder = require_elder_access(elder_id, caregiver_id, firestore)

    people = []
    for member_id in elder.get("caregiver_ids") or []:
        caregiver = firestore.get_caregiver(member_id) or {}
        people.append({
            "caregiver_id": member_id,
            "email": caregiver.get("email"),
            "name": caregiver.get("name"),
            "is_you": member_id == caregiver_id,
        })

    return people


@router.delete("/elders/{elder_id}/caregivers/{member_id}", status_code=204)
def remove_caregiver(
    elder_id: str,
    member_id: str,
    caregiver_id: str = Depends(current_caregiver_id),
):
    """Removes someone from an elder's care team."""
    firestore = deps.firestore_service()
    elder = require_elder_access(elder_id, caregiver_id, firestore)

    caregivers = elder.get("caregiver_ids") or []
    if member_id not in caregivers:
        raise HTTPException(status_code=404, detail="They are not on this care team")

    # An elder with nobody watching would keep taking reminders while every
    # escalation went nowhere, which is worse than having no CareBridge at all.
    if len(caregivers) == 1:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{elder['name']} would have nobody watching. "
                "Add someone else first."
            ),
        )

    firestore.remove_caregiver_from_elder(elder_id, member_id)
