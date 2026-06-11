import { Check, ChevronDown, Layers, Loader2, Plus } from "lucide-react";
import { KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";

import type { Domain } from "../types";

type Props = {
  domains: Domain[];
  recentDomainIds?: string[];
  selectedDomainId: string;
  loading: boolean;
  onSelectDomain: (domainId: string) => void;
  onCreateDomain?: (name: string) => Promise<void>;
};

export default function DomainSelect({
  domains,
  selectedDomainId,
  loading,
  onSelectDomain,
  onCreateDomain,
}: Props) {
  const [isOpen, setIsOpen] = useState(false);
  const [newDomainName, setNewDomainName] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState("");
  const dropdownRef = useRef<HTMLDivElement>(null);
  const isDisabled = loading || domains.length === 0;

  const selectedLabel = useMemo(() => {
    if (!selectedDomainId) {
      return "";
    }

    const domain = domains.find((item) => item.id === selectedDomainId);
    return domain?.name ?? selectedDomainId;
  }, [domains, selectedDomainId]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node)
      ) {
        setIsOpen(false);
      }
    }

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  function handleSelect(domainId: string) {
    onSelectDomain(domainId);
    setIsOpen(false);
  }

  async function handleCreateDomain() {
    if (!onCreateDomain || !newDomainName.trim()) {
      return;
    }

    setIsCreating(true);
    setCreateError("");
    try {
      await onCreateDomain(newDomainName.trim());
      setNewDomainName("");
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Could not create domain");
    } finally {
      setIsCreating(false);
    }
  }

  function handleCreateKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      void handleCreateDomain();
    }
  }

  return (
    <div className="grid gap-3">
      <div className="grid gap-2" ref={dropdownRef}>
        <span className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
          <Layers size={14} />
          Domain
        </span>
        <div className="relative">
          <button
            className="control flex w-full items-center justify-between gap-3 text-left disabled:cursor-not-allowed disabled:opacity-60"
            type="button"
            disabled={isDisabled}
            onClick={() => setIsOpen((current) => !current)}
          >
            <span className={selectedLabel ? "truncate" : "truncate text-zinc-400"}>
              {selectedLabel ||
                (loading
                  ? "Loading domains"
                  : domains.length
                    ? "Select a domain"
                    : "No domains found")}
            </span>
            <ChevronDown
              className={`shrink-0 transition ${isOpen ? "rotate-180" : ""}`}
              size={17}
            />
          </button>

          {isOpen ? (
            <div className="absolute left-0 right-0 top-[calc(100%+8px)] z-30 overflow-hidden rounded-lg border border-zinc-200 bg-white shadow-soft dark:border-zinc-800 dark:bg-zinc-950 dark:shadow-dark">
              <button
                className="flex w-full items-center justify-between px-3 py-2.5 text-left text-sm text-zinc-500 transition hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-900"
                type="button"
                onClick={() => handleSelect("")}
              >
                Select a domain
                {!selectedDomainId ? <Check size={16} /> : null}
              </button>

              {domains.length ? (
                <div className="border-t border-zinc-100 py-1 dark:border-zinc-800">
                  <p className="px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.08em] text-zinc-400">
                    Domains
                  </p>
                  {domains.map((domain) => (
                    <button
                      key={domain.id}
                      className="flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left text-sm transition hover:bg-zinc-100 dark:hover:bg-zinc-900"
                      type="button"
                      onClick={() => handleSelect(domain.id)}
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-medium">
                          {domain.name}
                        </span>
                        <span className="block truncate text-xs text-zinc-500 dark:text-zinc-400">
                          {domain.id}
                        </span>
                      </span>
                      {selectedDomainId === domain.id ? (
                        <Check className="shrink-0" size={16} />
                      ) : null}
                    </button>
                  ))}
                </div>
              ) : null}

            </div>
          ) : null}
        </div>
      </div>

      {onCreateDomain ? (
        <div className="grid gap-2">
          <span className="text-xs font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
            New Domain
          </span>
          <div className="flex gap-2">
            <input
              className="control min-w-0 flex-1"
              value={newDomainName}
              onChange={(event) => setNewDomainName(event.target.value)}
              onKeyDown={handleCreateKeyDown}
              placeholder="cs-book"
            />
            <button
              className="button-secondary shrink-0"
              type="button"
              onClick={() => void handleCreateDomain()}
              disabled={isCreating || !newDomainName.trim()}
            >
              {isCreating ? <Loader2 className="animate-spin" size={17} /> : <Plus size={17} />}
              Create
            </button>
          </div>
          {createError ? (
            <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
              {createError}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
