import { initializeApp, type FirebaseApp } from "firebase/app";
import {
  GoogleAuthProvider,
  applyActionCode,
  checkActionCode,
  confirmPasswordReset,
  createUserWithEmailAndPassword,
  getAuth,
  onAuthStateChanged,
  sendEmailVerification,
  sendPasswordResetEmail,
  signInWithEmailAndPassword,
  updateProfile,
  signInWithCustomToken,
  signInWithPopup,
  signOut,
  verifyPasswordResetCode,
  type Auth,
  type User,
} from "firebase/auth";

const config = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
  // Notifications only. Sign-in works without it, which is why it was
  // missing for as long as nothing pushed.
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
};

/** The values the notification service worker needs, which cannot read them
 *  itself. Only ever the public web config — no key belongs in here. */
export const firebaseConfig = config;

/**
 * Sign-in is optional at build time.
 *
 * Without a Firebase config the app keeps using the header identity the
 * backend accepts when AUTH_ENABLED is false, so local development needs no
 * Firebase project at all. Supplying the config is what turns real auth on,
 * and it must match AUTH_ENABLED=true on the API.
 */
export const firebaseConfigured = Boolean(config.apiKey && config.projectId);

/** Google sign-in needs an OAuth client configured on the provider. Until
 *  that exists the button would always fail, so it is not shown. */
export const googleSignInEnabled =
  import.meta.env.VITE_GOOGLE_SIGN_IN === "true";

let app: FirebaseApp | null = null;
let auth: Auth | null = null;

if (firebaseConfigured) {
  app = initializeApp(config);
  auth = getAuth(app);
}

/**
 * Elder devices sign in as a different principal than the caregiver, so they
 * get their own Firebase app. A single app has one currentUser, and without
 * this a caregiver checking the elder screen on their own laptop would sign
 * themselves out.
 *
 * One app per person, not one per device: a phone on a shared side table can
 * be paired to a couple, and each of them needs their own live session for
 * the API to tell their reminders apart.
 */
const elderApps = new Map<string, Auth>();

function elderAuthFor(elderId: string): Auth {
  if (!firebaseConfigured) throw new Error("Sign-in is not configured");

  let auth = elderApps.get(elderId);
  if (!auth) {
    auth = getAuth(initializeApp(config, `elder:${elderId}`));
    elderApps.set(elderId, auth);
  }
  return auth;
}

/** Reads the elder id out of a pairing code without claiming the session. */
function scratchAuth(): Auth {
  if (!firebaseConfigured) throw new Error("Sign-in is not configured");
  return elderAuthFor("__pairing__");
}

type RedeemedCode = {
  elder_id: string;
  elder_name: string;
  custom_token: string;
};

/**
 * Swaps the spoken code for the credential the device signs in with.
 *
 * A bare fetch rather than the shared client, for two reasons: the elder has
 * no account to authenticate with, and client.ts already imports this module.
 */
async function redeemPairingCode(code: string): Promise<RedeemedCode> {
  const base = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

  const response = await fetch(`${base}/api/pairing/redeem`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });

  if (!response.ok) {
    throw new Error("That code is not a CareBridge pairing code");
  }

  return response.json();
}

/**
 * A Firebase custom token is a JWT: three dot-separated parts, hundreds of
 * characters. A spoken pairing code is eleven. Nothing has to be guessed.
 */
function looksLikeACustomToken(value: string): boolean {
  return value.split(".").length === 3 && value.length > 100;
}

export async function pairElderDevice(
  entered: string,
): Promise<{ elderId: string; elderName: string | null }> {
  const value = entered.trim();

  // The short code is what a family reads to each other; the long token is
  // what the earlier build handed out. Both are accepted, so a phone set up
  // either way keeps working.
  if (!looksLikeACustomToken(value)) {
    const redeemed = await redeemPairingCode(value);
    await signInWithCustomToken(
      elderAuthFor(redeemed.elder_id),
      redeemed.custom_token,
    );
    return { elderId: redeemed.elder_id, elderName: redeemed.elder_name };
  }

  // Which person this token belongs to is only knowable after signing in, and
  // the session has to live under that person's own app. So: read it on a
  // scratch app, then sign in properly. Custom tokens stay valid for an hour,
  // so the second use is fine.
  const probe = await signInWithCustomToken(scratchAuth(), value);
  const claims = await probe.user.getIdTokenResult();
  const elderId = claims.claims.elder_id;

  if (typeof elderId !== "string") {
    throw new Error("That code is not a CareBridge pairing code");
  }

  await signInWithCustomToken(elderAuthFor(elderId), value);
  await signOut(scratchAuth());

  return { elderId, elderName: null };
}

export async function elderIdToken(elderId: string): Promise<string | null> {
  if (!firebaseConfigured) return null;
  const user = elderAuthFor(elderId).currentUser;
  return user ? user.getIdToken() : null;
}

/** Resolves once Firebase has restored (or failed to restore) the session. */
export function watchElder(
  elderId: string,
  onChange: (user: User | null) => void,
): () => void {
  if (!firebaseConfigured) {
    onChange(null);
    return () => {};
  }
  return onAuthStateChanged(elderAuthFor(elderId), onChange);
}

export async function unpairElderDevice(elderId: string): Promise<void> {
  if (firebaseConfigured) await signOut(elderAuthFor(elderId));
}

export function getAuthOrNull(): Auth | null {
  return auth;
}

/** The app notifications register against. Sign-in state is irrelevant to a
 *  push token, so this is the default app even on an elder's phone. */
export function getAppOrNull(): FirebaseApp | null {
  return app;
}

export function watchUser(onChange: (user: User | null) => void): () => void {
  if (!auth) {
    onChange(null);
    return () => {};
  }
  return onAuthStateChanged(auth, onChange);
}

/** Fresh on every call; the SDK caches and refreshes as needed. */
export async function idToken(): Promise<string | null> {
  return auth?.currentUser ? auth.currentUser.getIdToken() : null;
}

export async function signInWithPassword(email: string, password: string) {
  if (!auth) throw new Error("Sign-in is not configured");
  await signInWithEmailAndPassword(auth, email, password);
}

export async function registerWithPassword(
  email: string,
  password: string,
  name?: string,
) {
  if (!auth) throw new Error("Sign-in is not configured");
  const credential = await createUserWithEmailAndPassword(auth, email, password);

  // Asked for at sign-up so the app has something to call them other than
  // their email address, which does not belong in a screen-shared header.
  if (name?.trim()) {
    await updateProfile(credential.user, { displayName: name.trim() });
  }

  // Sent on every new account. Whether an unconfirmed address may actually use
  // the API is the backend's REQUIRE_VERIFIED_EMAIL call, not the browser's.
  await sendEmailVerification(credential.user);
}

/** Lets someone who signed up before the name field existed set one. */
export async function setDisplayName(name: string): Promise<void> {
  if (!auth?.currentUser) throw new Error("Not signed in");
  await updateProfile(auth.currentUser, { displayName: name.trim() });
  // onAuthStateChanged does not fire for a profile edit, so nudge the
  // listeners that are already watching this user.
  await auth.currentUser.reload();
}

export async function resendVerificationEmail() {
  if (auth?.currentUser) await sendEmailVerification(auth.currentUser);
}

export function emailIsVerified(user: User | null): boolean {
  // Google accounts arrive verified; only the password flow needs the prompt.
  return Boolean(user?.emailVerified);
}

export async function sendPasswordReset(email: string) {
  if (!auth) throw new Error("Sign-in is not configured");
  await sendPasswordResetEmail(auth, email);
}

/* ---------------- handling the links those emails contain ----------------
 *
 * Firebase used to handle these on its own hosted page. It is now this app's
 * /auth/action route, so the wording is ours and a half-delivered link can say
 * so instead of "the selected page mode is invalid".
 */

/** Confirms an email address. Also used for the email-change flows. */
export async function applyEmailActionCode(oobCode: string) {
  if (!auth) throw new Error("Sign-in is not configured");
  await applyActionCode(auth, oobCode);
}

/** Whose account a reset link belongs to, so the page can say the address. */
export async function passwordResetEmail(oobCode: string): Promise<string> {
  if (!auth) throw new Error("Sign-in is not configured");
  return verifyPasswordResetCode(auth, oobCode);
}

export async function completePasswordReset(oobCode: string, password: string) {
  if (!auth) throw new Error("Sign-in is not configured");
  await confirmPasswordReset(auth, oobCode, password);
}

/** The address a verification link belongs to, for a friendlier confirmation. */
export async function actionCodeEmail(oobCode: string): Promise<string | null> {
  if (!auth) return null;
  try {
    const info = await checkActionCode(auth, oobCode);
    return info.data.email ?? null;
  } catch {
    return null;
  }
}

export async function signInWithGoogle() {
  if (!auth) throw new Error("Sign-in is not configured");
  await signInWithPopup(auth, new GoogleAuthProvider());
}

export async function signOutCaregiver() {
  if (auth) await signOut(auth);
}

/** Firebase error codes are not something to show a worried family member. */
export function friendlyAuthError(error: unknown): string {
  const code = (error as { code?: string })?.code ?? "";

  if (code.includes("invalid-credential") || code.includes("wrong-password")) {
    return "That email and password do not match.";
  }
  if (code.includes("user-not-found")) return "No account with that email.";
  if (code.includes("email-already-in-use")) {
    return "That email already has an account. Try signing in.";
  }
  if (code.includes("weak-password")) {
    return "Please use a password of at least six characters.";
  }
  if (code.includes("popup-closed")) return "Sign-in was cancelled.";
  if (code.includes("too-many-requests")) {
    return "Too many attempts. Please wait a minute and try again.";
  }
  if (code.includes("invalid-email")) return "That does not look like an email address.";
  if (code.includes("expired-action-code")) {
    return "That link has expired. Ask for a new one and use it within an hour.";
  }
  if (code.includes("invalid-action-code")) {
    return "That link is not valid any more — it may already have been used.";
  }
  if (code.includes("user-disabled")) return "That account has been disabled.";
  if (code.includes("network")) return "Cannot reach the sign-in service.";

  return "Sign-in did not work. Please try again.";
}
