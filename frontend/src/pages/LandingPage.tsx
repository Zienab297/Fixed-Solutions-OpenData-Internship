import { ArrowRight, Database, LockKeyhole, Network, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";

import ThemeToggle from "../components/ThemeToggle";

type Props = {
  isAuthenticated: boolean;
  theme: "light" | "dark";
  setTheme: (theme: "light" | "dark") => void;
};

const platformNotes = [
  { icon: <Database size={18} />, label: "Domain knowledge" },
  { icon: <ShieldCheck size={18} />, label: "Quality review" },
  { icon: <LockKeyhole size={18} />, label: "Controlled access" },
];

export default function LandingPage({ isAuthenticated, theme, setTheme }: Props) {
  return (
    <main className="min-h-screen overflow-hidden bg-white text-zinc-950 dark:bg-zinc-950 dark:text-white">
      <section className="relative isolate min-h-[92vh] overflow-hidden border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-black">
        <div className="absolute inset-0 -z-20 bg-[radial-gradient(circle_at_72%_42%,rgba(255,255,255,0.85),rgba(255,255,255,0)_30%),linear-gradient(115deg,#050505_0%,#0b0b0c_42%,#ffffff_42%,#ffffff_100%)] dark:bg-[radial-gradient(circle_at_72%_42%,rgba(255,255,255,0.18),rgba(255,255,255,0)_31%),linear-gradient(115deg,#000_0%,#09090b_46%,#171717_100%)]" />
        <img
          src="/assets/landing-hero-rag.png"
          alt=""
          className="landing-hero-object pointer-events-none absolute -right-28 top-24 -z-10 w-[760px] max-w-none opacity-95 mix-blend-multiply dark:mix-blend-screen sm:-right-20 lg:right-0 lg:top-16 lg:w-[880px]"
        />
        <div className="absolute inset-x-0 bottom-0 -z-10 h-40 bg-gradient-to-t from-white via-white/80 to-transparent dark:from-black dark:via-black/80" />

        <header className="mx-auto flex w-full max-w-[1680px] items-center justify-between px-5 py-5 lg:px-12 2xl:px-16">
          <Link className="flex items-center gap-3" to="/">
            <span className="grid h-11 w-11 place-items-center overflow-hidden rounded-lg border border-zinc-200 bg-white dark:border-zinc-700">
              <img
                src="/assets/rag-logo-mark.png"
                alt="RAG Workspace"
                className="h-full w-full object-cover"
              />
            </span>
            <span className="text-sm font-semibold text-white">RAG Workspace</span>
          </Link>

          <div className="flex items-center gap-3">
            <ThemeToggle theme={theme} setTheme={setTheme} />
            <Link className="button-primary" to={isAuthenticated ? "/chat" : "/login"}>
              {isAuthenticated ? "Open Workspace" : "Sign in"}
              <ArrowRight size={17} />
            </Link>
          </div>
        </header>

        <div className="mx-auto grid max-w-7xl gap-12 px-5 pb-14 pt-16 lg:grid-cols-[minmax(0,0.9fr)_minmax(440px,1fr)] lg:px-8 lg:pb-20 lg:pt-28">
          <div className="landing-hero-copy max-w-3xl text-white">
            <h1 className="text-4xl font-semibold leading-[1.02] tracking-normal sm:text-6xl lg:text-7xl">
              RAG Workspace
            </h1>
            <p className="mt-6 max-w-xl text-lg leading-8 text-zinc-300">
              A crisp command center for document intelligence, domain-aware answers,
              evaluation, and review.
            </p>
            <div className="mt-9 flex flex-col gap-3 sm:flex-row">
              <Link className="button-primary h-12 px-6" to={isAuthenticated ? "/chat" : "/login"}>
                {isAuthenticated ? "Open Workspace" : "Sign in"}
                <ArrowRight size={18} />
              </Link>
              <a className="button-secondary h-12 px-6" href="#platform">
                View Platform
              </a>
            </div>
          </div>

          <div className="hidden lg:block" aria-hidden="true" />
        </div>

        <div className="mx-auto grid max-w-7xl gap-3 px-5 pb-8 lg:grid-cols-3 lg:px-8">
          {platformNotes.map((item) => (
            <div
              key={item.label}
              className="flex items-center gap-3 rounded-lg border border-zinc-200 bg-white/85 px-4 py-3 text-sm font-medium shadow-sm backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/75"
            >
              <span className="grid h-9 w-9 place-items-center rounded-lg bg-zinc-950 text-white dark:bg-white dark:text-zinc-950">
                {item.icon}
              </span>
              {item.label}
            </div>
          ))}
        </div>
      </section>

      <section id="platform" className="bg-white px-5 py-16 dark:bg-zinc-950 lg:px-8">
        <div className="mx-auto grid max-w-7xl gap-4 lg:grid-cols-[0.8fr_1fr] lg:items-end">
          <div>
            <div className="grid h-12 w-12 place-items-center rounded-lg bg-zinc-950 text-white dark:bg-white dark:text-zinc-950">
              <Network size={22} />
            </div>
            <h2 className="mt-6 text-3xl font-semibold tracking-normal">
              Built for controlled knowledge work.
            </h2>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            {[
              ["Chat", "Ask inside selected domains."],
              ["Upload", "Add documents to the workspace."],
              ["Quality", "Review judge scores and flagged answers."],
            ].map(([title, text]) => (
              <div
                key={title}
                className="rounded-lg border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-900"
              >
                <p className="font-semibold">{title}</p>
                <p className="mt-2 text-sm leading-6 text-zinc-500 dark:text-zinc-400">{text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}
