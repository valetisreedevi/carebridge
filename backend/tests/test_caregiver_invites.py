"""Sharing an elder between family members.

Care is shared between siblings and between a spouse and a child. Until this
existed, one person was the single point of failure for every escalation.
"""

CAREGIVER = {"X-Caregiver-Id": "caregiver_1"}
SIBLING = {"X-Caregiver-Id": "caregiver_2"}
STRANGER = {"X-Caregiver-Id": "caregiver_3"}


def _elder(client) -> str:
    return client.post(
        "/api/elders", json={"name": "Amma"}, headers=CAREGIVER
    ).json()["id"]


def _invite(client, elder_id: str) -> str:
    response = client.post(f"/api/elders/{elder_id}/invites", headers=CAREGIVER)
    assert response.status_code == 201
    return response.json()["code"]


def test_a_sibling_can_join_with_an_invite(client):
    elder_id = _elder(client)
    code = _invite(client, elder_id)

    accepted = client.post(
        "/api/invites/accept", json={"code": code}, headers=SIBLING
    )
    assert accepted.status_code == 200

    # The proof is access, not the response body.
    assert client.get(
        f"/api/elders/{elder_id}/today", headers=SIBLING
    ).status_code == 200


def test_the_code_survives_being_read_aloud(client):
    """Family members forward these by phone; case and dashes should not matter."""
    elder_id = _elder(client)
    code = _invite(client, elder_id)

    mangled = code.lower().replace("-", " ")
    assert client.post(
        "/api/invites/accept", json={"code": mangled}, headers=SIBLING
    ).status_code == 200


def test_an_invite_works_only_once(client):
    elder_id = _elder(client)
    code = _invite(client, elder_id)

    client.post("/api/invites/accept", json={"code": code}, headers=SIBLING)
    second = client.post(
        "/api/invites/accept", json={"code": code}, headers=STRANGER
    )

    assert second.status_code == 404
    assert client.get(
        f"/api/elders/{elder_id}/today", headers=STRANGER
    ).status_code == 403


def test_an_expired_invite_is_refused(client, db):
    from datetime import datetime, timedelta, timezone

    elder_id = _elder(client)
    code = _invite(client, elder_id)

    for snapshot in db.collection("caregiver_invites").stream():
        db.collection("caregiver_invites").document(snapshot.id).update({
            "expires_at": datetime.now(timezone.utc) - timedelta(minutes=1)
        })

    assert client.post(
        "/api/invites/accept", json={"code": code}, headers=SIBLING
    ).status_code == 404


def test_a_made_up_code_is_refused_the_same_way(client):
    """A wrong code and a used one must be indistinguishable."""
    response = client.post(
        "/api/invites/accept", json={"code": "AAAAA-BBBBB"}, headers=SIBLING
    )

    assert response.status_code == 404
    assert "not valid any more" in response.json()["detail"]


def test_only_someone_on_the_care_team_can_invite(client):
    elder_id = _elder(client)

    assert client.post(
        f"/api/elders/{elder_id}/invites", headers=STRANGER
    ).status_code == 403


def test_the_care_team_lists_everyone_on_it(client):
    elder_id = _elder(client)
    code = _invite(client, elder_id)
    client.post("/api/invites/accept", json={"code": code}, headers=SIBLING)

    team = client.get(f"/api/elders/{elder_id}/caregivers", headers=CAREGIVER).json()

    assert [person["caregiver_id"] for person in team] == [
        "caregiver_1",
        "caregiver_2",
    ]
    assert [person["is_you"] for person in team] == [True, False]


def test_someone_can_be_removed_from_the_care_team(client):
    elder_id = _elder(client)
    code = _invite(client, elder_id)
    client.post("/api/invites/accept", json={"code": code}, headers=SIBLING)

    removed = client.delete(
        f"/api/elders/{elder_id}/caregivers/caregiver_2", headers=CAREGIVER
    )

    assert removed.status_code == 204
    assert client.get(
        f"/api/elders/{elder_id}/today", headers=SIBLING
    ).status_code == 403


def test_the_last_caregiver_cannot_be_removed(client):
    """An elder with nobody watching still takes reminders nobody hears about."""
    elder_id = _elder(client)

    response = client.delete(
        f"/api/elders/{elder_id}/caregivers/caregiver_1", headers=CAREGIVER
    )

    assert response.status_code == 409
    assert "nobody watching" in response.json()["detail"]
