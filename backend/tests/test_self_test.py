"""Proving the chain works before the evening it has to.

Every silent failure this project has actually hit is on this list, and each
one only ever announced itself as "she has not confirmed" — which reads as a
person rather than as plumbing. A family should be able to ask the question
directly, and get an answer that names which link is broken.
"""

CAREGIVER = {"X-Caregiver-Id": "caregiver_1"}


def _named(body, fragment):
    return next(c for c in body["checks"] if fragment in c["check"])


def test_a_household_with_no_phone_is_told_which_link_is_broken(client, seeded, db):
    for device in db.collection("devices").stream():
        db.collection("devices").document(device.id).update({"active": False})

    body = client.post(
        f"/api/elders/{seeded['elder_id']}/self-test", headers=CAREGIVER
    ).json()

    assert body["ok"] is False
    phone = _named(body, "phone is paired")
    assert phone["ok"] is False
    assert "No phone is set up" in phone["detail"]


def test_a_paired_phone_passes_the_first_check(client, seeded):
    body = client.post(
        f"/api/elders/{seeded['elder_id']}/self-test", headers=CAREGIVER
    ).json()

    assert _named(body, "phone is paired")["ok"] is True


def test_it_says_when_there_is_nowhere_to_escalate_to(client, seeded):
    """The blocker that took an evening to find, surfaced in one press.

    A caregiver with no address on file is invisible right up until the first
    escalation, which then has nowhere to go and fails quietly.
    """
    body = client.post(
        f"/api/elders/{seeded['elder_id']}/self-test", headers=CAREGIVER
    ).json()

    assert _named(body, "on file to be told")["ok"] is False


def test_it_creates_no_dose(client, seeded, db):
    """The old demo button invented a tablet every time it was pressed.

    A family checking that the phone works must not be able to add a dose to
    the record by doing so.
    """
    before = len(list(db.collection("medication_events").stream()))

    client.post(f"/api/elders/{seeded['elder_id']}/self-test", headers=CAREGIVER)
    client.post(f"/api/elders/{seeded['elder_id']}/self-test", headers=CAREGIVER)

    assert len(list(db.collection("medication_events").stream())) == before

    day = client.get(
        f"/api/elders/{seeded['elder_id']}/today", headers=CAREGIVER
    ).json()
    assert day["ledger"]["scheduled"] == len(day["items"])


def test_the_test_notification_is_not_a_reminder(client, seeded, db):
    client.post(f"/api/elders/{seeded['elder_id']}/self-test", headers=CAREGIVER)

    sent = [d.to_dict() for d in db.collection("notifications").stream()]
    assert [n["type"] for n in sent] == ["SELF_TEST"]


def test_another_familys_household_is_not_testable(client, seeded):
    response = client.post(
        f"/api/elders/{seeded['elder_id']}/self-test",
        headers={"X-Caregiver-Id": "someone-else"},
    )
    assert response.status_code in (403, 404)
