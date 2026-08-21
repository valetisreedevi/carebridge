import { useEffect, useState } from "react";
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
  resendVerificationEmail,
  signOutCaregiver,
  watchUser,
} from "./api/firebase";
import AuthAction from "./pages/AuthAction";
import Dashboard from "./pages/Dashboard";
import ElderView from "./pages/ElderView";
import SignIn from "./pages/SignIn";

function Nav({ user }: { user: User | null }) {
  const { pathname } = useLocation();

  // Once a phone belongs to the elder there is nothing for them to
  // navigate to, and the caregiver's email is not theirs to see.
  if (pathname === "/elder" && pairedElderId()) return null;

  // The action page is reached from an email, often by someone who cannot
  // sign in. Navigation would only offer them doors they cannot open.
  if (pathname === "/auth/action") return null;

  return (
    <nav className="nav">
      <span className="nav__brand">CareBridge</span>
      <Link className={pathname === "/" ? "nav__on" : ""} to="/">
        Family
      </Link>
      <Link className={pathname === "/elder" ? "nav__on" : ""} to="/elder">
        Elder device
      </Link>

      {user && (
        <span className="nav__account">
          <span className="nav__email">{user.email}</span>
          <button type="button" onClick={signOutCaregiver}>
            Sign out
          </button>
        </span>
      )}
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

  useEffect(() => {
    if (!firebaseConfigured) return;

    return watchUser((next) => {
      setUser(next);
      setChecking(false);
    });
  }, []);

  if (checking) {
    return <main className="signin"><p>Loading…</p></main>;
  }

  // The elder screen is reached by a paired device, not by a signed-in
  // caregiver, so it stays outside the sign-in gate.
  const caregiverArea =
    firebaseConfigured && !user ? <SignIn /> : <Dashboard />;

  return (
    <BrowserRouter>
      <Nav user={user} />
      {user && !emailIsVerified(user) && <VerifyBanner user={user} />}
      <Routes>
        <Route path="/" element={caregiverArea} />
        <Route path="/elder" element={<ElderView />} />
        {/* Outside the sign-in gate: someone resetting a password cannot
            sign in, which is the whole reason they are here. */}
        <Route path="/auth/action" element={<AuthAction />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
