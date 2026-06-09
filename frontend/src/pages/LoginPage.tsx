import { ArrowRight, LockKeyhole, Moon, Sun } from "lucide-react";
import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import { login } from "../api";
import type { User } from "../types";

type Props = {
  onLogin: (token: string, user: User) => void;
  theme: "light" | "dark";
  setTheme: (theme: "light" | "dark") => void;
};

export default function LoginPage({ onLogin, theme, setTheme }: Props) {
  const navigate = useNavigate();
  const [email, setEmail] = useState("admin@example.com");
  const [password, setPassword] = useState("sprint1");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const isDark = theme === "dark";

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSubmitting(true);
    setError("");

    try {
      const result = await login(email, password);
      onLogin(result.access_token, result.user);
      navigate("/chat");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen bg-white text-zinc-950 dark:bg-zinc-950 dark:text-white">
      <div className="mx-auto grid min-h-screen w-full max-w-6xl items-center gap-10 px-5 py-8 lg:grid-cols-[1fr_430px]">
        <section className="hidden lg:block">
          <div className="max-w-xl">
            <div className="grid h-14 w-14 place-items-center rounded-lg bg-zinc-950 text-white dark:bg-white dark:text-zinc-950">
              <LockKeyhole size={26} />
            </div>
            <h1 className="mt-8 text-5xl font-semibold leading-tight tracking-normal">
              Secure access for domain-aware RAG workflows.
            </h1>
            <p className="mt-5 text-lg leading-8 text-zinc-600 dark:text-zinc-300">
              Sign in once, upload source PDFs, and ask questions inside the
              selected knowledge domain.
            </p>
            <div className="mt-10 grid grid-cols-3 gap-3 text-sm">
              {["Auth", "Chat", "Ingest"].map((item) => (
                <div
                  key={item}
                  className="rounded-lg border border-zinc-200 px-4 py-3 dark:border-zinc-800"
                >
                  <p className="font-semibold">{item}</p>
                  <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                    Sprint 1
                  </p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="surface rounded-lg p-6">
          <div className="mb-8 flex items-center justify-between">
            <div>
              <p className="text-xl font-semibold">RAG Workspace</p>
              <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
                Login
              </p>
            </div>
            <button
              className="button-secondary h-10 px-3"
              type="button"
              onClick={() => setTheme(isDark ? "light" : "dark")}
              title={isDark ? "Use light theme" : "Use dark theme"}
            >
              {isDark ? <Sun size={17} /> : <Moon size={17} />}
            </button>
          </div>

          <form className="space-y-4" onSubmit={handleSubmit}>
            <label className="grid gap-2">
              <span className="text-sm font-medium">Email</span>
              <input
                className="control"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="email"
                required
              />
            </label>

            <label className="grid gap-2">
              <span className="text-sm font-medium">Password</span>
              <input
                className="control"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                required
              />
            </label>

            {error ? (
              <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
                {error}
              </p>
            ) : null}

            <button className="button-primary w-full" disabled={isSubmitting}>
              {isSubmitting ? "Signing in" : "Sign in"}
              <ArrowRight size={17} />
            </button>
          </form>
        </section>
      </div>
    </div>
  );
}
