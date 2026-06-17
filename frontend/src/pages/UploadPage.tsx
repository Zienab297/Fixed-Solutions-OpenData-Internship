import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from "react";
import { FileText, FileUp, Loader2, UploadCloud } from "lucide-react";

import { createDomain, fetchDomains, fetchIngestionJob, uploadDocument } from "../api";
import DomainSelect from "../components/DomainSelect";
import StatusBadge from "../components/StatusBadge";
import {
  readLastIngestionJobId,
  readRecentDomainIds,
  rememberDomainId,
  saveLastIngestionJobId,
} from "../storage";
import { useAuth } from "../AuthContext";
import type { Domain, IngestionJob } from "../types";

const acceptedDocumentTypes = [
  ".pdf",
  ".docx",
  ".csv",
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "text/csv",
].join(",");

const terminalStatuses = new Set(["completed", "failed"]);

export default function UploadPage() {
  const { token, user, hasRole } = useAuth();
  const [domains, setDomains] = useState<Domain[]>([]);
  const [recentDomainIds, setRecentDomainIds] = useState<string[]>(() =>
    readRecentDomainIds(),
  );
  const [selectedDomainId, setSelectedDomainId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<IngestionJob | null>(null);
  const [jobLookupId, setJobLookupId] = useState("");
  const [isLoadingDomains, setIsLoadingDomains] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isLoadingJob, setIsLoadingJob] = useState(false);
  const [error, setError] = useState("");

  // admin/contributor see all domains; domain_admin only sees their own; reader sees none
  const writableDomains = useMemo(() => {
    if (hasRole("admin") || hasRole("contributor")) return domains;
    if (hasRole("domain_admin") && user) {
      return domains.filter((d) => d.owner_id === user.id);
    }
    return [];
  }, [domains, user, hasRole]);

  const effectiveDomainId = useMemo(() => selectedDomainId, [selectedDomainId]);

  useEffect(() => {
    if (!token) return;
    let ignore = false;
    setIsLoadingDomains(true);
    fetchDomains(token)
      .then((items) => {
        if (!ignore) setDomains(items);
      })
      .catch((err) => {
        if (!ignore)
          setError(err instanceof Error ? err.message : "Could not load domains");
      })
      .finally(() => {
        if (!ignore) setIsLoadingDomains(false);
      });
    return () => {
      ignore = true;
    };
  }, [token]);

  useEffect(() => {
    if (!token) return;
    const lastJobId = readLastIngestionJobId();
    if (!lastJobId) return;

    fetchIngestionJob(token, lastJobId)
      .then((nextJob) => {
        setJob(nextJob);
        if (nextJob.domain_id) {
          setRecentDomainIds(rememberDomainId(nextJob.domain_id));
        }
      })
      .catch(() => {
        // A missing old job should not block new uploads.
      });
  }, [token]);

  useEffect(() => {
    if (!token || !job || terminalStatuses.has(job.status)) return;

    const interval = window.setInterval(() => {
      fetchIngestionJob(token, job.id)
        .then((nextJob) =>
          setJob((current) =>
            current
              ? {
                  ...current,
                  ...nextJob,
                  domain_id: nextJob.domain_id ?? current.domain_id,
                  filename: nextJob.filename ?? current.filename,
                  created_at: current.created_at,
                }
              : nextJob,
          ),
        )
        .catch((err) => {
          setError(err instanceof Error ? err.message : "Could not update job");
        });
    }, 2000);

    return () => window.clearInterval(interval);
  }, [job, token]);

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || !effectiveDomainId || !token) {
      setError("A supported file and domain are required.");
      return;
    }

    setIsSubmitting(true);
    setError("");
    setJob(null);
    setRecentDomainIds(rememberDomainId(effectiveDomainId));

    try {
      const result = await uploadDocument(token, file, effectiveDomainId);
      saveLastIngestionJobId(result.id);
      setJob(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleLoadJob(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedJobId = jobLookupId.trim();
    if (!trimmedJobId || !token) return;

    setIsLoadingJob(true);
    setError("");

    try {
      const nextJob = await fetchIngestionJob(token, trimmedJobId);
      saveLastIngestionJobId(nextJob.id);
      if (nextJob.domain_id) {
        setRecentDomainIds(rememberDomainId(nextJob.domain_id));
      }
      setJob(nextJob);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load job");
    } finally {
      setIsLoadingJob(false);
    }
  }

  async function handleCreateDomain(name: string) {
    if (!token) return;
    const domain = await createDomain(token, name);
    setDomains((current) => [domain, ...current]);
    setSelectedDomainId(domain.id);
    setRecentDomainIds(rememberDomainId(domain.id));
  }

  // Only admins can create new domains
  const canCreateDomain = hasRole("admin");

  return (
    <div className="mx-auto grid max-w-6xl gap-6">
      <section className="grid gap-2">
        <h1 className="text-3xl font-semibold tracking-normal">Upload</h1>
        <p className="max-w-2xl text-sm leading-6 text-zinc-500 dark:text-zinc-400">
          Submit PDF, DOCX, or CSV files into the ingestion worker. The API
          returns a job ID immediately while the worker extracts, chunks,
          embeds, and indexes.
        </p>
      </section>

      <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
        <section className="surface rounded-lg p-5">
          <form className="space-y-5" onSubmit={handleSubmit}>
            <DomainSelect
              domains={writableDomains}
              recentDomainIds={recentDomainIds}
              selectedDomainId={selectedDomainId}
              loading={isLoadingDomains}
              onSelectDomain={setSelectedDomainId}
              onCreateDomain={canCreateDomain ? handleCreateDomain : undefined}
            />

            <label className="grid min-h-64 cursor-pointer place-items-center rounded-lg border border-dashed border-zinc-300 bg-zinc-50 px-4 py-10 text-center transition hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-900 dark:hover:bg-zinc-800">
              <input
                className="sr-only"
                type="file"
                accept={acceptedDocumentTypes}
                onChange={handleFileChange}
              />
              <div>
                <div className="mx-auto grid h-14 w-14 place-items-center rounded-lg bg-white text-zinc-950 dark:bg-zinc-950 dark:text-white">
                  <UploadCloud size={26} />
                </div>
                <p className="mt-4 font-semibold">
                  {file ? file.name : "Choose a document"}
                </p>
                <p className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">
                  {file ? `${Math.ceil(file.size / 1024)} KB selected` : "PDF, DOCX, or CSV"}
                </p>
              </div>
            </label>

            {error ? (
              <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
                {error}
              </p>
            ) : null}

            <button
              className="button-primary w-full"
              disabled={isSubmitting || !file || !effectiveDomainId}
            >
              {isSubmitting ? (
                <Loader2 className="animate-spin" size={17} />
              ) : (
                <FileUp size={17} />
              )}
              Upload Document
            </button>
          </form>
        </section>

        <aside className="surface rounded-lg p-5">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold">Job Status</p>
              <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                Polling every 2 seconds
              </p>
            </div>
            <FileText size={20} />
          </div>

          {job ? (
            <div className="mt-6 space-y-5">
              <StatusBadge status={job.status} />
              <div className="space-y-3 text-sm">
                <div>
                  <p className="text-xs uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
                    Job ID
                  </p>
                  <p className="mt-1 break-all font-mono text-xs">{job.id}</p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
                    File
                  </p>
                  <p className="mt-1">{job.filename}</p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
                    Domain
                  </p>
                  <p className="mt-1 break-all">
                    {job.domain_id ?? "Not available from status endpoint"}
                  </p>
                </div>
                {job.error_message ? (
                  <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
                    {job.error_message}
                  </div>
                ) : null}
              </div>
            </div>
          ) : (
            <div className="mt-8 rounded-lg border border-zinc-200 p-4 text-sm text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
              No active upload job.
            </div>
          )}

          <form className="mt-5 space-y-3" onSubmit={handleLoadJob}>
            <label className="grid gap-2">
              <span className="text-xs font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
                Load Job ID
              </span>
              <input
                className="control"
                value={jobLookupId}
                onChange={(event) => setJobLookupId(event.target.value)}
                placeholder="paste job id"
              />
            </label>
            <button
              className="button-secondary w-full"
              type="submit"
              disabled={isLoadingJob || !jobLookupId.trim()}
            >
              {isLoadingJob ? <Loader2 className="animate-spin" size={17} /> : null}
              Load status
            </button>
          </form>
        </aside>
      </div>
    </div>
  );
}