import { FormEvent, useEffect, useState } from "react";
import { Loader2, UserPlus } from "lucide-react";

import { createUser, fetchDomains } from "../api";
import { useAuth } from "../AuthContext";
import type { Domain } from "../types";

export default function CreateUserPage() {
  const { token, user, hasRole } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"reader" | "contributor" | "domain_admin">("reader");
  const [selectedDomainId, setSelectedDomainId] = useState("");
  const [domains, setDomains] = useState<Domain[]>([]);
  const [isLoadingDomains, setIsLoadingDomains] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const isAdmin = hasRole("admin");
  const isDomainAdmin = hasRole("domain_admin") && !isAdmin;

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
      setSuccess(`User ${newUser.email} created as ${newUser.role} in the selected domain.`);
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
      <section className="grid gap-2">
        <h1 className="text-3xl font-semibold tracking-normal">Create User</h1>
        <p className="max-w-2xl text-sm leading-6 text-zinc-500 dark:text-zinc-400">
          {isAdmin
            ? "As system admin you can create users in any domain."
            : "As domain admin you can create readers and contributors within your domains."}
        </p>
      </section>

      <section className="surface rounded-lg p-5 max-w-lg">
        <form className="space-y-5" onSubmit={handleSubmit}>
          <label className="grid gap-2">
            <span className="text-sm font-medium">Email</span>
            <input
              className="control"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="off"
              required
            />
          </label>

          <label className="grid gap-2">
            <span className="text-sm font-medium">Password</span>
            <input
              className="control"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              required
            />
          </label>

          <div className="grid gap-2">
            <span className="text-sm font-medium">Role</span>
            <div className="flex gap-4">
              {(isAdmin ? (["reader", "contributor", "domain_admin"] as const) : (["reader", "contributor"] as const)).map((r) => (
                <label key={r} className="flex items-center gap-2 text-sm capitalize cursor-pointer">
                  <input
                    type="radio"
                    name="role"
                    value={r}
                    checked={role === r}
                    onChange={() => setRole(r)}
                  />
                  {r}
                </label>
              ))}
            </div>
          </div>

          <div className="grid gap-2">
            <span className="text-sm font-medium">Domain</span>
            {isLoadingDomains ? (
              <p className="text-sm text-zinc-500">Loading domains…</p>
            ) : domains.length === 0 ? (
              <p className="text-sm text-red-600 dark:text-red-400">
                No domains available.
              </p>
            ) : (
              <select
                className="control"
                value={selectedDomainId}
                onChange={(e) => setSelectedDomainId(e.target.value)}
                required
              >
                {domains.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            )}
          </div>

          {error && (
            <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
              {error}
            </p>
          )}

          {success && (
            <p className="rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700 dark:border-green-900 dark:bg-green-950 dark:text-green-200">
              {success}
            </p>
          )}

          <button
            className="button-primary w-full"
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
      </section>
    </div>
  );
}