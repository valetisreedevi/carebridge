"""Smoke-tests a deployed CareBridge API over HTTPS.

The service is deployed --no-allow-unauthenticated, so every request carries a
Google identity token on top of whatever the app itself checks.

    python scripts/verify_deployed.py https://carebridge-api-xxxx.run.app

Reads the identity token from CAREBRIDGE_ID_TOKEN, or shells out to
`gcloud auth print-identity-token`.
"""

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

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


def identity_token() -> str:
    token = os.getenv("CAREBRIDGE_ID_TOKEN")
    if token:
        return token.strip()

    return subprocess.run(
        ["gcloud", "auth", "print-identity-token"],
        capture_output=True,
        text=True,
        check=True,
        shell=sys.platform == "win32",
    ).stdout.strip()


class Client:
    def __init__(self, base: str, token: str):
        self.base = base.rstrip("/")
        self.token = token

    def call(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        headers: dict | None = None,
    ) -> tuple[int, dict]:
        data = json.dumps(body).encode() if body is not None else None

        request = urllib.request.Request(
            f"{self.base}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                **({"Content-Type": "application/json"} if data else {}),
                **(headers or {}),
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

    client = Client(sys.argv[1], identity_token())
    caregiver = {"X-Caregiver-Id": "deploy-check"}

    print(f"\nAgainst {client.base}\n{'-' * (8 + len(client.base))}")

    status, health = client.call("GET", "/health")
    check("health responds", status == 200, str(health))
    check(
        "running the expected model on the global endpoint",
        health.get("model", "").startswith("gemini"),
        str(health),
    )
    print(f"    {health}")

    status, elder = client.call(
        "POST",
        "/api/elders",
        {"name": "Amma", "timezone": "Asia/Kolkata", "preferred_language": "te"},
        caregiver,
    )
    check("elder created", status == 201, str(elder))
    if status != 201:
        print(f"\n{passed} passed, {failed} failed")
        return 1

    elder_id = elder["id"]

    status, medication = client.call(
        "POST",
        "/api/medications",
        {
            "elder_id": elder_id,
            "name": "Amlodipine",
            "dose": "1 tablet",
            "food_instruction": "BEFORE_FOOD",
            "schedule_times": ["08:00"],
        },
        caregiver,
    )
    check("medication created", status == 201, str(medication))
    medication_id = medication["id"]

    status, other = client.call(
        "GET", f"/api/elders/{elder_id}", None, {"X-Caregiver-Id": "someone-else"}
    )
    check("another caregiver is refused", status == 403, f"got {status}")

    status, triggered = client.call(
        "POST", "/api/demo/trigger-reminder", {"medication_id": medication_id}, caregiver
    )
    check("reminder dispatched", status == 200, str(triggered))
    event_id = triggered.get("event_id")

    elder_headers = {"X-Elder-Id": elder_id}
    status, active = client.call("GET", "/api/reminders/active", None, elder_headers)
    check(
        "elder device sees the reminder",
        status == 200 and active.get("active") is True,
        str(active),
    )

    def say(text: str) -> dict:
        code, reply = client.call(
            "POST",
            "/api/agent/chat",
            {"elder_id": elder_id, "event_id": event_id, "message": text},
            elder_headers,
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
        "Gemini answers from the record",
        "amlodipine" in question.get("reply", "").lower(),
        question.get("reply", ""),
    )

    ambiguous = say("Okay.")
    check(
        "ambiguity is not a confirmation",
        ambiguous.get("event_status") != "TAKEN",
        str(ambiguous.get("event_status")),
    )

    taken = say("I have taken it now.")
    check(
        "confirmation recorded",
        taken.get("event_status") == "TAKEN",
        str(taken.get("event_status")),
    )

    status, today = client.call("GET", f"/api/elders/{elder_id}/today", None, caregiver)
    check(
        "dashboard shows it as taken",
        any(item["status"] == "TAKEN" for item in today.get("items", [])),
        str(today),
    )

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
