"""What actually goes on the wire, and why it differs per phone.

A message carrying a notification block is drawn by Android's own system tray,
and the app's code is never run while the phone is asleep. For a browser that is
exactly right — there is no app to run. For the elder's native app it is fatal:
taking over a locked screen and speaking in the family's voice is the whole job,
and none of it happens if the tray answers first.

The difference is invisible everywhere else. Delivery succeeds either way, the
notifications collection looks identical, and the only symptom is an elderly
woman who is never reminded. So it is pinned here.
"""

from types import SimpleNamespace

import pytest

from app.services import notification_service as module


class FakeMessaging:
    """Just enough of firebase_admin.messaging to see what was built.

    The real suite switches FCM off and asserts against Firestore instead,
    which cannot see payload shape at all — the send is short-circuited before
    a message exists. These tests switch it back on and record instead of send.
    """

    def __init__(self):
        self.sent = []

    def MulticastMessage(self, **fields):
        return fields

    def Notification(self, **fields):
        return {"kind": "notification", **fields}

    def AndroidConfig(self, **fields):
        return {"kind": "android_config", **fields}

    def AndroidNotification(self, **fields):
        return {"kind": "android_notification", **fields}

    def send_each_for_multicast(self, message):
        self.sent.append(message)
        return SimpleNamespace(success_count=len(message["tokens"]))


@pytest.fixture
def fcm(monkeypatch):
    fake = FakeMessaging()
    monkeypatch.setattr(module, "FCM_AVAILABLE", True)
    monkeypatch.setattr(module, "messaging", fake)
    return fake


def remind(db):
    module.NotificationService(db).send_reminder(
        elder={"id": "elder_1", "name": "Amma"},
        medication={"id": "med_1", "name": "Amlodipine", "dose": "1 tablet"},
        event={"id": "event_1", "attempt": 0},
    )


def test_an_android_phone_is_sent_a_message_the_app_itself_must_handle(
    db, firestore_service, fcm
):
    firestore_service.register_device("elder_1", "token-on-the-android", platform="ANDROID")

    remind(db)

    [message] = fcm.sent
    assert message["tokens"] == ["token-on-the-android"]
    assert message.get("notification") is None, (
        "a notification block hands the message to the system tray, and the "
        "app never wakes to take over the locked screen"
    )
    assert message["data"]["type"] == "MEDICATION_REMINDER"
    assert message["data"]["event_id"] == "event_1"


def test_the_android_message_carries_the_words_so_the_app_need_not_ask(
    db, firestore_service, fcm
):
    """The notification is posted before the app can fetch anything.

    Without the text travelling with the push, the first thing an elder sees is
    whatever the app hardcoded, in whatever language it was written in.
    """
    firestore_service.register_device("elder_1", "token-on-the-android", platform="ANDROID")

    remind(db)

    [message] = fcm.sent
    assert message["data"]["title"] == "Medicine time"
    assert message["data"]["body"] == "Amlodipine - 1 tablet"


def test_a_browser_still_gets_the_tray_notification_it_cannot_draw_itself(
    db, firestore_service, fcm
):
    firestore_service.register_device("elder_1", "token-in-a-browser", platform="WEB")

    remind(db)

    [message] = fcm.sent
    assert message["tokens"] == ["token-in-a-browser"]
    assert message["notification"]["title"] == "Medicine time"
    assert message["android"]["notification"]["channel_id"] == "carebridge_reminders"


def test_a_phone_registered_before_platforms_mattered_is_treated_as_a_browser(
    db, firestore_service, fcm
):
    """Old device documents predate the field and must not silently go quiet.

    Treating an unknown platform as a browser keeps today's behaviour for
    everyone already paired. Guessing Android instead would strip the tray
    notification from phones that have no app to replace it.
    """
    firestore_service.register_device("elder_1", "token-from-before", platform=None)

    remind(db)

    [message] = fcm.sent
    assert message["notification"] is not None


def test_a_household_with_both_kinds_of_phone_gets_both_shapes(
    db, firestore_service, fcm
):
    """Amma's app and a caregiver watching the web page, on the same dose."""
    firestore_service.register_device("elder_1", "token-on-the-android", platform="ANDROID")
    firestore_service.register_device("elder_1", "token-in-a-browser", platform="WEB")

    remind(db)

    assert len(fcm.sent) == 2
    shapes = {
        message["tokens"][0]: message.get("notification") is None
        for message in fcm.sent
    }
    assert shapes == {"token-on-the-android": True, "token-in-a-browser": False}


def test_the_dose_is_recorded_as_reaching_every_phone_of_either_kind(
    db, firestore_service, fcm
):
    """Splitting the send must not halve the count the family is shown."""
    firestore_service.register_device("elder_1", "token-on-the-android", platform="ANDROID")
    firestore_service.register_device("elder_1", "token-in-a-browser", platform="WEB")

    remind(db)

    [recorded] = list(db.collection("notifications").stream())
    assert recorded.to_dict()["device_count"] == 2
    assert recorded.to_dict()["delivered_to"] == 2
