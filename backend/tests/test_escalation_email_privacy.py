"""What an escalation email is allowed to disclose, and to whom.

The alert is health information about someone who did not choose to use this
software. Two things follow: the subject line must survive being read over a
shoulder, and a care team must not be introduced to itself.
"""

import pytest

from app.services import notification_service as module


class FakeSMTP:
    """Captures what would have gone out, per message."""

    sent: list = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def send_message(self, message):
        FakeSMTP.sent.append(message)


@pytest.fixture
def outbox(monkeypatch):
    FakeSMTP.sent = []
    monkeypatch.setattr(module.smtplib, "SMTP", FakeSMTP)

    settings = module.get_settings()
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test", raising=False)
    monkeypatch.setattr(settings, "smtp_user", "carebridge@example.test", raising=False)
    monkeypatch.setattr(settings, "smtp_password", "not-a-real-password", raising=False)
    monkeypatch.setattr(settings, "smtp_from", "carebridge@example.test", raising=False)

    return FakeSMTP.sent


@pytest.fixture
def care_team(firestore_service, notifications, outbox):
    """One elder watched by three people, and a dose to escalate about."""
    for caregiver_id, email in (
        ("daughter", "daughter@example.test"),
        ("son", "son@example.test"),
        ("paid_carer", "carer@agency.example.test"),
    ):
        firestore_service.upsert_caregiver(caregiver_id, email=email)

    elder_id = firestore_service.create_elder(name="Margaret", caregiver_id="daughter")
    for caregiver_id in ("son", "paid_carer"):
        firestore_service.add_caregiver_to_elder(elder_id, caregiver_id)

    notifications.notify_caregiver(
        elder=firestore_service.get_elder(elder_id),
        medication={"id": "med_1", "name": "Metformin"},
        event={"id": "event_1"},
        reason="NOT_CONFIRMED",
        message="Margaret has not confirmed the 9:00 AM Metformin.",
        channel="email",
    )

    return outbox


def test_the_subject_does_not_name_the_medicine(care_team):
    for message in care_team:
        assert "Metformin" not in message["Subject"]


def test_the_subject_says_who_it_is_about(care_team):
    assert all("Margaret" in message["Subject"] for message in care_team)


def test_the_detail_still_reaches_the_body(care_team):
    body = care_team[0].get_content()

    assert "Metformin" in body
    assert "has not confirmed" in body


def test_nobody_learns_the_other_carers_addresses(care_team):
    assert len(care_team) == 3

    for message in care_team:
        recipients = message["To"]
        assert "," not in recipients
        assert message["Cc"] is None
        assert message["Bcc"] is None


def test_every_carer_is_written_to(care_team):
    assert {message["To"] for message in care_team} == {
        "daughter@example.test",
        "son@example.test",
        "carer@agency.example.test",
    }


def test_one_bad_address_does_not_stop_the_rest(
    monkeypatch, firestore_service, notifications, outbox
):
    """A relay rejecting one recipient must not silence the whole care team."""
    original = FakeSMTP.send_message

    def refuse_the_son(self, message):
        if message["To"] == "son@example.test":
            raise RuntimeError("550 mailbox unavailable")
        original(self, message)

    monkeypatch.setattr(FakeSMTP, "send_message", refuse_the_son)

    for caregiver_id, email in (
        ("daughter", "daughter@example.test"),
        ("son", "son@example.test"),
    ):
        firestore_service.upsert_caregiver(caregiver_id, email=email)

    elder_id = firestore_service.create_elder(name="Margaret", caregiver_id="daughter")
    firestore_service.add_caregiver_to_elder(elder_id, "son")

    result = notifications.notify_caregiver(
        elder=firestore_service.get_elder(elder_id),
        medication={"id": "med_1", "name": "Metformin"},
        event={"id": "event_1"},
        reason="NOT_CONFIRMED",
        message="Margaret has not confirmed the 9:00 AM Metformin.",
        channel="email",
    )

    assert result["delivered_to"] == 1
    assert [m["To"] for m in outbox] == ["daughter@example.test"]
