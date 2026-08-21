"""Putting a phone on the right person's reminders, with a code you can say.

The pairing credential is a Firebase custom token — hundreds of characters of
JWT. It cannot be read down a telephone to the person it is for, which is the
only way a family ever sets one of these up. A short code stands in front of
it, and because that code reaches a family member's medication record it is
treated as a credential in its own right.
"""

import pytest

from app.api import auth as auth_module


@pytest.fixture
def firebase(monkeypatch):
    """Custom tokens without a Firebase project."""
    monkeypatch.setattr(auth_module, "FIREBASE_AVAILABLE", True)
    monkeypatch.setattr(
        auth_module,
        "firebase_auth",
        type(
            "Stub",
            (),
            {
                "create_custom_token": staticmethod(
                    lambda uid, claims: f"token-for-{uid}".encode()
                )
            },
        ),
    )


@pytest.fixture
def family(firestore_service):
    """One caregiver looking after two people, the way a family actually is."""
    firestore_service.upsert_caregiver("caregiver_1")

    return {
        "amma": firestore_service.create_elder(name="Amma", caregiver_id="caregiver_1"),
        "nanna": firestore_service.create_elder(
            name="Nanna", caregiver_id="caregiver_1"
        ),
    }


def _mint(client, elder_id, caregiver_id="caregiver_1"):
    response = client.post(
        f"/api/elders/{elder_id}/pairing-code",
        headers={"X-Caregiver-Id": caregiver_id},
    )
    assert response.status_code == 201
    return response.json()


# ---------------- the code a person can actually read out ----------------


def test_the_code_is_short_enough_to_say(client, family):
    code = _mint(client, family["amma"])["code"]

    assert len(code) == 11
    assert code[5] == "-"


def test_the_code_avoids_characters_that_sound_alike(client, family):
    """0/O and 1/I are the ones that get misheard on a phone call."""
    code = _mint(client, family["amma"])["code"]

    assert not set(code) & set("0O1I")


def test_the_caregiver_is_told_who_the_code_is_for(client, family):
    """Two codes on screen at once is exactly when a caregiver mixes them up."""
    assert _mint(client, family["amma"])["elder_name"] == "Amma"
    assert _mint(client, family["nanna"])["elder_name"] == "Nanna"


# ---------------- redeeming it ----------------


def test_redeeming_returns_the_credential_and_the_name(client, firebase, family):
    code = _mint(client, family["amma"])["code"]

    body = client.post("/api/pairing/redeem", json={"code": code}).json()

    assert body["elder_id"] == family["amma"]
    assert body["elder_name"] == "Amma"
    assert body["custom_token"] == f"token-for-elder:{family['amma']}"


def test_redeeming_needs_no_account(client, firebase, family):
    """The elder has no sign-in and never will — that is the whole point."""
    code = _mint(client, family["amma"])["code"]

    response = client.post("/api/pairing/redeem", json={"code": code})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "mangle",
    [
        pytest.param(str.lower, id="typed in lower case"),
        pytest.param(lambda c: c.replace("-", ""), id="dash left out"),
        pytest.param(lambda c: c.replace("-", " "), id="space instead of a dash"),
        pytest.param(lambda c: f"  {c} ", id="pasted with spaces round it"),
    ],
)
def test_however_they_type_it_is_fine(client, firebase, family, mangle):
    """She did not see it written down. She heard it."""
    code = _mint(client, family["amma"])["code"]

    response = client.post("/api/pairing/redeem", json={"code": mangle(code)})

    assert response.status_code == 200
    assert response.json()["elder_name"] == "Amma"


def test_the_phone_lands_on_the_right_person(client, firebase, family):
    nanna_code = _mint(client, family["nanna"])["code"]

    body = client.post("/api/pairing/redeem", json={"code": nanna_code}).json()

    assert body["elder_name"] == "Nanna"
    assert body["elder_id"] == family["nanna"]


# ---------------- it is a credential, so it behaves like one ----------------


def test_a_code_works_once(client, firebase, family):
    code = _mint(client, family["amma"])["code"]

    assert client.post("/api/pairing/redeem", json={"code": code}).status_code == 200
    assert client.post("/api/pairing/redeem", json={"code": code}).status_code == 404


def test_an_expired_code_is_refused(client, firebase, firestore_service, family):
    from datetime import datetime, timedelta, timezone

    from app.api.codes import hash_code

    code = _mint(client, family["amma"])["code"]
    firestore_service.create_pairing_code(
        code_hash=hash_code(code),
        elder_id=family["amma"],
        created_by="caregiver_1",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    assert client.post("/api/pairing/redeem", json={"code": code}).status_code == 404


def test_wrong_spent_and_expired_are_indistinguishable(
    client, firebase, firestore_service, family
):
    """Otherwise the endpoint becomes a way to test guesses."""
    from datetime import datetime, timedelta, timezone

    from app.api.codes import hash_code

    spent = _mint(client, family["amma"])["code"]
    client.post("/api/pairing/redeem", json={"code": spent})

    expired = _mint(client, family["amma"])["code"]
    firestore_service.create_pairing_code(
        code_hash=hash_code(expired),
        elder_id=family["amma"],
        created_by="caregiver_1",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    replies = {
        client.post("/api/pairing/redeem", json={"code": code}).json()["detail"]
        for code in ("ZZZZZ-ZZZZZ", spent, expired)
    }

    assert len(replies) == 1


def test_the_code_is_never_stored(client, db, family):
    """A leaked database must not hand over working codes."""
    code = _mint(client, family["amma"])["code"]

    stored = str(db.raw("elder_pairing_codes"))

    assert code not in stored
    assert code.replace("-", "") not in stored


def test_only_this_elder_s_care_team_can_mint_one(client, family):
    response = client.post(
        f"/api/elders/{family['amma']}/pairing-code",
        headers={"X-Caregiver-Id": "not-on-this-care-team"},
    )

    assert response.status_code == 403


def test_two_phones_racing_the_same_code_do_not_both_pair(
    client, firebase, db, firestore_service, family
):
    """Check-then-write would let both through."""
    from app.api.codes import hash_code

    code = _mint(client, family["amma"])["code"]
    code_hash = hash_code(code)

    first = firestore_service.claim_pairing_code(code_hash)
    second = firestore_service.claim_pairing_code(code_hash)

    assert first is not None
    assert second is None
