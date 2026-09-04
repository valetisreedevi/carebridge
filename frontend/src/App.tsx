import { useEffect, useReducer, useState } from "react";
import {
  BrowserRouter,
  Link,
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import type { User } from "firebase/auth";
import { pairedElderId } from "./api/client";
import {
  emailIsVerified,
  firebaseConfigured,
  refreshUser,
  resendVerificationEmail,
  setDisplayName,
  signOutCaregiver,
  watchUser,
} from "./api/firebase";
import AuthAction from "./pages/AuthAction";
import Dashboard from "./pages/Dashboard";
import ElderView from "./pages/ElderView";
import Landing from "./pages/Landing";
import SignIn from "./pages/SignIn";

/** Something to call them that is not their email address.
 *
 *  A header sits on screen through every screen-share, every screenshot and
 *  every demo recording, and it is telling the one person who already knows.
 *  The address itself stays in the tooltip, for the one case that needs it:
 *  working out which account you are signed in as on a shared computer.
 */
function callThem(user: User): string {
  if (user.displayName?.trim()) return user.displayName.trim();

  const local = (user.email ?? "").split("@")[0].replace(/[._-]+/g, " ").trim();
  if (!local) return "Your account";

  // Trailing digits are almost always an availability tax, not a name.
  const words = local.replace(/\d+$/, "").trim() || local;
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function Account({ user }: { user: User }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(user.displayName ?? "");
  const [saving, setSaving] = useState(false);

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!draft.trim()) return;
    setSaving(true);
    try {
      await setDisplayName(draft);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  if (editing) {
    return (
      <form className="nav__account" onSubmit={save}>
        <input
          className="nav__nameInput"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="What should we call you?"
          aria-label="Your name"
          autoFocus
        />
        <button type="submit" disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </button>
        <button type="button" onClick={() => setEditing(false)}>
          Cancel
        </button>
      </form>
    );
  }

  return (
    <span className="nav__account">
      <button
        type="button"
        className="nav__name"
        onClick={() => setEditing(true)}
        title={user.email ?? undefined}
      >
        {callThem(user)}
      </button>
      <button type="button" onClick={signOutCaregiver}>
        Sign out
      </button>
    </span>
  );
}

function Nav({ user }: { user: User | null }) {
  const { pathname } = useLocation();

  // Once a phone belongs to the elder there is nothing for them to
  // navigate to, and the caregiver's email is not theirs to see.
  if (pathname === "/elder" && pairedElderId()) return null;

  // The action page is reached from an email, often by someone who cannot
  // sign in. Navigation would only offer them doors they cannot open.
  if (pathname === "/auth/action") return null;

  // The landing page carries its own header and its own call to action.
  if (!user && pathname === "/") return null;
  if (pathname === "/signin") return null;

  return (
    <nav className="nav">
      {/* The mark lived only in the browser tab until now. A wordmark with
          nothing beside it reads as a heading, not as a product. */}
      <span className="nav__brand">
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
        CareBridge
      </span>
      <Link className={pathname === "/" ? "nav__on" : ""} to="/">
        Family
      </Link>
      <Link className={pathname === "/elder" ? "nav__on" : ""} to="/elder">
        Elder device
      </Link>

      {user && <Account user={user} />}
    </nav>
  );
}

/** Shown until the caregiver clicks the link in their sign-up email. */
function VerifyBanner({ user }: { user: User }) {
  const [sent, setSent] = useState(false);

  return (
    <div className="banner" role="status">
      <span>
        Confirm <strong>{user.email}</strong> to secure your account. The link is
        in your inbox.
      </span>
      <button
        type="button"
        onClick={async () => {
          await resendVerificationEmail();
          setSent(true);
        }}
        disabled={sent}
      >
        {sent ? "Email sent" : "Resend email"}
      </button>
    </div>
  );
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(firebaseConfigured);
  const [, recheck] = useReducer((n: number) => n + 1, 0);

  useEffect(() => {
    if (!firebaseConfigured) return;

    return watchUser((next) => {
      setUser(next);
      setChecking(false);
    });
  }, []);

  // Verifying an address happens in a different tab, and the User object this
  // tab is holding keeps saying emailVerified: false until it is reloaded. The
  // banner therefore outlived the thing it was asking for — it was still
  // demanding confirmation of an address that had just been confirmed.
  // onAuthStateChanged does not fire for this, so the re-render is forced.
  useEffect(() => {
    if (!firebaseConfigured) return;

    const onFocus = () => {
      refreshUser().then(recheck);
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, []);

  if (checking) {
    return <main className="signin"><p>Loading…</p></main>;
  }

  // The elder screen is reached by a paired device, not by a signed-in
  // caregiver, so it stays outside the sign-in gate.
  // A stranger opening the bare URL used to get a sign-in form and no idea
  // what they were signing in to. They get the product's argument instead, one
  // click from the form.
  const caregiverArea =
    firebaseConfigured && !user ? <Landing /> : <Dashboard />;

  return (
    <BrowserRouter>
      <Nav user={user} />
      {user && !emailIsVerified(user) && <VerifyBanner user={user} />}
      <Routes>
        <Route path="/" element={caregiverArea} />
        {/* Signing in left the form on screen, because nothing sent a
            signed-in caregiver anywhere. Success and failure looked identical:
            the same page, the same filled-in fields. */}
        <Route
          path="/signin"
          element={user ? <Navigate to="/" replace /> : <SignIn />}
        />
        <Route path="/elder" element={<ElderView />} />
        {/* Outside the sign-in gate: someone resetting a password cannot
            sign in, which is the whole reason they are here. */}
        <Route path="/auth/action" element={<AuthAction />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
