import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  actionCodeEmail,
  applyEmailActionCode,
  completePasswordReset,
  friendlyAuthError,
  passwordResetEmail,
} from "../api/firebase";

/**
 * Handles the links CareBridge emails out — confirm your address, reset your
 * password.
 *
 * Firebase hosts a page for this, but its failure text ("the selected page
 * mode is invalid") tells a locked-out person nothing, and the most common
 * failure is not their fault: mail clients wrap the very long URL onto a
 * second line, so the half that carries the code never arrives. That case gets
 * named here in plain words.
 */

type Phase = "working" | "done" | "needsPassword" | "failed";

const APPLY_MODES = new Set([
  "verifyEmail",
  "recoverEmail",
  "verifyAndChangeEmail",
]);

export default function AuthAction() {
  const [params] = useSearchParams();
  const mode = params.get("mode");
  const oobCode = params.get("oobCode");

  const [phase, setPhase] = useState<Phase>("working");
  const [heading, setHeading] = useState("One moment…");
  const [detail, setDetail] = useState<string | null>(null);
  const [account, setAccount] = useState<string | null>(null);

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  const fail = useCallback((title: string, why: string) => {
    setPhase("failed");
    setHeading(title);
    setDetail(why);
  }, []);

  useEffect(() => {
    // A link that arrives without its code is the truncation case. Saying so
    // is the whole reason this page exists.
    if (!mode || !oobCode) {
      fail(
        "This link is incomplete",
        "Email apps sometimes break a long link across two lines, and only the " +
          "first half opens. Go back to the email, copy the whole link, and " +
          "paste it into your browser's address bar.",
      );
      return;
    }

    if (mode === "resetPassword") {
      passwordResetEmail(oobCode)
        .then((email) => {
          setAccount(email);
          setPhase("needsPassword");
          setHeading("Choose a new password");
        })
        .catch((e) => fail("That link did not work", friendlyAuthError(e)));
      return;
    }

    if (APPLY_MODES.has(mode)) {
      // Read the address before spending the code; afterwards it is gone.
      actionCodeEmail(oobCode)
        .then((email) => setAccount(email))
        .finally(() =>
          applyEmailActionCode(oobCode)
            .then(() => {
              setPhase("done");
              setHeading(
                mode === "verifyEmail"
                  ? "Email confirmed"
                  : "Your sign-in email was updated",
              );
            })
            .catch((e) => fail("That link did not work", friendlyAuthError(e))),
        );
      return;
    }

    fail(
      "This link is not one CareBridge sends",
      "Check that you opened it from a CareBridge email. If you did, ask for a new one.",
    );
  }, [mode, oobCode, fail]);

  const submitPassword = async (event: React.FormEvent) => {
    event.preventDefault();
    if (password !== confirm) {
      setDetail("The two passwords do not match.");
      return;
    }

    setBusy(true);
    setDetail(null);
    try {
      await completePasswordReset(oobCode as string, password);
      setPhase("done");
      setHeading("Password changed");
    } catch (e) {
      setDetail(friendlyAuthError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="signin">
      <div className="signin__card">
        <div className="signin__mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="28" height="28">
            <path fill="currentColor" d="M10 3h4v5h5v4h-5v5h-4v-5H5V8h5V3z" />
          </svg>
        </div>

        <h1>{heading}</h1>
        {account && phase !== "failed" && (
          <p className="signin__sub">{account}</p>
        )}

        {phase === "needsPassword" && (
          <form className="signin__form" onSubmit={submitPassword}>
            <label>
              New password
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                required
                minLength={8}
              />
              <small className="signin__hint">At least 8 characters.</small>
            </label>

            <label>
              Confirm new password
              <input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
                required
                minLength={8}
              />
            </label>

            {detail && (
              <p className="signin__error" role="alert">
                {detail}
              </p>
            )}

            <button
              type="submit"
              className="signin__primary btn-primary"
              disabled={busy}
            >
              {busy ? "Saving…" : "Save new password"}
            </button>
          </form>
        )}

        {phase === "failed" && (
          <p className="signin__error" role="alert">
            {detail}
          </p>
        )}

        {phase === "done" && (
          <p className="signin__notice" role="status">
            You can sign in now.
          </p>
        )}

        {phase !== "needsPassword" && (
          <p className="signin__switch">
            <Link to="/">Go to CareBridge</Link>
          </p>
        )}
      </div>
    </main>
  );
}
