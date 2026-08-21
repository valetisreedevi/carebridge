"""Signing an elder's devices out, and having that mean something.

A device is paired by exchanging a one-time code for a Firebase session that
refreshes indefinitely. Removing its FCM token stopped the reminders and left
that session reading the medication record, the caregiver's voice recordings
and the medicine photos, and answering doses on the elder's behalf.
"""

import pytest
from fastapi import HTTPException

from app.api import auth as auth_module


class FakeFirebaseAuth:
    """Enough of firebase_admin.auth to test revocation, and no more."""

    class RevokedIdTokenError(Exception):
        pass

    class UserNotFoundError(Exception):
        pass

    def __init__(self):
        self.revoked: list[str] = []
        self.known_users: set[str] = set()

    def revoke_refresh_tokens(self, uid):
        if self.known_users and uid not in self.known_users:
            raise FakeFirebaseAuth.UserNotFoundError(uid)
        self.revoked.append(uid)

    def verify_id_token(self, token, check_revoked=False):
        elder_id = token.removeprefix("elder-token-for-")
        if check_revoked and f"elder:{elder_id}" in self.revoked:
            raise FakeFirebaseAuth.RevokedIdTokenError(token)
        return {"uid": f"elder:{elder_id}", "elder_id": elder_id}


@pytest.fixture
def firebase(monkeypatch):
    stub = FakeFirebaseAuth()
    monkeypatch.setattr(auth_module, "FIREBASE_AVAILABLE", True)
    monkeypatch.setattr(auth_module, "firebase_auth", stub)
    return stub


@pytest.fixture
def paired(firestore_service):
    """An elder on two handsets: their own, and a shared one."""
    firestore_service.upsert_caregiver("caregiver_1")
    elder_id = firestore_service.create_elder(name="Amma", caregiver_id="caregiver_1")

    firestore_service.register_device(elder_id, "token-own-phone")
    firestore_service.register_device(elder_id, "token-shared-phone")

    return elder_id


# ---------------- the session actually stops working ----------------


def test_a_revoked_session_is_turned_away(firebase, monkeypatch):
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: _auth_on()
    )
    firebase.revoke_refresh_tokens("elder:abc")

    with pytest.raises(HTTPException) as raised:
        auth_module.current_elder_id(authorization="Bearer elder-token-for-abc")

    assert raised.value.status_code == 401
    assert "pairing code" in raised.value.detail


def test_a_live_session_still_works(firebase, monkeypatch):
    monkeypatch.setattr(auth_module, "get_settings", lambda: _auth_on())

    assert (
        auth_module.current_elder_id(authorization="Bearer elder-token-for-abc")
        == "abc"
    )


def test_revocation_is_checked_on_every_request(firebase, monkeypatch):
    """Without check_revoked an issued token stays good for up to an hour."""
    monkeypatch.setattr(auth_module, "get_settings", lambda: _auth_on())
    seen = {}

    original = firebase.verify_id_token

    def record(token, check_revoked=False):
        seen["check_revoked"] = check_revoked
        return original(token, check_revoked)

    firebase.verify_id_token = record
    auth_module.current_elder_id(authorization="Bearer elder-token-for-abc")

    assert seen["check_revoked"] is True


def _auth_on():
    from app.config.settings import Settings

    return Settings(auth_enabled=True, worker_token="test-worker-token")


# ---------------- signing out from the dashboard ----------------


def test_signing_out_revokes_the_elder_s_sessions(client, firebase, paired):
    response = client.post(
        f"/api/elders/{paired}/devices/sign-out",
        headers={"X-Caregiver-Id": "caregiver_1"},
    )

    assert response.status_code == 200
    assert firebase.revoked == [f"elder:{paired}"]


def test_signing_out_unpairs_every_handset(client, firebase, firestore_service, paired):
    client.post(
        f"/api/elders/{paired}/devices/sign-out",
        headers={"X-Caregiver-Id": "caregiver_1"},
    )

    assert firestore_service.get_device_tokens(paired) == []


def test_signing_out_reports_how_many_devices_went(client, firebase, paired):
    body = client.post(
        f"/api/elders/{paired}/devices/sign-out",
        headers={"X-Caregiver-Id": "caregiver_1"},
    ).json()

    assert body["devices_signed_out"] == 2
    assert body["elder_name"] == "Amma"


def test_another_elder_on_a_shared_phone_keeps_their_pairing(
    client, firebase, firestore_service, paired
):
    """The handset is shared; the session is not."""
    other_id = firestore_service.create_elder(name="Nanna", caregiver_id="caregiver_1")
    firestore_service.register_device(other_id, "token-shared-phone")

    client.post(
        f"/api/elders/{paired}/devices/sign-out",
        headers={"X-Caregiver-Id": "caregiver_1"},
    )

    assert firestore_service.get_device_tokens(other_id) == ["token-shared-phone"]
    assert f"elder:{other_id}" not in firebase.revoked


def test_a_stranger_cannot_sign_out_someone_else_s_devices(client, firebase, paired):
    response = client.post(
        f"/api/elders/{paired}/devices/sign-out",
        headers={"X-Caregiver-Id": "not-on-this-care-team"},
    )

    assert response.status_code == 403
    assert firebase.revoked == []


def test_signing_out_a_never_paired_elder_is_not_an_error(
    client, firebase, firestore_service
):
    firestore_service.upsert_caregiver("caregiver_1")
    elder_id = firestore_service.create_elder(name="Amma", caregiver_id="caregiver_1")
    firebase.known_users = {"someone-else"}

    response = client.post(
        f"/api/elders/{elder_id}/devices/sign-out",
        headers={"X-Caregiver-Id": "caregiver_1"},
    )

    assert response.status_code == 200
    assert response.json()["devices_signed_out"] == 0


# ---------------- removing one handset ----------------


def test_unregistering_a_device_also_removes_its_access(client, firebase, paired):
    """Removing a phone from the list has to remove what it can read."""
    response = client.delete(
        f"/api/devices/{paired}?fcm_token=token-own-phone",
        headers={"X-Caregiver-Id": "caregiver_1"},
    )

    assert response.status_code == 204
    assert firebase.revoked == [f"elder:{paired}"]
