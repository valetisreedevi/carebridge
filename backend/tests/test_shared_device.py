"""One phone, several people.

A phone on a shared side table belongs to a household. Registering a second
person used to overwrite the first, who then stopped receiving reminders with
no warning anywhere — the failure a family would only notice by missing doses.
"""

TOKEN = "fcm-token-on-the-shared-side-table"


def test_a_second_person_does_not_displace_the_first(firestore_service):
    amma = firestore_service.create_elder(name="Amma", caregiver_id="c1")
    nanna = firestore_service.create_elder(name="Nanna", caregiver_id="c1")

    firestore_service.register_device(elder_id=amma, fcm_token=TOKEN)
    firestore_service.register_device(elder_id=nanna, fcm_token=TOKEN)

    assert firestore_service.get_device_tokens(amma) == [TOKEN]
    assert firestore_service.get_device_tokens(nanna) == [TOKEN]


def test_the_same_person_registering_twice_is_not_counted_twice(firestore_service, db):
    amma = firestore_service.create_elder(name="Amma", caregiver_id="c1")

    firestore_service.register_device(elder_id=amma, fcm_token=TOKEN)
    firestore_service.register_device(elder_id=amma, fcm_token=TOKEN)

    device = db.collection("devices").document(TOKEN).get().to_dict()
    assert device["elder_ids"] == [amma]


def test_a_device_registered_before_sharing_keeps_working(firestore_service, db):
    """Old documents carry a single elder_id and no list."""
    amma = firestore_service.create_elder(name="Amma", caregiver_id="c1")
    db.collection("devices").document(TOKEN).set({
        "elder_id": amma,
        "fcm_token": TOKEN,
        "platform": "ANDROID",
        "active": True,
    })

    assert firestore_service.get_device_tokens(amma) == [TOKEN]

    nanna = firestore_service.create_elder(name="Nanna", caregiver_id="c1")
    firestore_service.register_device(elder_id=nanna, fcm_token=TOKEN)

    assert firestore_service.get_device_tokens(amma) == [TOKEN]
    assert firestore_service.get_device_tokens(nanna) == [TOKEN]


def test_removing_one_person_leaves_the_other_paired(firestore_service):
    amma = firestore_service.create_elder(name="Amma", caregiver_id="c1")
    nanna = firestore_service.create_elder(name="Nanna", caregiver_id="c1")

    firestore_service.register_device(elder_id=amma, fcm_token=TOKEN)
    firestore_service.register_device(elder_id=nanna, fcm_token=TOKEN)
    firestore_service.unregister_device(elder_id=amma, fcm_token=TOKEN)

    assert firestore_service.get_device_tokens(amma) == []
    assert firestore_service.get_device_tokens(nanna) == [TOKEN]


def test_removing_the_last_person_deactivates_the_device(firestore_service):
    amma = firestore_service.create_elder(name="Amma", caregiver_id="c1")

    firestore_service.register_device(elder_id=amma, fcm_token=TOKEN)
    firestore_service.unregister_device(elder_id=amma, fcm_token=TOKEN)

    assert firestore_service.get_device_tokens(amma) == []


def test_each_persons_reminder_reaches_the_shared_phone(
    firestore_service, notifications, db
):
    """The delivery path, not just the bookkeeping.

    FCM is stubbed out in tests, so the dispatch record carries how many
    devices the reminder was addressed to.
    """
    amma = firestore_service.create_elder(name="Amma", caregiver_id="c1")
    nanna = firestore_service.create_elder(name="Nanna", caregiver_id="c1")

    firestore_service.register_device(elder_id=amma, fcm_token=TOKEN)
    firestore_service.register_device(elder_id=nanna, fcm_token=TOKEN)

    for elder_id, name in ((amma, "Amma"), (nanna, "Nanna")):
        result = notifications.send_reminder(
            elder={"id": elder_id, "name": name},
            medication={"id": "m1", "name": "Metformin", "dose": "1 tablet"},
            event={"id": "e1"},
        )
        record = (
            db.collection("notifications")
            .document(result["notification_id"])
            .get()
            .to_dict()
        )
        assert record["device_count"] == 1, f"{name} did not reach the shared phone"
