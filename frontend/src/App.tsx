import { BrowserRouter, Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import ElderView from "./pages/ElderView";

function Nav() {
  const { pathname } = useLocation();

  return (
    <nav className="nav">
      <Link className={pathname === "/" ? "nav__on" : ""} to="/">
        Family
      </Link>
      <Link className={pathname === "/elder" ? "nav__on" : ""} to="/elder">
        Elder device
      </Link>
    </nav>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Nav />
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/elder" element={<ElderView />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
