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
pytest                       # 229 tests, no network needed
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
The agent has seven tools and no other database access. None of them takes an
elder id or an event id as an argument — those come from an ambient request
context set from the caller's credentials, so the model cannot reach another
family's records by inventing an identifier.

    get_current_reminder      get_medication_instructions
    confirm_medication_taken  snooze_reminder
    record_decline            report_unclear_reply
    notify_caregiver

`report_unclear_reply` is the one that does nothing. When the model cannot tell
what an answer meant it says so, instead of choosing the likeliest reading: the
dose does not move, what was heard is kept, and after the second one a person
is asked to step in. That threshold is a counter in the backend, never a
judgement the model makes turn by turn.

**Two numbers, kept apart.** Adherence products almost universally report doses
taken over doses scheduled, which turns a phone nobody set up into a woman
ignoring her tablets. Every figure here comes from `models/adherence.py`, which
counts reach and outcome separately and partitions exactly:

    scheduled == asked + unreachable + not_yet_due

The dashboard shows all three, so a family can add them up rather than trust
them. `services/adherence_service.py` computes every rate, median and
week-on-week comparison in plain Python.

**The second agent explains; it never decides.** `adherence_analyst_agent` has
no tools at all — it cannot read the database or reach a household. It is handed
a brief of figures that are already final and asked to write them out for a
worried family. That is what makes a model safe here: by the time it runs, the
decision is made and the first alert has already been sent.

The escalation ladder shows the rule directly. Rung one is a push carrying the
sentence the backend wrote, sent immediately. Rung two, five minutes later, is
an email carrying the analyst's wording — and if the analyst is slow, off or
broken, it carries the same plain sentence rung one did. **The alert never waits
for the model.** The weekly note behaves the same way: `plain_weekly_note` is
what a family reads when Gemini is unavailable, so the note is a feature of
CareBridge rather than of the model being up.

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
| An answer nobody understood is recorded, not guessed | `medication_tools.report_unclear_reply` |
| Two unclear replies fetch a human             | `settings.max_unclear_replies`    |
| Adherence is never divided by undelivered doses | `adherence_service.adherence_of_asked` |
| An escalation is never delayed by the analyst | `reminder_service._narrated`      |

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

- **No reminder has ever reached a real phone.** FCM dispatch is wired and
  logged, but no device has registered a token, so delivery is unproven.
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

## Deployment status

Live on Cloud Run as `carebridge-api` (revision `00003-zgw`, `us-central1`),
deployed `--no-allow-unauthenticated` so only identities holding `run.invoker`
can call it — currently the project owner and the scheduler service account.

Cloud Scheduler drives `POST /api/internal/reminders/process` every minute,
and that loop is verified in production, not just locally:

```
Fired attempt 1, then touched nothing.
  [ 20s] REMINDER_SENT attempt=1
  [ 61s] REMINDER_SENT attempt=2   <- scheduler, unaided
  [123s] ESCALATED     attempt=2   <- scheduler, unaided

Alert: "Amma has not confirmed the 5:06 AM Metformin after 2 reminder attempts."
```

```bash
URL="$(gcloud run services describe carebridge-api   --region us-central1 --format 'value(status.url)')"

python backend/scripts/verify_deployed.py "$URL"    # 11 checks, live Gemini
python backend/scripts/verify_escalation.py "$URL"  # scheduler drives it alone
```

`verify_escalation.py` earns its keep: it fires one reminder and then refuses
to touch the system, so a scheduler that is not actually driving the loop
fails. It caught a production-only bug that every local test passed through.

### Before anyone else uses this

The API runs with `AUTH_ENABLED=false`, which is safe *only* because the
service is not publicly invokable. Two things must happen together before that
changes: complete `infrastructure/FIREBASE_SETUP.md`, then redeploy (the
`AUTH_ENABLED` default is already `true`).

### What is still unproven

Reminders reach the *loop*, not yet a *person*. Every dispatch so far has
logged `-> 0 device(s)` because no device has ever registered an FCM token, so
no elder's phone has actually rung. Proving that needs the Android app built
and paired on a real handset.
