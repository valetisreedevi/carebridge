# Turning on caregiver sign-in

The backend already verifies Firebase ID tokens, and the web client already
sends them when it is configured. What is missing is the Firebase project
itself, and creating one needs a console step that cannot be scripted: adding
Firebase to a GCP project requires the account to accept the Firebase terms,
and the Management API returns a bare `403 PERMISSION_DENIED` until that has
happened — even for a project Owner.

Everything below is a one-time setup.

## 1. Add Firebase to the project

Open <https://console.firebase.google.com/> → **Create a project** → **Add
Firebase to a Google Cloud project**, and pick `carecompanion-506011`.

Accept the terms when prompted. That acceptance is the thing the API cannot do
on your behalf.

## 2. Enable Email/Password and Google sign-in

**Build → Authentication → Get started**, then under **Sign-in method** enable:

- Email/Password
- Google

## 3. Register a web app

**Project settings → Your apps → Web (`</>`)**, nickname `CareBridge web`.

Firebase shows a `firebaseConfig` object. Copy four values from it into
`frontend/.env.local`:

```
VITE_FIREBASE_API_KEY=AIza...
VITE_FIREBASE_AUTH_DOMAIN=carecompanion-506011.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=carecompanion-506011
VITE_FIREBASE_APP_ID=1:335038762962:web:...
```

These are not secrets — a Firebase web config is public by design. What
protects the data is the backend checking the token and the ownership rules on
every request.

The web client checks for `VITE_FIREBASE_API_KEY` at build time. Without it,
sign-in stays off and the client falls back to the `X-Caregiver-Id` header,
which is what makes local development work with no Firebase project at all.

## 4. Authorise the domains the app runs on

**Authentication → Settings → Authorized domains.** `localhost` is there by
default. Add the host you serve the built frontend from.

## 5. Turn auth on in the API

Redeploy with the flag flipped:

```bash
PROJECT_ID=carecompanion-506011 ./infrastructure/deploy.sh
```

`AUTH_ENABLED` defaults to `true`, so the plain command is the secure one.
The `AUTH_ENABLED=false` override exists for the private-preview posture
described below and should not outlive it.

## Why the API is currently deployed with AUTH_ENABLED=false

Cloud Run is deployed `--no-allow-unauthenticated`, so the service is not
reachable without a Google identity token: only your own account and the
scheduler service account can call it at all. Inside that boundary the API
trusts the `X-Caregiver-Id` / `X-Elder-Id` headers.

That is a reasonable private-preview posture and a bad public one. Two things
must happen together before anyone else uses it: complete the steps above, and
redeploy with `AUTH_ENABLED=true`.

Note that the elder Android app pairs by sending `X-Elder-Id`, which stops
working under `AUTH_ENABLED=true`. Elder devices then need a Firebase custom
token from `mint_elder_pairing_token` (`backend/app/api/auth.py`), exchanged
for an ID token carrying an `elder_id` claim. That exchange is written on the
backend but not yet wired into either client.
