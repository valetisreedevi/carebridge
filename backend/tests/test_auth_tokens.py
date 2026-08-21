"""Who a verified Firebase token is allowed to be."""

import pytest
from fastapi import HTTPException

from app.api import auth as auth_module
from app.config.settings import Settings


@pytest.fixture
def signed_in(monkeypatch):
    """Auth turned on, with a stand-in for Firebase's token verification."""
    claims: dict = {}

    def _settings(**overrides):
        # A real worker token, because auth_enabled refuses to start with the
        # published placeholder. These tests are about who a token is, not
        # about deployment configuration.
        return Settings(
            auth_enabled=True, worker_token="test-worker-token", **overrides
        )

    monkeypatch.setattr(auth_module, "FIREBASE_AVAILABLE", True)
    monkeypatch.setattr(
        auth_module,
        "firebase_auth",
        type("Stub", (), {"verify_id_token": staticmethod(lambda _: claims)}),
    )

    def configure(token_claims: dict, **settings_overrides):
        claims.clear()
        claims.update(token_claims)
        monkeypatch.setattr(
            auth_module, "get_settings", lambda: _settings(**settings_overrides)
        )

    return configure


def test_a_caregiver_token_identifies_the_caregiver(signed_in):
    signed_in({"uid": "caregiver_1", "email_verified": True})

    assert auth_module.current_caregiver_id(authorization="Bearer x") == "caregiver_1"


def test_an_elder_device_token_is_not_a_caregiver(signed_in):
    """A paired phone could otherwise create elders and act as a person."""
    signed_in({"uid": "elder:abc", "elder_id": "abc"})

    with pytest.raises(HTTPException) as raised:
        auth_module.current_caregiver_id(authorization="Bearer x")

    assert raised.value.status_code == 403


def test_an_unverified_email_is_turned_away_when_verification_is_required(signed_in):
    signed_in({"uid": "caregiver_1", "email_verified": False}, require_verified_email=True)

    with pytest.raises(HTTPException) as raised:
        auth_module.current_caregiver_id(authorization="Bearer x")

    assert raised.value.status_code == 403


def test_an_unverified_email_is_fine_when_verification_is_off(signed_in):
    signed_in({"uid": "caregiver_1", "email_verified": False})

    assert auth_module.current_caregiver_id(authorization="Bearer x") == "caregiver_1"


def test_an_elder_token_identifies_the_elder(signed_in):
    signed_in({"uid": "elder:abc", "elder_id": "abc"})

    assert auth_module.current_elder_id(authorization="Bearer x") == "abc"


def test_a_caregiver_token_cannot_act_as_an_elder_device(signed_in):
    signed_in({"uid": "caregiver_1", "email_verified": True})

    with pytest.raises(HTTPException) as raised:
        auth_module.current_elder_id(authorization="Bearer x")

    assert raised.value.status_code == 403
