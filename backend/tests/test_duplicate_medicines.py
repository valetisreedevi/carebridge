"""Guarding against a second medicine with the same name.

Five identical "Eye Drops" rows is not clutter. To the person taking them it
reads as five separate medicines, which is a prompt to take five doses.
"""

CAREGIVER = {"X-Caregiver-Id": "caregiver_1"}


def _elder(client) -> str:
    return client.post(
        "/api/elders", json={"name": "Nanna"}, headers=CAREGIVER
    ).json()["id"]


def _add(client, elder_id: str, name: str = "Eye Drops", time: str = "06:52", **extra):
    return client.post(
        "/api/medications",
        json={
            "elder_id": elder_id,
            "name": name,
            "dose": "1 drop",
            "food_instruction": "AFTER_FOOD",
            "schedule_times": [time],
            **extra,
        },
        headers=CAREGIVER,
    )


def test_a_second_medicine_with_the_same_name_is_refused(client):
    elder_id = _elder(client)
    assert _add(client, elder_id).status_code == 201

    clash = _add(client, elder_id, time="07:14")

    assert clash.status_code == 409
    assert "already has Eye Drops at 06:52" in clash.json()["detail"]["message"]


def test_the_refusal_carries_what_is_needed_to_fix_it(client):
    """The caregiver almost always meant another time on the same medicine."""
    elder_id = _elder(client)
    first = _add(client, elder_id).json()

    detail = _add(client, elder_id, time="07:14").json()["detail"]

    assert detail["existing_id"] == first["id"]
    assert detail["existing_times"] == ["06:52"]


def test_the_name_check_ignores_case_and_spacing(client):
    elder_id = _elder(client)
    _add(client, elder_id)

    assert _add(client, elder_id, name="  eye drops  ").status_code == 409


def test_a_caregiver_who_means_it_can_still_add_one(client):
    elder_id = _elder(client)
    _add(client, elder_id)

    deliberate = _add(client, elder_id, time="07:14", allow_duplicate=True)

    assert deliberate.status_code == 201


def test_another_elder_may_take_the_same_medicine(client):
    """A couple on one care team will often be on the same tablet."""
    nanna = _elder(client)
    amma = client.post(
        "/api/elders", json={"name": "Amma"}, headers=CAREGIVER
    ).json()["id"]

    _add(client, nanna)

    assert _add(client, amma).status_code == 201


def test_a_removed_medicine_does_not_block_re_adding_it(client):
    elder_id = _elder(client)
    first = _add(client, elder_id).json()

    client.delete(f"/api/medications/{first['id']}", headers=CAREGIVER)

    assert _add(client, elder_id).status_code == 201


def test_adding_a_time_to_the_existing_medicine_is_the_intended_fix(client):
    elder_id = _elder(client)
    first = _add(client, elder_id).json()

    updated = client.put(
        f"/api/medications/{first['id']}",
        json={"schedule_times": ["06:52", "07:14"]},
        headers=CAREGIVER,
    )

    assert updated.status_code == 200
    assert updated.json()["schedule_times"] == ["06:52", "07:14"]
