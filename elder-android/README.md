# CareBridge — elder Android app

Kotlin + Jetpack Compose. Receives a high-priority FCM reminder, shows the
medicine with the caregiver's photo, plays the caregiver's recorded voice, and
takes a spoken or tapped response.

## Before it will build

1. Create an Android Studio project keystore/SDK as usual, then set `sdk.dir`
   in `local.properties`.
2. In the Firebase console, add an Android app with package
   `com.carebridge.elder` and download `google-services.json` into `app/`.
   The file is gitignored because it is per-project.
3. Enable Firebase Cloud Messaging on the same GCP project the backend uses.

## Pointing it at the backend

`API_BASE_URL` defaults to `http://10.0.2.2:8000`, which is how an emulator
reaches a server on the host machine. Override at build time:

    ./gradlew installDebug -PapiBaseUrl=https://carebridge-api-xxxx.run.app

Cleartext HTTP is permitted only for `10.0.2.2` and `localhost`
(`res/xml/network_security_config.xml`); everything else must be HTTPS.

## Pairing

The caregiver reads the elder id from the dashboard and types it into the
pairing screen. The app registers its FCM token against that elder, and from
then on reminders arrive without anyone opening the app.

With `AUTH_ENABLED=true` on the backend this header-based pairing is rejected;
the device must exchange a Firebase custom token (see
`mint_elder_pairing_token` in `backend/app/api/auth.py`) for an ID token
carrying an `elder_id` claim, and send it as a bearer token.

## Full-screen reminders

`ReminderActivity` is declared with `showWhenLocked` and `turnScreenOn`, and
the notification carries a full-screen intent. Android grants that takeover on
a locked screen; unlocked, it shows a heads-up notification instead. Both lead
to the same screen. Verify the exact behaviour on your target device — OEM
battery managers vary.

## Not verified here

This module was written but never compiled: the machine it was authored on has
no JDK, Android SDK or Gradle. Open it in Android Studio, let it sync, and
expect to fix dependency-version drift.
