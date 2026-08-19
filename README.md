# CareBridge

An AI medication companion for elderly people, and the family members who
worry about them.

At medication time CareBridge reaches the elder rather than waiting to be
opened. It plays a recording in a family member's own voice, shows the
medicine, and listens. The elder answers in plain speech — "I took it",
"remind me in ten minutes", "which medicine?" — and Gemini, through a small set
of controlled tools, decides what that means. The backend decides what is
allowed to happen. If nobody answers after the configured attempts, the family
is told.

    reminder → family voice → elder speaks → agent understands
             → tool → backend validates → retry → escalation

## What is here

| Path              | What it is                                                  |
| ----------------- | ----------------------------------------------------------- |
| `backend/`        | FastAPI on Cloud Run: API, state machine, ADK agent, worker  |
| `frontend/`       | React + Vite: caregiver dashboard and an elder web client    |
| `elder-android/`  | Kotlin + Compose elder app with FCM full-screen reminders    |
| `infrastructure/` | Deploy script, Firestore and Storage rules                   |

## Running it locally

Requires Python 3.12, Node 20+, and `gcloud auth application-default login`
against a project with Firestore, Cloud Storage and Vertex AI enabled.

```bash
# backend
cd backend
python -m venv .venv && .venv/Scripts/activate    # or source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                              # then fill in your project
uvicorn app.main:app --reload --port 8000

# frontend, in another terminal
cd frontend
npm install
npm run dev                                       # http://localhost:5173
```

If the API is not on port 8000, put `VITE_API_URL=http://127.0.0.1:<port>` in
`frontend/.env.local`.

Open the dashboard, add a person, add a medication, and press **Remind now** —
that fires the reminder immediately instead of waiting for the clock. Then
**Pair this browser as …** and switch to the elder view.

## Verifying it

```bash
cd backend
pytest                       # 33 tests, no network needed
python scripts/e2e_demo.py   # real Firestore, real GCS, real Gemini
```

`scripts/e2e_demo.py` walks both storylines end to end: a conversation that
ends in a confirmation, and a silence that ends in an escalation. It also
asserts the safety rules — that "Okay." is not a confirmation, that the agent
refuses to change a dose, and that the alert says *not confirmed* rather than
*not taken*.

## How the pieces fit

**Cloud Scheduler** calls `POST /api/internal/reminders/process` every minute.
Each run does two passes: turn medication schedules into concrete events for
the elder's local day, then act on every event whose next attempt is due —
send a reminder, or escalate if the attempts are used up.

**The event is the unit of state.** `next_attempt_at` is what the worker polls;
terminal states clear it, which is how a confirmed medication drops out of the
query with a single inequality filter and no composite index.

    PENDING → REMINDER_SENT → TAKEN
                            → DECLINED
                            → SNOOZED → REMINDER_SENT → ESCALATED

Transitions are applied inside a Firestore transaction and rejected if illegal,
so a race between the elder tapping "I took it" and the worker escalating
cannot produce a confused record.

**The agent decides what the elder meant. The backend decides what happens.**
The agent has six tools and no other database access. None of them takes an
elder id or an event id as an argument — those come from an ambient request
context set from the caller's credentials, so the model cannot reach another
family's records by inventing an identifier.

    get_current_reminder      get_medication_instructions
    confirm_medication_taken  snooze_reminder
    record_decline            notify_caregiver

## Safety rules, and where they live

| Rule                                          | Enforced in                       |
| --------------------------------------------- | --------------------------------- |
| Ambiguity is never a confirmation             | agent prompt                      |
| No dose, schedule or instruction changes      | agent prompt; no tool can do it   |
| Food-instruction conflicts get the record, not advice | agent prompt              |
| Snooze bounded to 1–60 minutes                | `medication_tools.snooze_reminder`|
| Finished events cannot be reopened            | `medication_event.ALLOWED_TRANSITIONS` |
| Silence is "not confirmed", never "not taken" | `reminder_service._escalate`      |
| One family cannot see another's records       | `auth.require_elder_access`       |

Every one of these has a test.

## Authentication

`AUTH_ENABLED=false` (the default) lets callers identify themselves with an
`X-Caregiver-Id` or `X-Elder-Id` header. That is for local development and
demos only.

With `AUTH_ENABLED=true` caregivers must present a Firebase ID token, and elder
devices must present one carrying an `elder_id` claim, obtained by exchanging
the custom token from `mint_elder_pairing_token`. Ownership is checked on every
request either way — the header mode changes who you can claim to be, not what
that person is allowed to reach.

The worker endpoint is separately protected by `WORKER_TOKEN`, which Cloud
Scheduler sends as a header on top of its OIDC identity.

## Deploying

```bash
PROJECT_ID=your-project ./infrastructure/deploy.sh
```

Creates the service accounts and roles, stores a generated worker token in
Secret Manager, deploys to Cloud Run with `AUTH_ENABLED=true`, and creates the
once-a-minute scheduler job.

Note that Gemini 3.x is served from Vertex's **global** endpoint, not a region.
`GCP_LOCATION=global` is deliberate; `us-central1` returns 404 for
`gemini-3.6-flash`.

## Known gaps

- **The Android app has never been compiled.** It was written on a machine
  with no JDK or Android SDK. Open it in Android Studio and expect to fix
  dependency-version drift. See `elder-android/README.md`.
- **Signed URLs need a service-account key.** On local user credentials
  signing is unavailable, so media falls back to streaming through the API.
  On Cloud Run the deployed service account can sign.
- **Multi-caregiver escalation is single-tier.** Every caregiver on the elder
  gets the same alert; there is no primary/secondary/emergency ladder yet.
- **English only.** The data model carries `preferred_language` and the
  clients pass a speech tag, but the prompt and the UI copy are English.
