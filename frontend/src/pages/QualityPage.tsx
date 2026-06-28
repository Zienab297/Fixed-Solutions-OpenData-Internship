import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  ArrowLeft,
  BarChart3,
  Check,
  Clock3,
  FileText,
  History,
  Loader2,
  RefreshCw,
  ShieldAlert,
  Trash2,
  X,
} from "lucide-react";

import {
  deleteDomainDocument,
  fetchModerationItems,
  fetchQualityDomainDetail,
  fetchQualitySummary,
  updateModerationItem,
} from "../api";
import { useAuth } from "../AuthContext";
import type {
  DomainDocument,
  DomainHistoryItem,
  EvaluationScores,
  ModerationItem,
  QualityDomainDetail,
  QualityDomainSummary,
} from "../types";

type DetailTab = "history" | "files" | "flagged";

const scoreLabels = [
  ["faithfulness", "Faithfulness"],
  ["relevance", "Relevance"],
  ["completeness", "Completeness"],
  ["citation_accuracy", "Citations"],
] as const;

const detailTabs: Array<{ key: DetailTab; label: string }> = [
  { key: "history", label: "History" },
  { key: "files", label: "Files" },
  { key: "flagged", label: "Flagged" },
];

export default function QualityPage() {
  const { token } = useAuth();
  const [summaries, setSummaries] = useState<QualityDomainSummary[]>([]);
  const [moderationItems, setModerationItems] = useState<ModerationItem[]>([]);
  const [statusFilter, setStatusFilter] =
    useState<"pending" | "accepted" | "rejected" | "all">("pending");
  const [selectedDomainId, setSelectedDomainId] = useState("");
  const [detail, setDetail] = useState<QualityDomainDetail | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>("history");
  const [isLoading, setIsLoading] = useState(true);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [isUpdatingId, setIsUpdatingId] = useState("");
  const [isDeletingDocumentId, setIsDeletingDocumentId] = useState("");
  const [error, setError] = useState("");

  const totals = useMemo(() => {
    const evaluationCount = summaries.reduce(
      (sum, item) => sum + item.evaluation_count,
      0,
    );
    const flaggedCount = summaries.reduce((sum, item) => sum + item.flagged_count, 0);
    return { evaluationCount, flaggedCount };
  }, [summaries]);

  async function loadQuality() {
    if (!token) return;
    setIsLoading(true);
    setError("");
    try {
      const [quality, moderation] = await Promise.all([
        fetchQualitySummary(token),
        fetchModerationItems(token, statusFilter),
      ]);
      setSummaries(quality.domains);
      setModerationItems(moderation.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load quality data");
    } finally {
      setIsLoading(false);
    }
  }

  async function loadDomainDetail(domainId: string) {
    if (!token) return;
    setSelectedDomainId(domainId);
    setIsDetailLoading(true);
    setError("");
    try {
      const nextDetail = await fetchQualityDomainDetail(token, domainId);
      setDetail(nextDetail);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load domain detail");
    } finally {
      setIsDetailLoading(false);
    }
  }

  useEffect(() => {
    void loadQuality();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, statusFilter]);

  async function handleModerationUpdate(
    itemId: string,
    nextStatus: "accepted" | "rejected",
  ) {
    if (!token) return;
    setIsUpdatingId(itemId);
    setError("");
    try {
      await updateModerationItem(token, itemId, nextStatus);
      await loadQuality();
      if (selectedDomainId) {
        await loadDomainDetail(selectedDomainId);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update moderation item");
    } finally {
      setIsUpdatingId("");
    }
  }

  async function handleDeleteDocument(document: DomainDocument) {
    if (!token || !selectedDomainId) return;
    const confirmed = window.confirm(
      `Delete "${document.title}" and remove its embedded chunks from this domain?`,
    );
    if (!confirmed) return;

    setIsDeletingDocumentId(document.id);
    setError("");
    try {
      await deleteDomainDocument(token, selectedDomainId, document.id);
      await loadDomainDetail(selectedDomainId);
      await loadQuality();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete document");
    } finally {
      setIsDeletingDocumentId("");
    }
  }

  if (selectedDomainId) {
    return (
      <DomainDetailView
        detail={detail}
        detailTab={detailTab}
        error={error}
        isDetailLoading={isDetailLoading}
        isDeletingDocumentId={isDeletingDocumentId}
        isUpdatingId={isUpdatingId}
        onBack={() => {
          setSelectedDomainId("");
          setDetail(null);
          setDetailTab("history");
        }}
        onDeleteDocument={(document) => void handleDeleteDocument(document)}
        onRefresh={() => void loadDomainDetail(selectedDomainId)}
        onSetDetailTab={setDetailTab}
        onModerationUpdate={(itemId, status) =>
          void handleModerationUpdate(itemId, status)
        }
      />
    );
  }

  return (
    <div className="mx-auto grid max-w-6xl gap-6">
      <section className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="grid gap-2">
          <h1 className="text-3xl font-semibold tracking-normal">Quality</h1>
        </div>
        <button
          className="button-secondary"
          type="button"
          onClick={() => void loadQuality()}
          disabled={isLoading}
        >
          {isLoading ? <Loader2 className="animate-spin" size={17} /> : <RefreshCw size={17} />}
          Refresh
        </button>
      </section>

      <ErrorBanner error={error} />

      <section className="grid gap-4 md:grid-cols-3">
        <MetricBlock
          icon={<BarChart3 size={18} />}
          label="Evaluations"
          value={String(totals.evaluationCount)}
        />
        <MetricBlock
          icon={<ShieldAlert size={18} />}
          label="Flagged"
          value={String(totals.flaggedCount)}
        />
        <MetricBlock
          icon={<Clock3 size={18} />}
          label="Pending Review"
          value={String(moderationItems.filter((item) => item.status === "pending").length)}
        />
      </section>

      <section className="surface rounded-lg p-5">
        <div>
          <h2 className="text-lg font-semibold">Domain Scores</h2>
        </div>

        {isLoading ? (
          <LoadingState />
        ) : summaries.length ? (
          <div className="mt-5 grid gap-4 lg:grid-cols-2">
            {summaries.map((summary) => (
              <DomainScoreCard
                key={summary.domain_id}
                summary={summary}
                onShowDetail={() => void loadDomainDetail(summary.domain_id)}
              />
            ))}
          </div>
        ) : (
          <EmptyState text="No domains available for quality review." />
        )}
      </section>

      <section className="surface rounded-lg p-5">
        <ModerationHeader
          statusFilter={statusFilter}
          onStatusFilterChange={setStatusFilter}
        />

        {isLoading ? (
          <LoadingState />
        ) : moderationItems.length ? (
          <div className="mt-5 space-y-3">
            {moderationItems.map((item) => (
              <ModerationCard
                key={item.id}
                item={item}
                isUpdating={isUpdatingId === item.id}
                onModerationUpdate={(status) =>
                  void handleModerationUpdate(item.id, status)
                }
              />
            ))}
          </div>
        ) : (
          <EmptyState text="No moderation items match this filter." />
        )}
      </section>
    </div>
  );
}

function DomainDetailView({
  detail,
  detailTab,
  error,
  isDetailLoading,
  isDeletingDocumentId,
  isUpdatingId,
  onBack,
  onDeleteDocument,
  onRefresh,
  onSetDetailTab,
  onModerationUpdate,
}: {
  detail: QualityDomainDetail | null;
  detailTab: DetailTab;
  error: string;
  isDetailLoading: boolean;
  isDeletingDocumentId: string;
  isUpdatingId: string;
  onBack: () => void;
  onDeleteDocument: (document: DomainDocument) => void;
  onRefresh: () => void;
  onSetDetailTab: (tab: DetailTab) => void;
  onModerationUpdate: (itemId: string, status: "accepted" | "rejected") => void;
}) {
  return (
    <div className="mx-auto grid max-w-6xl gap-6">
      <section className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <button className="button-secondary h-10 px-3" type="button" onClick={onBack}>
            <ArrowLeft size={16} />
            Back
          </button>
          <div>
            <h1 className="text-2xl font-semibold tracking-normal">
              {detail?.domain.name ?? "Domain"}
            </h1>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
              Query history, embedded files, and flagged recommendations.
            </p>
          </div>
        </div>
        <button
          className="button-secondary"
          type="button"
          onClick={onRefresh}
          disabled={isDetailLoading}
        >
          {isDetailLoading ? <Loader2 className="animate-spin" size={17} /> : <RefreshCw size={17} />}
          Refresh
        </button>
      </section>

      <ErrorBanner error={error} />

      <div className="border-b border-zinc-200 dark:border-zinc-800">
        <div className="flex gap-6 overflow-x-auto">
          {detailTabs.map((tab) => (
            <button
              key={tab.key}
              className={`border-b-2 px-1 pb-3 text-sm font-semibold transition ${
                detailTab === tab.key
                  ? "border-blue-600 text-blue-600 dark:border-blue-400 dark:text-blue-300"
                  : "border-transparent text-zinc-600 hover:text-zinc-950 dark:text-zinc-400 dark:hover:text-white"
              }`}
              type="button"
              onClick={() => onSetDetailTab(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {isDetailLoading && !detail ? (
        <LoadingState />
      ) : detailTab === "history" ? (
        <HistoryTab items={detail?.history ?? []} />
      ) : detailTab === "files" ? (
        <FilesTab
          documents={detail?.documents ?? []}
          isDeletingDocumentId={isDeletingDocumentId}
          onDeleteDocument={onDeleteDocument}
        />
      ) : (
        <FlaggedTab
          items={detail?.flagged ?? []}
          isUpdatingId={isUpdatingId}
          onModerationUpdate={onModerationUpdate}
        />
      )}
    </div>
  );
}

function DomainScoreCard({
  summary,
  onShowDetail,
}: {
  summary: QualityDomainSummary;
  onShowDetail: () => void;
}) {
  return (
    <article className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold">{summary.domain_name}</h3>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            {summary.evaluation_count} evaluations - {summary.flagged_count} flagged
          </p>
        </div>
        <ScorePill score={averageScore(summary.scores)} />
      </div>
      <ScoreGrid scores={summary.scores} />
      {summary.route_breakdown.length ? (
        <div className="mt-4 space-y-2">
          {summary.route_breakdown.map((route) => (
            <div
              key={`${summary.domain_id}-${route.llm_route}`}
              className="flex items-center justify-between rounded-lg bg-zinc-50 px-3 py-2 text-xs dark:bg-zinc-900"
            >
              <span className="font-medium uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
                {route.llm_route}
              </span>
              <span>
                {route.evaluation_count} - {formatScore(averageScore(route.scores))}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <div className="mt-4 rounded-lg bg-zinc-50 px-3 py-2 text-xs text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
          No evaluated answers yet
        </div>
      )}
      <button className="button-secondary mt-4 h-9 w-full" type="button" onClick={onShowDetail}>
        Show detail
      </button>
    </article>
  );
}

function HistoryTab({ items }: { items: DomainHistoryItem[] }) {
  if (!items.length) {
    return <EmptyState text="No query history has been saved for this domain yet." />;
  }

  return (
    <section className="surface rounded-lg p-5">
      <div className="flex items-center gap-2">
        <History size={18} />
        <h2 className="text-lg font-semibold">History</h2>
      </div>
      <div className="mt-5 space-y-4">
        {items.map((item) => (
          <article
            key={item.audit_log_id}
            className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800"
          >
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0">
                <p className="text-xs uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
                  {formatDate(item.asked_at)} - {item.llm_route ?? "unknown"} route
                </p>
                <h3 className="mt-2 text-sm font-semibold">Question</h3>
                <p className="mt-1 whitespace-pre-wrap text-sm leading-6">
                  {item.question || "Question text was not stored for this older query."}
                </p>
              </div>
              <StatusPill status={item.status} flagged={item.evaluation?.flagged ?? false} />
            </div>
            <div className="mt-4 rounded-lg bg-zinc-50 p-3 text-sm leading-6 dark:bg-zinc-900">
              <p className="font-semibold">Answer</p>
              <p className="mt-1 whitespace-pre-wrap">
                {item.answer || "Answer text was not stored for this older query."}
              </p>
            </div>
            {item.evaluation ? (
              <ScoreGrid scores={item.evaluation} />
            ) : (
              <div className="mt-4 inline-flex items-center gap-2 rounded-lg border border-zinc-200 px-2.5 py-1.5 text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                <Loader2 className="animate-spin" size={14} />
                Judge pending
              </div>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

function FilesTab({
  documents,
  isDeletingDocumentId,
  onDeleteDocument,
}: {
  documents: DomainDocument[];
  isDeletingDocumentId: string;
  onDeleteDocument: (document: DomainDocument) => void;
}) {
  if (!documents.length) {
    return <EmptyState text="No files are embedded in this domain yet." />;
  }

  return (
    <section className="surface rounded-lg p-5">
      <div className="flex items-center gap-2">
        <FileText size={18} />
        <h2 className="text-lg font-semibold">Files</h2>
      </div>
      <div className="mt-5 overflow-hidden rounded-lg border border-zinc-200 dark:border-zinc-800">
        <div className="grid grid-cols-[1.5fr_0.7fr_0.7fr_0.7fr_auto] gap-3 border-b border-zinc-200 bg-zinc-50 px-4 py-3 text-xs font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400">
          <span>File</span>
          <span>Type</span>
          <span>Status</span>
          <span>Chunks</span>
          <span className="text-right">Action</span>
        </div>
        {documents.map((document) => (
          <div
            key={document.id}
            className="grid grid-cols-[1.5fr_0.7fr_0.7fr_0.7fr_auto] items-center gap-3 border-b border-zinc-200 px-4 py-3 last:border-b-0 dark:border-zinc-800"
          >
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">{document.title}</p>
              <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                Uploaded {formatDate(document.created_at)}
              </p>
            </div>
            <span className="text-sm uppercase">{document.source_type}</span>
            <StatusPill status={document.ingest_status} />
            <span className="text-sm">{document.chunk_count}</span>
            <button
              className="button-secondary h-9 px-3 text-red-600 hover:text-red-700 dark:text-red-300"
              type="button"
              disabled={isDeletingDocumentId === document.id}
              onClick={() => onDeleteDocument(document)}
            >
              {isDeletingDocumentId === document.id ? (
                <Loader2 className="animate-spin" size={15} />
              ) : (
                <Trash2 size={15} />
              )}
              Delete
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}

function FlaggedTab({
  items,
  isUpdatingId,
  onModerationUpdate,
}: {
  items: ModerationItem[];
  isUpdatingId: string;
  onModerationUpdate: (itemId: string, status: "accepted" | "rejected") => void;
}) {
  if (!items.length) {
    return <EmptyState text="No flagged responses for this domain." />;
  }

  return (
    <section className="surface rounded-lg p-5">
      <div className="flex items-center gap-2">
        <ShieldAlert size={18} />
        <h2 className="text-lg font-semibold">Flagged</h2>
      </div>
      <div className="mt-5 space-y-3">
        {items.map((item) => (
          <ModerationCard
            key={item.id}
            item={item}
            isUpdating={isUpdatingId === item.id}
            onModerationUpdate={(status) => onModerationUpdate(item.id, status)}
          />
        ))}
      </div>
    </section>
  );
}

function ModerationHeader({
  statusFilter,
  onStatusFilterChange,
}: {
  statusFilter: "pending" | "accepted" | "rejected" | "all";
  onStatusFilterChange: (value: "pending" | "accepted" | "rejected" | "all") => void;
}) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h2 className="text-lg font-semibold">Moderation Queue</h2>
      </div>
      <select
        className="control w-full sm:w-44"
        value={statusFilter}
        onChange={(event) =>
          onStatusFilterChange(event.target.value as typeof statusFilter)
        }
      >
        <option value="pending">Pending</option>
        <option value="accepted">Accepted</option>
        <option value="rejected">Rejected</option>
        <option value="all">All</option>
      </select>
    </div>
  );
}

function ModerationCard({
  item,
  isUpdating,
  onModerationUpdate,
}: {
  item: ModerationItem;
  isUpdating: boolean;
  onModerationUpdate: (status: "accepted" | "rejected") => void;
}) {
  return (
    <article className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold">
              {item.domain_name ?? "Unknown domain"}
            </span>
            <StatusPill status={item.status} flagged />
            <span className="text-xs uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
              {item.llm_route ?? "unknown"} route
            </span>
          </div>
          <p className="mt-2 break-all font-mono text-xs text-zinc-500 dark:text-zinc-400">
            {item.query_id}
          </p>
        </div>
        {item.status === "pending" ? (
          <div className="flex gap-2">
            <button
              className="button-secondary h-9"
              type="button"
              disabled={isUpdating}
              onClick={() => onModerationUpdate("accepted")}
            >
              <Check size={16} />
              Accept
            </button>
            <button
              className="button-secondary h-9"
              type="button"
              disabled={isUpdating}
              onClick={() => onModerationUpdate("rejected")}
            >
              <X size={16} />
              Reject
            </button>
          </div>
        ) : null}
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <div className="rounded-lg bg-zinc-50 p-3 dark:bg-zinc-900">
          <p className="text-xs font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
            Question
          </p>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-6">
            {item.question || "Question text was not stored for this older flagged item."}
          </p>
        </div>
        <div className="rounded-lg bg-zinc-50 p-3 dark:bg-zinc-900">
          <p className="text-xs font-semibold uppercase tracking-[0.08em] text-zinc-500 dark:text-zinc-400">
            Answer
          </p>
          <p className="mt-2 whitespace-pre-wrap text-sm leading-6">
            {item.answer || "Answer text was not stored for this older flagged item."}
          </p>
        </div>
      </div>

      <ScoreGrid scores={item.scores} />
      <div className="mt-4 grid gap-2 text-xs text-zinc-600 dark:text-zinc-300">
        {Object.entries(item.rationale).map(([key, value]) => (
          <p key={key}>
            <span className="font-semibold capitalize">
              {key.replace("_", " ")}:
            </span>{" "}
            {String(value)}
          </p>
        ))}
      </div>
    </article>
  );
}

function MetricBlock({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="surface rounded-lg p-4">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-zinc-500 dark:text-zinc-400">
          {label}
        </span>
        {icon}
      </div>
      <p className="mt-3 text-3xl font-semibold">{value}</p>
    </div>
  );
}

function ScoreGrid({ scores }: { scores: Pick<EvaluationScores, "faithfulness" | "relevance" | "completeness" | "citation_accuracy"> }) {
  return (
    <div className="mt-4 grid gap-2 sm:grid-cols-2">
      {scoreLabels.map(([key, label]) => (
        <div
          key={key}
          className="flex items-center justify-between rounded-lg bg-zinc-50 px-3 py-2 text-xs dark:bg-zinc-900"
        >
          <span className="text-zinc-500 dark:text-zinc-400">{label}</span>
          <span className="font-semibold">{formatScore(scores[key])}</span>
        </div>
      ))}
    </div>
  );
}

function ScorePill({ score }: { score: number | null }) {
  return (
    <span className="rounded-lg bg-emerald-100 px-2.5 py-1.5 text-xs font-semibold text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100">
      {formatScore(score)}
    </span>
  );
}

function StatusPill({
  status,
  flagged = false,
}: {
  status: string;
  flagged?: boolean;
}) {
  const className = flagged
    ? "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-100"
    : "bg-zinc-100 text-zinc-700 dark:bg-zinc-900 dark:text-zinc-200";
  return (
    <span className={`inline-flex rounded-lg px-2.5 py-1.5 text-xs font-semibold ${className}`}>
      {status}
    </span>
  );
}

function LoadingState() {
  return (
    <div className="mt-5 flex items-center gap-2 text-sm text-zinc-500 dark:text-zinc-400">
      <Loader2 className="animate-spin" size={16} />
      Loading
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="mt-5 rounded-lg border border-zinc-200 p-4 text-sm text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
      {text}
    </div>
  );
}

function ErrorBanner({ error }: { error: string }) {
  if (!error) return null;
  return (
    <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
      {error}
    </p>
  );
}

function averageScore(
  scores: Pick<EvaluationScores, "faithfulness" | "relevance" | "completeness" | "citation_accuracy">,
): number | null {
  const values = scoreLabels
    .map(([key]) => scores[key])
    .filter((score): score is number => typeof score === "number");
  if (!values.length) return null;
  return values.reduce((sum, score) => sum + score, 0) / values.length;
}

function formatScore(score: number | null | undefined): string {
  if (typeof score !== "number") return "--";
  return `${Math.round(score * 100)}%`;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "unknown time";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
