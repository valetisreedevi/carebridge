"""A phone signing itself up, and a family being able to see that it did.

POST /devices needs caregiver credentials, which an elder's phone does not
have. So a paired device could not put its own notification address on file,
nothing was ever written to the devices collection, and the dashboard had no
way to tell a phone that was set up from one that was never opened.
"""

import pytest


@pytest.fixture
def paired(firestore_service):
    firestore_service.upsert_caregiver("caregiver_1")
    return firestore_service.create_elder(name="Amma", caregiver_id="caregiver_1")


def _register(client, elder_id, token, platform="WEB", label=None):
    body = {"fcm_token": token, "platform": platform}
    if label:
        body["label"] = label
    return client.post(
        "/api/devices/mine", json=body, headers={"X-Elder-Id": elder_id}
    )


# ---------------- a device registering itself ----------------


def test_a_phone_can_register_itself(client, paired):
    response = _register(client, paired, "fcm-token-from-the-phone")

    assert response.status_code == 201
    assert response.json()["elder_id"] == paired


def test_registering_makes_the_phone_reachable(client, firestore_service, paired):
    _register(client, paired, "fcm-token-from-the-phone")

    assert firestore_service.get_device_tokens(paired) == ["fcm-token-from-the-phone"]


def test_a_phone_cannot_sign_itself_up_for_someone_else(
    client, firestore_service, paired
):
    """The elder id comes from the credentials, so the body cannot name one."""
    other = firestore_service.create_elder(name="Nanna", caregiver_id="caregiver_1")

    client.post(
        "/api/devices/mine",
        json={"fcm_token": "sneaky-token", "elder_id": other},
        headers={"X-Elder-Id": paired},
    )

    assert firestore_service.get_device_tokens(other) == []
    assert firestore_service.get_device_tokens(paired) == ["sneaky-token"]


def test_registering_twice_is_one_phone(client, firestore_service, paired):
    _register(client, paired, "same-token")
    _register(client, paired, "same-token")

    assert len(firestore_service.list_devices_for_elder(paired)) == 1


# ---------------- what the caregiver can see ----------------


def test_the_caregiver_sees_the_phone(client, paired):
    _register(client, paired, "fcm-token-from-the-phone", platform="WEB")

    devices = client.get(
        f"/api/elders/{paired}/devices", headers={"X-Caregiver-Id": "caregiver_1"}
    ).json()

    assert len(devices) == 1
    assert devices[0]["platform"] == "WEB"
    assert devices[0]["paired_at"] is not None
    assert devices[0]["last_seen_at"] is not None


def test_the_notification_address_is_never_handed_out(client, paired):
    """It is the address of a person's phone; the dashboard has no use for it."""
    _register(client, paired, "fcm-token-from-the-phone")

    response = client.get(
        f"/api/elders/{paired}/devices", headers={"X-Caregiver-Id": "caregiver_1"}
    )

    assert "fcm-token-from-the-phone" not in response.text


def test_no_phones_set_up_reads_as_an_empty_list(client, paired):
    response = client.get(
        f"/api/elders/{paired}/devices", headers={"X-Caregiver-Id": "caregiver_1"}
    )

    assert response.status_code == 200
    assert response.json() == []


def test_a_stranger_cannot_see_the_phones(client, paired):
    _register(client, paired, "fcm-token-from-the-phone")

    response = client.get(
        f"/api/elders/{paired}/devices",
        headers={"X-Caregiver-Id": "not-on-this-care-team"},
    )

    assert response.status_code == 403


def test_a_shared_phone_says_how_many_others_are_on_it(
    client, firestore_service, paired
):
    nanna = firestore_service.create_elder(name="Nanna", caregiver_id="caregiver_1")
    _register(client, paired, "the-side-table-phone")
    _register(client, nanna, "the-side-table-phone")

    devices = client.get(
        f"/api/elders/{paired}/devices", headers={"X-Caregiver-Id": "caregiver_1"}
    ).json()

    assert devices[0]["shared_with"] == 1


def test_an_unpaired_phone_drops_off_the_list(client, firestore_service, paired):
    _register(client, paired, "the-old-phone")
    firestore_service.unregister_device(elder_id=paired, fcm_token="the-old-phone")

    devices = client.get(
        f"/api/elders/{paired}/devices", headers={"X-Caregiver-Id": "caregiver_1"}
    ).json()

    assert devices == []


# ---------------- one document per phone ----------------


def test_two_tokens_sharing_a_long_prefix_stay_separate(firestore_service, paired):
    """The document id was the token truncated to 200 characters, so two of
    these collided into one - and registration writes rather than merges, so a
    phone could be silently reassigned to another household."""
    prefix = "t" * 250
    firestore_service.register_device(paired, prefix + "AAA")
    firestore_service.register_device(paired, prefix + "BBB")

    assert len(firestore_service.list_devices_for_elder(paired)) == 2
    assert set(firestore_service.get_device_tokens(paired)) == {
        prefix + "AAA",
        prefix + "BBB",
    }
