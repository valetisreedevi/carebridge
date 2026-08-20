import { initializeApp, type FirebaseApp } from "firebase/app";
import {
  GoogleAuthProvider,
  createUserWithEmailAndPassword,
  getAuth,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signInWithCustomToken,
  signInWithPopup,
  signOut,
  type Auth,
  type User,
} from "firebase/auth";

const config = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

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
 */
let elderAuth: Auth | null = null;

function getElderAuth(): Auth {
  if (!firebaseConfigured) throw new Error("Sign-in is not configured");

  if (!elderAuth) {
    elderAuth = getAuth(initializeApp(config, "elder"));
  }
  return elderAuth;
}

export async function pairElderDevice(pairingToken: string): Promise<string> {
  const auth = getElderAuth();
  const credential = await signInWithCustomToken(auth, pairingToken.trim());

  const claims = await credential.user.getIdTokenResult();
  const elderId = claims.claims.elder_id;

  if (typeof elderId !== "string") {
    throw new Error("That code is not a CareBridge pairing code");
  }
  return elderId;
}

export async function elderIdToken(): Promise<string | null> {
  if (!firebaseConfigured) return null;
  const user = getElderAuth().currentUser;
  return user ? user.getIdToken() : null;
}

export function watchElder(onChange: (user: User | null) => void): () => void {
  if (!firebaseConfigured) {
    onChange(null);
    return () => {};
  }
  return onAuthStateChanged(getElderAuth(), onChange);
}

export async function unpairElderDevice(): Promise<void> {
  if (firebaseConfigured) await signOut(getElderAuth());
}

export function getAuthOrNull(): Auth | null {
  return auth;
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

export async function registerWithPassword(email: string, password: string) {
  if (!auth) throw new Error("Sign-in is not configured");
  await createUserWithEmailAndPassword(auth, email, password);
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
  if (code.includes("network")) return "Cannot reach the sign-in service.";

  return "Sign-in did not work. Please try again.";
}
