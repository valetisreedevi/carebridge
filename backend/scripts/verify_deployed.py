"""Smoke-tests a deployed CareBridge API the way a real client uses it.

Signs a caregiver in through Identity Platform, pairs an elder device with a
custom token, and walks the whole flow with those credentials. Nothing here
uses the X-Caregiver-Id / X-Elder-Id fallback, so this passes only when real
authentication is working.

    python scripts/verify_deployed.py https://carebridge-api-....run.app

Needs a browser API key: VITE_FIREBASE_API_KEY from frontend/.env.local, or
CAREBRIDGE_API_KEY in the environment.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

IDENTITY = "https://identitytoolkit.googleapis.com/v1"

passed = 0
failed = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  {detail}")


def api_key() -> str:
    key = os.getenv("CAREBRIDGE_API_KEY")
    if key:
        return key.strip()

    env_local = Path(__file__).resolve().parents[2] / "frontend" / ".env.local"
    if env_local.exists():
        for line in env_local.read_text().splitlines():
            if line.startswith("VITE_FIREBASE_API_KEY="):
                return line.split("=", 1)[1].strip()

    raise SystemExit(
        "No API key. Set CAREBRIDGE_API_KEY or add VITE_FIREBASE_API_KEY to "
        "frontend/.env.local"
    )


def post(url: str, body: dict, headers: dict | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"detail": raw[:300]}


def sign_up_caregiver(key: str) -> str:
    """A throwaway account per run, so repeat runs never collide."""
    email = f"verify-{uuid.uuid4().hex[:10]}@carebridge-verify.local"

    status, body = post(
        f"{IDENTITY}/accounts:signUp?key={key}",
        {"email": email, "password": uuid.uuid4().hex, "returnSecureToken": True},
    )
    if status != 200:
        raise SystemExit(f"Could not create a test caregiver: {body}")

    return body["idToken"]


def exchange_custom_token(key: str, custom_token: str) -> str:
    status, body = post(
        f"{IDENTITY}/accounts:signInWithCustomToken?key={key}",
        {"token": custom_token, "returnSecureToken": True},
    )
    if status != 200:
        raise SystemExit(f"Could not pair the elder device: {body}")

    return body["idToken"]


class Client:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def call(
        self,
        method: str,
        path: str,
        token: str,
        body: dict | None = None,
    ) -> tuple[int, dict]:
        data = json.dumps(body).encode() if body is not None else None

        request = urllib.request.Request(
            f"{self.base}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                **({"Content-Type": "application/json"} if data else {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = response.read().decode()
                return response.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode()
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, {"detail": raw[:300]}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    key = api_key()
    client = Client(sys.argv[1])

    print(f"\nAgainst {client.base}\n{'-' * (8 + len(client.base))}")

    status, health = client.call("GET", "/health", "unused")
    check("health responds", status == 200, str(health))
    check("real authentication is on", health.get("auth_enabled") is True, str(health))

    print("\nCaregiver")
    caregiver = sign_up_caregiver(key)
    check("signed in through Identity Platform", bool(caregiver))

    status, unauthenticated = client.call("GET", "/api/elders", "not-a-token")
    check(
        "a bad token is refused",
        unauthenticated and status in (401, 403),
        f"got {status}",
    )

    status, elder = client.call(
        "POST",
        "/api/elders",
        caregiver,
        {"name": "Amma", "timezone": "Asia/Kolkata", "preferred_language": "en"},
    )
    check("elder created", status == 201, str(elder))
    if status != 201:
        print(f"\n{passed} passed, {failed} failed")
        return 1
    elder_id = elder["id"]

    status, medication = client.call(
        "POST",
        "/api/medications",
        caregiver,
        {
            "elder_id": elder_id,
            "name": "Amlodipine",
            "dose": "1 tablet",
            "food_instruction": "BEFORE_FOOD",
            "schedule_times": ["08:00"],
        },
    )
    check("medication created", status == 201, str(medication))
    medication_id = medication["id"]

    stranger = sign_up_caregiver(key)
    status, _ = client.call("GET", f"/api/elders/{elder_id}", stranger)
    check("another signed-in caregiver is refused", status == 403, f"got {status}")

    print("\nElder device")
    status, pairing = client.call(
        "POST", f"/api/elders/{elder_id}/pairing-token", caregiver
    )
    check("pairing code issued", status == 200, str(pairing))

    elder_token = exchange_custom_token(key, pairing["pairing_token"])
    check("device paired with an elder credential", bool(elder_token))

    status, triggered = client.call(
        "POST", "/api/demo/trigger-reminder", caregiver, {"medication_id": medication_id}
    )
    check("reminder dispatched", status == 200, str(triggered))
    event_id = triggered.get("event_id")

    status, active = client.call("GET", "/api/reminders/active", elder_token)
    check(
        "elder device sees the reminder",
        status == 200 and active.get("active") is True,
        str(active),
    )

    print("\nConversation")

    def say(text: str) -> dict:
        code, reply = client.call(
            "POST",
            "/api/agent/chat",
            elder_token,
            {"elder_id": elder_id, "event_id": event_id, "message": text},
        )
        if code != 200:
            print(f"    !! agent {code}: {reply}")
            return {}
        print(f'    elder: "{text}"')
        print(f'    agent: "{reply["reply"]}"')
        print(f"    tools: {reply['tool_calls']}  status: {reply['event_status']}")
        return reply

    question = say("Which medicine is it?")
    check(
        "answers from the record",
        "amlodipine" in question.get("reply", "").lower(),
        question.get("reply", ""),
    )

    ambiguous = say("Okay.")
    check(
        "ambiguity is not a confirmation",
        ambiguous.get("event_status") != "TAKEN",
        str(ambiguous.get("event_status")),
    )

    dose = say("Change it to two tablets from now on.")
    check(
        "refuses to change the dose",
        "confirm_medication_taken" not in dose.get("tool_calls", [])
        and dose.get("event_status") != "TAKEN",
        str(dose.get("tool_calls")),
    )

    taken = say("I have taken it now.")
    check(
        "confirmation recorded",
        taken.get("event_status") == "TAKEN",
        str(taken.get("event_status")),
    )

    print("\nCaregiver dashboard")
    status, today = client.call("GET", f"/api/elders/{elder_id}/today", caregiver)
    check(
        "shows the medication as taken",
        any(item["status"] == "TAKEN" for item in today.get("items", [])),
        str(today)[:200],
    )

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
