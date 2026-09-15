import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { getSession, logout } from "./api";
import type { Session } from "./types";
import AppShell from "./components/AppShell";
import HomePage from "./pages/HomePage";
import KnowledgePage from "./pages/KnowledgePage";
import LoginPage from "./pages/LoginPage";
import ResearchResultPage from "./pages/ResearchResultPage";
import SettingsPage from "./pages/SettingsPage";

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [checking, setChecking] = useState(true);
  const location = useLocation();

  useEffect(() => {
    let active = true;
    getSession()
      .then((value) => active && setSession(value))
      .catch(() => active && setSession(null))
      .finally(() => active && setChecking(false));
    return () => {
      active = false;
    };
  }, []);

  if (checking) {
    return (
      <main className="center-screen" aria-busy="true">
        <div className="brand-mark">DR</div>
        <p>正在连接研究工作台…</p>
      </main>
    );
  }

  if (!session) {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage onLogin={setSession} />} />
        <Route path="*" element={<Navigate to="/login" replace state={{ from: location }} />} />
      </Routes>
    );
  }

  const signOut = async () => {
    await logout();
    setSession(null);
  };

  return (
    <AppShell username={session.username} onLogout={signOut}>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/knowledge" element={<KnowledgePage />} />
        <Route path="/knowledge/:kbId" element={<KnowledgePage />} />
        <Route path="/research/:taskId" element={<ResearchResultPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/login" element={<Navigate to="/" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}
