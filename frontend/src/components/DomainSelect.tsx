import { Check, ChevronDown, Layers } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { Domain } from "../types";

type Props = {
  domains: Domain[];
  recentDomainIds?: string[];
  selectedDomainId: string;
  manualDomainId: string;
  loading: boolean;
  onSelectDomain: (domainId: string) => void;
  onManualDomain: (domainId: string) => void;
};

export default function DomainSelect({
  domains,
  recentDomainIds = [],
  selectedDomainId,
  manualDomainId,
  loading,
  onSelectDomain,
  onManualDomain,
}: Props) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const domainIds = new Set(domains.map((domain) => domain.id));
  const recentOnly = recentDomainIds.filter((domainId) => !domainIds.has(domainId));
  const isDisabled = loading || (domains.length === 0 && recentOnly.length === 0);

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
    onManualDomain("");
    setIsOpen(false);
  }

  function handleManualDomain(domainId: string) {
    onSelectDomain("");
    onManualDomain(domainId);
  }

  return (
    <div className="grid gap-3 md:grid-cols-[1fr_220px]">
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
                  : domains.length || recentOnly.length
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

              {recentOnly.length ? (
                <div className="border-t border-zinc-100 py-1 dark:border-zinc-800">
                  <p className="px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.08em] text-zinc-400">
                    Recent manual domains
                  </p>
                  {recentOnly.map((domainId) => (
                    <button
                      key={domainId}
                      className="flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left text-sm transition hover:bg-zinc-100 dark:hover:bg-zinc-900"
                      type="button"
                      onClick={() => handleSelect(domainId)}
                    >
                      <span className="truncate font-medium">{domainId}</span>
                      {selectedDomainId === domainId ? (
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

      <label className="grid gap-2">
        <span className="text-xs font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
          Domain ID
        </span>
        <input
          className="control"
          value={manualDomainId}
          onChange={(event) => handleManualDomain(event.target.value)}
          placeholder="manual id"
        />
      </label>
    </div>
  );
}
