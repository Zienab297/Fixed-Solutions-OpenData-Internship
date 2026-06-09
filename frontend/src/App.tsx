import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";

import AppShell from "./components/AppShell";
import ChatPage from "./pages/ChatPage";
import LoginPage from "./pages/LoginPage";
import UploadPage from "./pages/UploadPage";
import { tokenStorageKey, userStorageKey } from "./api";
import type { User } from "./types";

type Theme = "light" | "dark";

function readStoredUser(): User | null {
  const value = localStorage.getItem(userStorageKey);
  if (!value) {
    return null;
  }

  try {
    return JSON.parse(value) as User;
  } catch {
    localStorage.removeItem(userStorageKey);
    return null;
  }
}

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem(tokenStorageKey));
  const [user, setUser] = useState<User | null>(() => readStoredUser());
  const [theme, setTheme] = useState<Theme>(() => {
    return (localStorage.getItem("rag_theme") as Theme | null) ?? "light";
  });

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem("rag_theme", theme);
  }, [theme]);

  const auth = useMemo(
    () => ({
      token,
      user,
      signIn: (nextToken: string, nextUser: User) => {
        localStorage.setItem(tokenStorageKey, nextToken);
        localStorage.setItem(userStorageKey, JSON.stringify(nextUser));
        setToken(nextToken);
        setUser(nextUser);
      },
      signOut: () => {
        localStorage.removeItem(tokenStorageKey);
        localStorage.removeItem(userStorageKey);
        setToken(null);
        setUser(null);
      },
    }),
    [token, user],
  );

  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/login"
          element={
            token && user ? (
              <Navigate to="/chat" replace />
            ) : (
              <LoginPage onLogin={auth.signIn} theme={theme} setTheme={setTheme} />
            )
          }
        />
        <Route
          path="/*"
          element={
            token && user ? (
              <AppShell
                user={user}
                theme={theme}
                setTheme={setTheme}
                onLogout={auth.signOut}
              >
                <Routes>
                  <Route path="/" element={<Navigate to="/chat" replace />} />
                  <Route path="/chat" element={<ChatPage token={token} />} />
                  <Route path="/upload" element={<UploadPage token={token} />} />
                  <Route path="*" element={<Navigate to="/chat" replace />} />
                </Routes>
              </AppShell>
            ) : (
              <Navigate to="/login" replace />
            )
          }
        />
      </Routes>
    </BrowserRouter>
  );
}
