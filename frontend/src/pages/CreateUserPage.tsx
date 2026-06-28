import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  AtSign,
  Check,
  KeyRound,
  Loader2,
  Network,
  ShieldCheck,
  UserPlus,
  Users,
} from "lucide-react";

import { createUser, fetchDomains } from "../api";
import { useAuth } from "../AuthContext";
import type { Domain } from "../types";

type Role = "reader" | "contributor" | "domain_admin";

const roleOptions: Array<{
  value: Role;
  label: string;
  icon: typeof Users;
  description: string;
}> = [
  {
    value: "reader",
    label: "Reader",
    icon: Users,
    description: "Can read and ask questions.",
  },
  {
    value: "contributor",
    label: "Contributor",
    icon: UserPlus,
    description: "Can upload documents.",
  },
  {
    value: "domain_admin",
    label: "Domain Admin",
    icon: ShieldCheck,
    description: "Can manage domain users.",
  },
];

export default function CreateUserPage() {
  const { token, user, hasRole } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("reader");
  const [selectedDomainId, setSelectedDomainId] = useState("");
  const [domains, setDomains] = useState<Domain[]>([]);
  const [isLoadingDomains, setIsLoadingDomains] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const isAdmin = hasRole("admin");
  const isDomainAdmin = hasRole("domain_admin") && !isAdmin;

  const availableRoles = useMemo(() => {
    return roleOptions.filter((option) => isAdmin || option.value !== "domain_admin");
  }, [isAdmin]);

  const selectedDomain = useMemo(
    () => domains.find((domain) => domain.id === selectedDomainId),
    [domains, selectedDomainId],
  );

  useEffect(() => {
    if (!token) return;
    setIsLoadingDomains(true);
    fetchDomains(token)
      .then((items) => {
        setDomains(items);
        if (items.length > 0) setSelectedDomainId(items[0].id);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load domains"))
      .finally(() => setIsLoadingDomains(false));
  }, [token, user, isAdmin, isDomainAdmin]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !selectedDomainId) return;

    setIsSubmitting(true);
    setError("");
    setSuccess("");

    try {
      const newUser = await createUser(token, {
        email,
        password,
        role,
        domain_id: selectedDomainId,
      });
      setSuccess(`${newUser.email} was created.`);
      setEmail("");
      setPassword("");
      setRole("reader");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create user");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="mx-auto grid max-w-6xl gap-6">
      <section className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-normal">Create User</h1>
        </div>
        <div className="hidden h-12 w-12 place-items-center rounded-lg bg-zinc-950 text-white dark:bg-white dark:text-zinc-950 sm:grid">
          <UserPlus size={22} />
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-[minmax(0,1.25fr)_360px]">
        <form className="surface rounded-lg p-6 lg:p-8" onSubmit={handleSubmit}>
          <div className="grid gap-5 md:grid-cols-2">
            <label className="grid gap-2">
              <span className="flex items-center gap-2 text-sm font-medium">
                <AtSign size={16} />
                Email
              </span>
              <input
                className="control h-12"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="off"
                placeholder="name@example.com"
                required
              />
            </label>

            <label className="grid gap-2">
              <span className="flex items-center gap-2 text-sm font-medium">
                <KeyRound size={16} />
                Password
              </span>
              <input
                className="control h-12"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="new-password"
                placeholder="Temporary password"
                required
              />
            </label>
          </div>

          <div className="mt-7 grid gap-3">
            <span className="text-sm font-medium">Role</span>
            <div className="grid gap-3 md:grid-cols-3">
              {availableRoles.map((option) => {
                const Icon = option.icon;
                const active = role === option.value;
                return (
                  <label
                    key={option.value}
                    className={`cursor-pointer rounded-lg border p-4 transition ${
                      active
                        ? "border-zinc-950 bg-zinc-950 text-white dark:border-white dark:bg-white dark:text-zinc-950"
                        : "border-zinc-200 bg-white hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950 dark:hover:bg-zinc-900"
                    }`}
                  >
                    <input
                      className="sr-only"
                      type="radio"
                      name="role"
                      value={option.value}
                      checked={active}
                      onChange={() => setRole(option.value)}
                    />
                    <div className="flex items-start justify-between gap-3">
                      <Icon size={20} />
                      {active ? <Check size={18} /> : null}
                    </div>
                    <p className="mt-4 text-sm font-semibold">{option.label}</p>
                    <p
                      className={`mt-2 text-xs leading-5 ${
                        active ? "text-white/75 dark:text-zinc-700" : "text-zinc-500 dark:text-zinc-400"
                      }`}
                    >
                      {option.description}
                    </p>
                  </label>
                );
              })}
            </div>
          </div>

          <label className="mt-7 grid gap-2">
            <span className="text-sm font-medium">Domain</span>
            {isLoadingDomains ? (
              <div className="control flex h-12 items-center gap-2 text-zinc-500">
                <Loader2 className="animate-spin" size={16} />
                Loading domains
              </div>
            ) : domains.length === 0 ? (
              <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
                No domains available.
              </p>
            ) : (
              <select
                className="control h-12"
                value={selectedDomainId}
                onChange={(event) => setSelectedDomainId(event.target.value)}
                required
              >
                {domains.map((domain) => (
                  <option key={domain.id} value={domain.id}>
                    {domain.name}
                  </option>
                ))}
              </select>
            )}
          </label>

          {error ? (
            <p className="mt-5 rounded-lg border border-red-200 bg-red-50 px-3 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
              {error}
            </p>
          ) : null}

          {success ? (
            <p className="mt-5 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-3 text-sm text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200">
              {success}
            </p>
          ) : null}

          <button
            className="button-primary mt-7 h-12 w-full"
            disabled={isSubmitting || !selectedDomainId || !email || !password}
          >
            {isSubmitting ? (
              <Loader2 className="animate-spin" size={17} />
            ) : (
              <UserPlus size={17} />
            )}
            Create User
          </button>
        </form>

        <aside className="overflow-hidden rounded-lg bg-zinc-950 text-white shadow-soft dark:bg-white dark:text-zinc-950 dark:shadow-dark">
          <div className="relative min-h-full p-6">
            <div className="absolute -right-20 -top-20 h-52 w-52 rounded-full border border-white/10 dark:border-zinc-950/10" />
            <div className="absolute -bottom-24 left-8 h-56 w-56 rounded-full border border-white/10 dark:border-zinc-950/10" />

            <div className="relative">
              <div className="grid h-12 w-12 place-items-center rounded-lg bg-white text-zinc-950 dark:bg-zinc-950 dark:text-white">
                <Network size={22} />
              </div>
              <h2 className="mt-6 text-2xl font-semibold tracking-normal">
                Access profile
              </h2>

              <div className="mt-8 space-y-3">
                <SummaryRow label="Email" value={email || "Not set"} />
                <SummaryRow
                  label="Role"
                  value={roleOptions.find((item) => item.value === role)?.label ?? role}
                />
                <SummaryRow label="Domain" value={selectedDomain?.name ?? "Not selected"} />
              </div>

              <div className="mt-8 rounded-lg border border-white/10 bg-white/5 p-4 dark:border-zinc-950/10 dark:bg-zinc-950/5">
                <p className="text-sm font-semibold">Ready state</p>
                <div className="mt-4 space-y-3 text-sm">
                  <CheckLine complete={Boolean(email)} label="Email entered" />
                  <CheckLine complete={Boolean(password)} label="Password entered" />
                  <CheckLine complete={Boolean(selectedDomainId)} label="Domain selected" />
                </div>
              </div>
            </div>
          </div>
        </aside>
      </section>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/5 p-3 dark:border-zinc-950/10 dark:bg-zinc-950/5">
      <p className="text-xs uppercase tracking-[0.08em] text-white/50 dark:text-zinc-500">
        {label}
      </p>
      <p className="mt-1 truncate text-sm font-medium">{value}</p>
    </div>
  );
}

function CheckLine({ complete, label }: { complete: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <span
        className={`grid h-5 w-5 place-items-center rounded-full ${
          complete
            ? "bg-white text-zinc-950 dark:bg-zinc-950 dark:text-white"
            : "border border-white/25 dark:border-zinc-950/25"
        }`}
      >
        {complete ? <Check size={13} /> : null}
      </span>
      <span className={complete ? "" : "text-white/55 dark:text-zinc-500"}>{label}</span>
    </div>
  );
}
