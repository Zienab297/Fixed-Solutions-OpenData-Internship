import {
  BarChart3,
  Database,
  FileUp,
  LogOut,
  MessageSquareText,
  Network,
  UserPlus,
} from "lucide-react";
import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

import ThemeToggle from "./ThemeToggle";
import { useAuth } from "../AuthContext";
import type { User } from "../types";

type Props = {
  children: ReactNode;
  user: User;
  theme: "light" | "dark";
  setTheme: (theme: "light" | "dark") => void;
  onLogout: () => void;
};

export default function AppShell({
  children,
  user,
  theme,
  setTheme,
  onLogout,
}: Props) {
  const { hasRole } = useAuth();

  return (
    <div className="min-h-screen bg-white text-zinc-950 dark:bg-zinc-950 dark:text-white">
      <div className="flex min-h-screen">
        <aside className="hidden w-72 border-r border-zinc-200 bg-zinc-50/80 px-5 py-5 dark:border-zinc-800 dark:bg-black/40 lg:flex lg:flex-col">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-lg bg-zinc-950 text-white dark:bg-white dark:text-zinc-950">
              <Network size={20} />
            </div>
            <div>
              <p className="text-sm font-semibold">RAG Workspace</p>
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                Sprint 1 console
              </p>
            </div>
          </div>

          <nav className="mt-8 space-y-1">
            {/* Chat — visible to all roles */}
            <NavLink
              to="/chat"
              className={({ isActive }) =>
                `nav-link ${isActive ? "nav-link-active" : ""}`
              }
            >
              <MessageSquareText size={18} />
              Chat
            </NavLink>

            {/* Upload — hidden from readers */}
            {hasRole("contributor") && (
              <NavLink
                to="/upload"
                className={({ isActive }) =>
                  `nav-link ${isActive ? "nav-link-active" : ""}`
                }
              >
                <FileUp size={18} />
                Upload
              </NavLink>
            )}

            {/* Quality — admin and domain_admin only */}
            {hasRole("domain_admin") && (
              <NavLink
                to="/quality"
                className={({ isActive }) =>
                  `nav-link ${isActive ? "nav-link-active" : ""}`
                }
              >
                <BarChart3 size={18} />
                Quality
              </NavLink>
            )}

            {/* Create User — admin and domain_admin only */}
            {hasRole("domain_admin") && (
              <NavLink
                to="/users/create"
                className={({ isActive }) =>
                  `nav-link ${isActive ? "nav-link-active" : ""}`
                }
              >
                <UserPlus size={18} />
                Create User
              </NavLink>
            )}
          </nav>

          <div className="mt-auto space-y-4">
            <div className="rounded-lg border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-950">
              <div className="flex items-center gap-3">
                <div className="grid h-9 w-9 place-items-center rounded-lg bg-zinc-100 dark:bg-zinc-900">
                  <Database size={17} />
                </div>
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{user.email}</p>
                  <p className="text-xs capitalize text-zinc-500 dark:text-zinc-400">
                    {user.role}
                  </p>
                </div>
              </div>
            </div>
            <button
              className="button-secondary w-full"
              type="button"
              onClick={onLogout}
            >
              <LogOut size={17} />
              Logout
            </button>
          </div>
        </aside>

        <main className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-16 items-center justify-between border-b border-zinc-200 px-4 dark:border-zinc-800 lg:px-8">
            <div className="flex items-center gap-3 lg:hidden">
              <div className="grid h-9 w-9 place-items-center rounded-lg bg-zinc-950 text-white dark:bg-white dark:text-zinc-950">
                <Network size={18} />
              </div>
              <span className="text-sm font-semibold">RAG Workspace</span>
            </div>
            <div className="hidden text-sm text-zinc-500 dark:text-zinc-400 lg:block">
              Multi-domain retrieval, ingestion, and generation
            </div>
            <ThemeToggle theme={theme} setTheme={setTheme} />
          </header>

          <div className="flex-1 px-4 py-6 lg:px-8">{children}</div>
        </main>
      </div>
    </div>
  );
}
