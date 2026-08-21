"""Putting an elder's phone on the right person's reminders.

A device signs in as the elder it serves, which needs a Firebase custom token
— several hundred characters of JWT. That token used to BE the pairing code,
shown to the caregiver in a text box to get onto the phone somehow. It cannot
be read down a telephone and it cannot be typed by the person it is for, which
is exactly how a family sets a phone up.

So the token moves behind a short code, in the same shape as the invite that
adds a second caregiver: PAQYA-DDW4N, said out loud, typed once.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import (
    current_caregiver_id,
    mint_elder_pairing_token,
    require_elder_access,
)
from app.api import deps
from app.api.codes import hash_code, new_code
from app.api.schemas import RedeemPairingCodeRequest

router = APIRouter(prefix="/api", tags=["pairing"])

# Long enough to survive "I'll do it tomorrow". The custom token behind it
# lasts an hour, but it is only minted once the code is redeemed, so the phone
# always gets a fresh one.
CODE_LIFETIME = timedelta(hours=72)


@router.post("/elders/{elder_id}/pairing-code", status_code=201)
def create_pairing_code(
    elder_id: str,
    caregiver_id: str = Depends(current_caregiver_id),
):
    """Mints the code a caregiver reads out to put a phone on this elder."""
    firestore = deps.firestore_service()
    elder = require_elder_access(elder_id, caregiver_id, firestore)

    code = new_code()
    expires_at = datetime.now(timezone.utc) + CODE_LIFETIME

    firestore.create_pairing_code(
        code_hash=hash_code(code),
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


@router.post("/pairing/redeem")
def redeem_pairing_code(request: RedeemPairingCodeRequest):
    """Swaps a spoken code for the credential the device signs in with.

    Deliberately unauthenticated: the whole point is that the elder has no
    account and never will. That makes the code itself the credential, so it
    gets the same handling as a caregiver invite — single use, short-lived,
    stored only as a hash, and one identical refusal for a wrong code, a spent
    one and an expired one, so the endpoint cannot be used to test guesses.

    The elder's name comes back with the token so the phone can show who it
    just became. Someone mistyping their way onto the wrong person's
    reminders should see it immediately, not at the next dose.
    """
    firestore = deps.firestore_service()

    refusal = HTTPException(
        status_code=404,
        detail="That code is not valid any more. Ask for a new one.",
    )

    claimed = firestore.claim_pairing_code(hash_code(request.code))
    if not claimed:
        raise refusal

    elder = firestore.get_elder(claimed["elder_id"])
    if not elder:
        raise refusal

    return {
        "elder_id": elder["id"],
        "elder_name": elder["name"],
        "custom_token": mint_elder_pairing_token(elder["id"]),
    }
