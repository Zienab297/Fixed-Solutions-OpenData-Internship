import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { useEffect, useState } from "react";

import { AuthProvider, useAuth } from "./AuthContext";
import AppShell from "./components/AppShell";
import ChatPage from "./pages/ChatPage";
import CreateUserPage from "./pages/CreateUserPage";
import LoginPage from "./pages/LoginPage";
import QualityPage from "./pages/QualityPage";
import UploadPage from "./pages/UploadPage";

type Theme = "light" | "dark";

function AppRoutes({ theme, setTheme }: { theme: Theme; setTheme: (t: Theme) => void }) {
  const { token, user, signIn, signOut } = useAuth();

  return (
    <Routes>
      <Route
        path="/login"
        element={
          token && user ? (
            <Navigate to="/chat" replace />
          ) : (
            <LoginPage onLogin={signIn} theme={theme} setTheme={setTheme} />
          )
        }
      />
      <Route
        path="/*"
        element={
          token && user ? (
            <AppShell user={user} theme={theme} setTheme={setTheme} onLogout={signOut}>
              <Routes>
                <Route path="/" element={<Navigate to="/chat" replace />} />
                <Route path="/chat" element={<ChatPage />} />
                <Route path="/upload" element={<UploadPage />} />
                <Route path="/quality" element={<QualityPage />} />
                <Route path="/users/create" element={<CreateUserPage />} />
                <Route path="*" element={<Navigate to="/chat" replace />} />
              </Routes>
            </AppShell>
          ) : (
            <Navigate to="/login" replace />
          )
        }
      />
    </Routes>
  );
}

export default function App() {
  const [theme, setTheme] = useState<Theme>(() => {
    return (localStorage.getItem("rag_theme") as Theme | null) ?? "light";
  });

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    localStorage.setItem("rag_theme", theme);
  }, [theme]);

  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <AuthProvider>
        <AppRoutes theme={theme} setTheme={setTheme} />
      </AuthProvider>
    </BrowserRouter>
  );
}
