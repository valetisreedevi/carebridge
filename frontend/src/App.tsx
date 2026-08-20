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
import { firebaseConfigured, signOutCaregiver, watchUser } from "./api/firebase";
import Dashboard from "./pages/Dashboard";
import ElderView from "./pages/ElderView";
import SignIn from "./pages/SignIn";

function Nav({ user }: { user: User | null }) {
  const { pathname } = useLocation();

  // Once a phone belongs to the elder there is nothing for them to
  // navigate to, and the caregiver's email is not theirs to see.
  if (pathname === "/elder" && pairedElderId()) return null;

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
      <Routes>
        <Route path="/" element={caregiverArea} />
        <Route path="/elder" element={<ElderView />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
