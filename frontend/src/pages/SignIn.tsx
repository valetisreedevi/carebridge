import { useState } from "react";
import {
  friendlyAuthError,
  registerWithPassword,
  signInWithGoogle,
  signInWithPassword,
} from "../api/firebase";

export default function SignIn() {
  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);

    try {
      if (mode === "in") await signInWithPassword(email.trim(), password);
      else await registerWithPassword(email.trim(), password);
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

  return (
    <main className="signin">
      <h1>CareBridge</h1>
      <p className="signin__sub">
        Sign in to look after someone's medication.
      </p>

      <form className="signin__form" onSubmit={submit}>
        <label>
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            required
          />
        </label>

        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "in" ? "current-password" : "new-password"}
            required
            minLength={6}
          />
        </label>

        {error && <p className="dash__error">{error}</p>}

        <button type="submit" className="signin__primary" disabled={busy}>
          {busy ? "One moment…" : mode === "in" ? "Sign in" : "Create account"}
        </button>
      </form>

      <button type="button" onClick={google} disabled={busy}>
        Continue with Google
      </button>

      <button
        type="button"
        className="signin__switch"
        onClick={() => {
          setMode(mode === "in" ? "up" : "in");
          setError(null);
        }}
      >
        {mode === "in"
          ? "No account yet? Create one"
          : "Already have an account? Sign in"}
      </button>
    </main>
  );
}
