import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { tokenStorageKey, userStorageKey } from "./api";
import type { User } from "./types";

export type Role = "reader" | "contributor" | "domain_admin" | "admin";

export interface AuthContextValue {
  token: string | null;
  user: User | null;
  role: Role | null;
  /** true if the user has at least the given role in the hierarchy */
  hasRole: (min: Role) => boolean;
  signIn: (token: string, user: User) => void;
  signOut: () => void;
}

const ROLE_RANK: Record<Role, number> = {
  reader: 0,
  contributor: 1,
  domain_admin: 2,
  admin: 3,
};

function rankOf(role: string | undefined): number {
  return ROLE_RANK[(role as Role) ?? "reader"] ?? 0;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function readStoredUser(): User | null {
  const value = localStorage.getItem(userStorageKey);
  if (!value) return null;
  try {
    return JSON.parse(value) as User;
  } catch {
    localStorage.removeItem(userStorageKey);
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() =>
    localStorage.getItem(tokenStorageKey),
  );
  const [user, setUser] = useState<User | null>(() => readStoredUser());

  const value = useMemo<AuthContextValue>(
    () => ({
      token,
      user,
      role: (user?.role as Role) ?? null,
      hasRole: (min: Role) => rankOf(user?.role) >= ROLE_RANK[min],
      signIn: (nextToken, nextUser) => {
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

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}