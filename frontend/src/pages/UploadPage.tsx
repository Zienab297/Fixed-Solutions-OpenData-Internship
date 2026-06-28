import { ChangeEvent, DragEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  Eye,
  FileSpreadsheet,
  FileText,
  FileType2,
  FileUp,
  Loader2,
  RefreshCw,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";

import {
  createDomain,
  deleteDocument,
  fetchDocumentFileBlob,
  fetchDocuments,
  fetchDomains,
  fetchIngestionJob,
  replaceDocument,
  uploadDocument,
  type RagDocument,
} from "../api";
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

const sourceTypeIcon: Record<string, typeof FileText> = {
  pdf: FileText,
  docx: FileType2,
  csv: FileSpreadsheet,
};

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function UploadPage() {
  const { token, hasRole } = useAuth();
  const [domains, setDomains] = useState<Domain[]>([]);
  const [recentDomainIds, setRecentDomainIds] = useState<string[]>(() =>
    readRecentDomainIds(),
  );
  const [selectedDomainId, setSelectedDomainId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [isDraggingFile, setIsDraggingFile] = useState(false);
  const [job, setJob] = useState<IngestionJob | null>(null);
  const [jobLookupId, setJobLookupId] = useState("");
  const [isLoadingDomains, setIsLoadingDomains] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isLoadingJob, setIsLoadingJob] = useState(false);
  const [error, setError] = useState("");

  // --- Document list (for the selected domain) ---
  const [documents, setDocuments] = useState<RagDocument[]>([]);
  const [isLoadingDocuments, setIsLoadingDocuments] = useState(false);
  const [documentsVersion, setDocumentsVersion] = useState(0);
  const refreshDocuments = () => setDocumentsVersion((v) => v + 1);
  const documentsRequestIdRef = useRef(0);
  const documentsAppliedIdRef = useRef(0);
  const jobRequestIdRef = useRef(0);
  const jobAppliedIdRef = useRef(0);

  // --- Per-row delete / replace state ---
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [replacingId, setReplacingId] = useState<string | null>(null);

  // --- Preview modal state ---
  const [previewDoc, setPreviewDoc] = useState<RagDocument | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewText, setPreviewText] = useState<string | null>(null);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);
  const [previewError, setPreviewError] = useState("");

  // fetchDomains already returns the user's authorized domains.
  const writableDomains = useMemo(() => {
    if (hasRole("contributor")) return domains;
    return [];
  }, [domains, hasRole]);

  const effectiveDomainId = useMemo(() => selectedDomainId, [selectedDomainId]);

  const hasActiveDocuments = useMemo(
    () => documents.some((doc) => !terminalStatuses.has(doc.ingest_status)),
    [documents],
  );

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

  // Load documents whenever the selected domain changes (or a refresh is
  // requested). Multiple triggers can call refreshDocuments() in quick
  // succession (the job-completion refresh and the safety-net poll below),
  // so responses can resolve out of order. We must only discard a response
  // if a NEWER response has already been applied -- not merely because a
  // newer request was issued before this one resolved. Comparing against
  // "last issued" instead of "last applied" causes a livelock under fast
  // polling: every response finds a newer request already in flight by the
  // time it resolves, so nothing is ever applied. documentsAppliedIdRef
  // tracks the highest request id actually applied to state so far.
  useEffect(() => {
    if (!token || !effectiveDomainId) {
      setDocuments([]);
      return;
    }
    const requestId = ++documentsRequestIdRef.current;
    setIsLoadingDocuments(true);
    fetchDocuments(token, effectiveDomainId)
      .then((items) => {
        console.log(
          "FETCH RESOLVED",
          requestId,
          "applied so far:",
          documentsAppliedIdRef.current,
          items.find((d) => d.title.toLowerCase().includes("w-4"))?.ingest_status,
        );
        if (requestId > documentsAppliedIdRef.current) {
          documentsAppliedIdRef.current = requestId;
          console.log("APPLYING", requestId);
          setDocuments(items);
        } else {
          console.log("DISCARDING (stale)", requestId);
        }
      })
      .catch((err) => {
        if (requestId > documentsAppliedIdRef.current) {
          setError(err instanceof Error ? err.message : "Could not load documents");
        }
      })
      .finally(() => {
        if (requestId >= documentsRequestIdRef.current) setIsLoadingDocuments(false);
      });
  }, [token, effectiveDomainId, documentsVersion]);

  // Safety-net poll: as long as anything in the visible list is still
  // pending/processing, keep refreshing the list itself, independent of
  // whether the currently-tracked `job` (right-hand panel) is the one
  // that finishes. Without this, a document ingested via another tab,
  // a page reload mid-processing, or a job the user never directly
  // tracked could finish server-side but never reflect in this list
  // until a manual refresh.
  useEffect(() => {
    if (!token || !effectiveDomainId || !hasActiveDocuments) return;
    const interval = window.setInterval(() => {
      refreshDocuments();
    }, 4000);
    return () => window.clearInterval(interval);
  }, [token, effectiveDomainId, hasActiveDocuments]);

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

  // Poll job status every 2s until terminal. Depends only on job?.id (not
  // the whole `job` object) — `job` itself is reassigned on every tick by
  // setJob below, so depending on it would tear down and recreate this
  // effect (and its interval) on every single poll, which could let two
  // overlapping intervals briefly run at once. jobAppliedIdRef tracks the
  // highest request id actually applied so far; a response is only
  // discarded if a NEWER response has already been applied, not merely
  // because a newer request was issued before this one resolved (comparing
  // against "last issued" instead risks every response finding a newer
  // request already in flight by the time it resolves, so nothing is ever
  // applied).
  useEffect(() => {
    if (!token || !job?.id || terminalStatuses.has(job.status)) return;
    const currentJobId = job.id;

    const interval = window.setInterval(() => {
      const requestId = ++jobRequestIdRef.current;
      fetchIngestionJob(token, currentJobId)
        .then((nextJob) => {
          if (requestId <= jobAppliedIdRef.current) return; // stale response, discard
          jobAppliedIdRef.current = requestId;
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
          );
          if (terminalStatuses.has(nextJob.status)) {
            refreshDocuments();
          }
        })
        .catch((err) => {
          if (requestId <= jobAppliedIdRef.current) return;
          setError(err instanceof Error ? err.message : "Could not update job");
        });
    }, 2000);

    return () => window.clearInterval(interval);
  }, [job?.id, job?.status, token]);

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null);
  }

  function handleDragOver(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setIsDraggingFile(true);
  }

  function handleDragLeave() {
    setIsDraggingFile(false);
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setIsDraggingFile(false);
    const dropped = event.dataTransfer.files?.[0];
    if (dropped) setFile(dropped);
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
      setFile(null);
      refreshDocuments();
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

  async function handleDeleteDocument(doc: RagDocument) {
    if (!token) return;
    if (!window.confirm(`Delete "${doc.title}"? This cannot be undone.`)) return;

    setDeletingId(doc.id);
    setError("");
    try {
      await deleteDocument(token, doc.id);
      refreshDocuments();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete document");
    } finally {
      setDeletingId(null);
    }
  }

  async function handleReplaceFile(doc: RagDocument, event: ChangeEvent<HTMLInputElement>) {
    const newFile = event.target.files?.[0];
    event.target.value = ""; // allow re-selecting the same filename later
    if (!newFile || !token || !effectiveDomainId) return;

    setReplacingId(doc.id);
    setError("");
    try {
      const result = await replaceDocument(token, doc.id, effectiveDomainId, newFile);
      saveLastIngestionJobId(result.id);
      setJob(result);
      refreshDocuments();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not replace document");
    } finally {
      setReplacingId(null);
    }
  }

  async function openPreview(doc: RagDocument) {
    if (!token) return;
    setPreviewDoc(doc);
    setPreviewUrl(null);
    setPreviewText(null);
    setPreviewError("");

    if (!doc.has_file) {
      setPreviewError("No original file was stored for this document.");
      return;
    }

    setIsLoadingPreview(true);
    try {
      const blob = await fetchDocumentFileBlob(token, doc.id);
      if (doc.source_type === "csv") {
        setPreviewText(await blob.text());
      } else {
        setPreviewUrl(URL.createObjectURL(blob));
      }
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : "Could not load preview");
    } finally {
      setIsLoadingPreview(false);
    }
  }

  function closePreview() {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewDoc(null);
    setPreviewUrl(null);
    setPreviewText(null);
    setPreviewError("");
  }

  const canCreateDomain = hasRole("domain_admin");
  const completedCount = documents.filter((d) => d.ingest_status === "completed").length;
  const activeCount = documents.filter((d) => !terminalStatuses.has(d.ingest_status)).length;
  const failedCount = documents.filter((d) => d.ingest_status === "failed").length;

  return (
    <div className="mx-auto grid max-w-6xl gap-7">
      <section className="flex flex-wrap items-baseline justify-between gap-3 border-b border-zinc-200 pb-5 dark:border-zinc-800">
        <div className="grid gap-1.5">
          <h1 className="text-2xl font-semibold tracking-tight">Upload</h1>
          <p className="max-w-2xl text-sm leading-6 text-zinc-500 dark:text-zinc-400">
            Submit PDF, DOCX, or CSV files into the ingestion pipeline. Each
            upload returns a job immediately while the worker extracts,
            chunks, embeds, and indexes in the background.
          </p>
        </div>
        {documents.length > 0 ? (
          <dl className="flex items-center gap-5 text-sm">
            <div className="text-right">
              <dt className="text-xs font-medium uppercase tracking-[0.08em] text-zinc-400">
                Indexed
              </dt>
              <dd className="mt-0.5 font-semibold text-emerald-600 dark:text-emerald-400">
                {completedCount}
              </dd>
            </div>
            {activeCount > 0 ? (
              <div className="text-right">
                <dt className="text-xs font-medium uppercase tracking-[0.08em] text-zinc-400">
                  In progress
                </dt>
                <dd className="mt-0.5 font-semibold text-blue-600 dark:text-blue-400">
                  {activeCount}
                </dd>
              </div>
            ) : null}
            {failedCount > 0 ? (
              <div className="text-right">
                <dt className="text-xs font-medium uppercase tracking-[0.08em] text-zinc-400">
                  Failed
                </dt>
                <dd className="mt-0.5 font-semibold text-red-600 dark:text-red-400">
                  {failedCount}
                </dd>
              </div>
            ) : null}
          </dl>
        ) : null}
      </section>

      <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
        <section className="surface rounded-xl p-6">
          <form className="space-y-5" onSubmit={handleSubmit}>
            <DomainSelect
              domains={writableDomains}
              recentDomainIds={recentDomainIds}
              selectedDomainId={selectedDomainId}
              loading={isLoadingDomains}
              onSelectDomain={setSelectedDomainId}
              onCreateDomain={canCreateDomain ? handleCreateDomain : undefined}
            />

            <label
              className={`grid min-h-56 cursor-pointer place-items-center rounded-xl border-2 border-dashed px-4 py-10 text-center transition-colors ${
                isDraggingFile
                  ? "border-zinc-950 bg-zinc-100 dark:border-white dark:bg-zinc-900"
                  : "border-zinc-300 bg-zinc-50 hover:border-zinc-400 hover:bg-zinc-100 dark:border-zinc-700 dark:bg-zinc-900/60 dark:hover:border-zinc-600 dark:hover:bg-zinc-900"
              }`}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
            >
              <input
                className="sr-only"
                type="file"
                accept={acceptedDocumentTypes}
                onChange={handleFileChange}
              />
              <div>
                <div className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-zinc-950 text-white dark:bg-white dark:text-zinc-950">
                  <UploadCloud size={22} />
                </div>
                <p className="mt-4 text-sm font-semibold">
                  {file ? file.name : "Drop a file here, or click to browse"}
                </p>
                <p className="mt-1.5 text-xs text-zinc-500 dark:text-zinc-400">
                  {file ? `${formatBytes(file.size)} · ready to upload` : "PDF, DOCX, or CSV"}
                </p>
              </div>
            </label>

            {error ? (
              <p className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
                <AlertTriangle size={15} className="mt-0.5 shrink-0" />
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
              {isSubmitting ? "Uploading…" : "Upload document"}
            </button>
          </form>

          {/* Documents already ingested into the selected domain */}
          <div className="mt-8 border-t border-zinc-200 pt-5 dark:border-zinc-800">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold tracking-tight">
                Documents in this domain
                {documents.length > 0 ? (
                  <span className="ml-2 rounded-full bg-zinc-100 px-2 py-0.5 text-xs font-medium text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
                    {documents.length}
                  </span>
                ) : null}
              </h2>
              <button
                type="button"
                className="button-secondary h-8 px-2.5 text-xs"
                onClick={refreshDocuments}
                disabled={!effectiveDomainId || isLoadingDocuments}
                title="Refresh"
              >
                <RefreshCw
                  size={13}
                  className={isLoadingDocuments ? "animate-spin" : ""}
                />
                Refresh
              </button>
            </div>

            {!effectiveDomainId ? (
              <p className="mt-4 rounded-lg border border-dashed border-zinc-200 px-4 py-6 text-center text-sm text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                Select a domain to see its documents.
              </p>
            ) : isLoadingDocuments && documents.length === 0 ? (
              <div className="mt-4 grid place-items-center py-10 text-zinc-400">
                <Loader2 className="animate-spin" size={18} />
              </div>
            ) : documents.length === 0 ? (
              <p className="mt-4 rounded-lg border border-dashed border-zinc-200 px-4 py-6 text-center text-sm text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                No documents yet. Upload a file above to get started.
              </p>
            ) : (
              <ul className="mt-3 divide-y divide-zinc-200 dark:divide-zinc-800">
                {documents.map((doc) => {
                  const Icon = sourceTypeIcon[doc.source_type] ?? FileText;
                  return (
                    <li
                      key={doc.id}
                      className="group flex items-center justify-between gap-3 py-3"
                    >
                      <div className="flex min-w-0 flex-1 items-center gap-3">
                        <div className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-zinc-100 text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
                          <Icon size={16} />
                        </div>
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium">{doc.title}</p>
                          <div className="mt-1 flex items-center gap-2">
                            <StatusBadge status={doc.ingest_status} />
                            <span className="text-xs uppercase tracking-wide text-zinc-400">
                              {doc.source_type}
                            </span>
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-1 opacity-80 transition-opacity group-hover:opacity-100">
                        <button
                          type="button"
                          className="rounded-md p-2 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-white"
                          title="Preview"
                          onClick={() => openPreview(doc)}
                        >
                          <Eye size={16} />
                        </button>

                        <label
                          className="cursor-pointer rounded-md p-2 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-white"
                          title="Replace file"
                        >
                          {replacingId === doc.id ? (
                            <Loader2 className="animate-spin" size={16} />
                          ) : (
                            <UploadCloud size={16} />
                          )}
                          <input
                            type="file"
                            className="sr-only"
                            accept={acceptedDocumentTypes}
                            disabled={replacingId === doc.id}
                            onChange={(event) => handleReplaceFile(doc, event)}
                          />
                        </label>

                        <button
                          type="button"
                          className="rounded-md p-2 text-red-500 hover:bg-red-50 hover:text-red-700 dark:hover:bg-red-950"
                          title="Delete"
                          disabled={deletingId === doc.id}
                          onClick={() => handleDeleteDocument(doc)}
                        >
                          {deletingId === doc.id ? (
                            <Loader2 className="animate-spin" size={16} />
                          ) : (
                            <Trash2 size={16} />
                          )}
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </section>

        <aside className="surface flex flex-col rounded-xl p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold tracking-tight">Job status</p>
              <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                Polling every 2 seconds
              </p>
            </div>
            <div className="grid h-9 w-9 place-items-center rounded-lg bg-zinc-100 text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
              <FileText size={17} />
            </div>
          </div>

          {job ? (
            <div className="mt-6 space-y-5">
              <div className="flex items-center gap-2">
                <StatusBadge status={job.status} />
                {job.status === "completed" ? (
                  <CheckCircle2 size={16} className="text-emerald-500" />
                ) : null}
              </div>
              <dl className="space-y-3 text-sm">
                <div>
                  <dt className="text-xs font-medium uppercase tracking-[0.08em] text-zinc-400">
                    Job ID
                  </dt>
                  <dd className="mt-1 break-all font-mono text-xs text-zinc-600 dark:text-zinc-300">
                    {job.id}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs font-medium uppercase tracking-[0.08em] text-zinc-400">
                    File
                  </dt>
                  <dd className="mt-1">{job.filename}</dd>
                </div>
                <div>
                  <dt className="text-xs font-medium uppercase tracking-[0.08em] text-zinc-400">
                    Domain
                  </dt>
                  <dd className="mt-1 break-all text-zinc-600 dark:text-zinc-300">
                    {job.domain_id ?? "Not available from status endpoint"}
                  </dd>
                </div>
              </dl>
              {job.error_message ? (
                <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
                  <AlertTriangle size={15} className="mt-0.5 shrink-0" />
                  {job.error_message}
                </div>
              ) : null}
            </div>
          ) : (
            <div className="mt-8 rounded-lg border border-dashed border-zinc-200 p-4 text-center text-sm text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
              No active upload job.
            </div>
          )}

          <form className="mt-6 space-y-3 border-t border-zinc-200 pt-5 dark:border-zinc-800" onSubmit={handleLoadJob}>
            <label className="grid gap-2">
              <span className="text-xs font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
                Look up a job
              </span>
              <input
                className="control"
                value={jobLookupId}
                onChange={(event) => setJobLookupId(event.target.value)}
                placeholder="Paste a job ID"
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

      {previewDoc ? (
        <div
          className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4 backdrop-blur-sm"
          onClick={closePreview}
        >
          <div
            className="surface max-h-[85vh] w-full max-w-3xl overflow-auto rounded-xl p-5"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="mb-4 flex items-center justify-between border-b border-zinc-200 pb-3 dark:border-zinc-800">
              <p className="truncate text-sm font-semibold">{previewDoc.title}</p>
              <div className="flex items-center gap-2">
                {previewUrl ? (
                  <a
                    href={previewUrl}
                    download={previewDoc.title}
                    className="rounded-md p-2 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-white"
                    title="Download"
                  >
                    <Download size={16} />
                  </a>
                ) : null}
                <button
                  type="button"
                  className="rounded-md p-2 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-white"
                  onClick={closePreview}
                >
                  <X size={16} />
                </button>
              </div>
            </div>

            {isLoadingPreview ? (
              <div className="grid place-items-center py-16">
                <Loader2 className="animate-spin" size={24} />
              </div>
            ) : previewError ? (
              <p className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
                <AlertTriangle size={15} className="mt-0.5 shrink-0" />
                {previewError}
              </p>
            ) : previewText !== null ? (
              <pre className="max-h-[65vh] overflow-auto whitespace-pre-wrap rounded-lg bg-zinc-50 p-4 text-xs dark:bg-zinc-900">
                {previewText}
              </pre>
            ) : previewDoc.source_type === "pdf" && previewUrl ? (
              <iframe
                src={previewUrl}
                title={previewDoc.title}
                className="h-[65vh] w-full rounded-lg border border-zinc-200 dark:border-zinc-800"
              />
            ) : previewUrl ? (
              <div className="rounded-lg border border-zinc-200 p-6 text-center text-sm text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                Inline preview isn't available for this file type ({previewDoc.source_type}).
                Use the download button above to view it.
              </div>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}