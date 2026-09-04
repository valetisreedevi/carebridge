import { useState } from "react";
import {
  friendlyAuthError,
  googleSignInEnabled,
  registerWithPassword,
  sendPasswordReset,
  signInWithGoogle,
  signInWithPassword,
} from "../api/firebase";

type Mode = "in" | "up" | "reset";

const HEADING: Record<Mode, string> = {
  in: "Welcome back",
  up: "Create your account",
  reset: "Reset your password",
};

const SUBHEADING: Record<Mode, string> = {
  in: "Keep track of a family member's medication, without having to ask.",
  up: "It takes a minute. You will add the person you care for next.",
  reset: "We will email you a link to choose a new password.",
};

export default function SignIn() {
  const [mode, setMode] = useState<Mode>("in");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const go = (next: Mode) => {
    setMode(next);
    setError(null);
    setNotice(null);
    setConfirm("");
  };

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();

    // Caught here rather than by Firebase: a mistyped password on sign-up
    // creates a real account nobody can get back into.
    if (mode === "up" && password !== confirm) {
      setError("The two passwords do not match.");
      return;
    }

    setBusy(true);
    setError(null);
    setNotice(null);

    try {
      if (mode === "in") {
        await signInWithPassword(email.trim(), password);
      } else if (mode === "up") {
        await registerWithPassword(email.trim(), password, name);
      } else {
        await sendPasswordReset(email.trim());
        setNotice(
          "If that email has an account, a reset link is on its way. " +
            "Check your spam folder too.",
        );
      }
    } catch (e) {
      setError(friendlyAuthError(e));
    } finally {
      setBusy(false);
    }
  };

  const google = async () => {
    setBusy(true);
    setError(null);
    try {
      await signInWithGoogle();
    } catch (e) {
      setError(friendlyAuthError(e));
    } finally {
      setBusy(false);
    }
  };

  const action =
    mode === "in" ? "Sign in" : mode === "up" ? "Create account" : "Email me a link";

  return (
    <main className="signin">
      <div className="signin__card">
        {/* Was a generic medical cross, which is a different symbol from the
          one in the tab. A product with two marks has none. */}
      <div className="signin__mark" aria-hidden="true">
        <svg className="mark" viewBox="0 0 64 64" aria-hidden="true">
            <circle cx="19" cy="19" r="8" fill="currentColor" />
            <path
              d="M10 49V37a9.5 9.5 0 0 1 9.5-9.5"
              fill="none"
              stroke="currentColor"
              strokeWidth="6"
              strokeLinecap="round"
            />
            <path
              d="M19 31c9 0 17 3 22 8"
              fill="none"
              stroke="currentColor"
              strokeWidth="5.5"
              strokeLinecap="round"
            />
            <circle cx="44" cy="26" r="6.5" fill="currentColor" />
            <path
              d="M36 49v-7a8 8 0 0 1 16 0v7"
              fill="none"
              stroke="currentColor"
              strokeWidth="6"
              strokeLinecap="round"
            />
          </svg>
      </div>

        <h1>{HEADING[mode]}</h1>
        <p className="signin__sub">{SUBHEADING[mode]}</p>

        <form className="signin__form" onSubmit={submit}>
          {mode === "up" && (
            <label>
              Your name
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoComplete="name"
                placeholder="Sridevi"
              />
              <small className="signin__hint">
                What CareBridge calls you. Your email stays private.
              </small>
            </label>
          )}

          <label>
            Email
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              placeholder="you@example.com"
              required
            />
          </label>

          {mode !== "reset" && (
            <label>
              Password
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={mode === "in" ? "current-password" : "new-password"}
                required
                minLength={8}
              />
              {mode === "up" && (
                <small className="signin__hint">At least 8 characters.</small>
              )}
            </label>
          )}

          {mode === "up" && (
            <label>
              Confirm password
              <input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
                required
                minLength={8}
              />
            </label>
          )}

          {error && (
            <p className="signin__error" role="alert">
              {error}
            </p>
          )}
          {notice && (
            <p className="signin__notice" role="status">
              {notice}
            </p>
          )}

          <button
            type="submit"
            className="signin__primary btn-primary"
            disabled={busy}
          >
            {busy ? "One moment…" : action}
          </button>
        </form>

        {mode === "in" && (
          <button
            type="button"
            className="signin__link"
            onClick={() => go("reset")}
          >
            Forgot your password?
          </button>
        )}

        {googleSignInEnabled && mode !== "reset" && (
          <>
            <div className="signin__or">
              <span>or</span>
            </div>
            <button
              type="button"
              className="signin__google"
              onClick={google}
              disabled={busy}
            >
              Continue with Google
            </button>
          </>
        )}

        <p className="signin__switch">
          {mode === "in" && (
            <>
              No account yet?{" "}
              <button type="button" onClick={() => go("up")}>
                Create one
              </button>
            </>
          )}
          {mode === "up" && (
            <>
              Already have an account?{" "}
              <button type="button" onClick={() => go("in")}>
                Sign in
              </button>
            </>
          )}
          {mode === "reset" && (
            <button type="button" onClick={() => go("in")}>
              Back to sign in
            </button>
          )}
        </p>
      </div>
    </main>
  );
}
