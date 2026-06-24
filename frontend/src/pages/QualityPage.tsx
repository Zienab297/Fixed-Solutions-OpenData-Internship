import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import {
  BarChart3,
  Check,
  Clock3,
  Loader2,
  RefreshCw,
  ShieldAlert,
  X,
} from "lucide-react";

import {
  fetchModerationItems,
  fetchQualitySummary,
  updateModerationItem,
} from "../api";
import { useAuth } from "../AuthContext";
import type { EvaluationScores, ModerationItem, QualityDomainSummary } from "../types";

const scoreLabels = [
  ["faithfulness", "Faithfulness"],
  ["relevance", "Relevance"],
  ["completeness", "Completeness"],
  ["citation_accuracy", "Citations"],
] as const;

export default function QualityPage() {
  const { token } = useAuth();
  const [summaries, setSummaries] = useState<QualityDomainSummary[]>([]);
  const [moderationItems, setModerationItems] = useState<ModerationItem[]>([]);
  const [statusFilter, setStatusFilter] =
    useState<"pending" | "accepted" | "rejected" | "all">("pending");
  const [isLoading, setIsLoading] = useState(true);
  const [isUpdatingId, setIsUpdatingId] = useState("");
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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update moderation item");
    } finally {
      setIsUpdatingId("");
    }
  }

  return (
    <div className="mx-auto grid max-w-6xl gap-6">
      <section className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="grid gap-2">
          <h1 className="text-3xl font-semibold tracking-normal">Quality</h1>
          <p className="max-w-2xl text-sm leading-6 text-zinc-500 dark:text-zinc-400">
            Judge scores, route breakdowns, and flagged answer review.
          </p>
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

      {error ? (
        <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          {error}
        </p>
      ) : null}

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
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">Domain Scores</h2>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
              Mean scores from completed judge evaluations.
            </p>
          </div>
        </div>

        {isLoading ? (
          <LoadingState />
        ) : summaries.length ? (
          <div className="mt-5 grid gap-4 lg:grid-cols-2">
            {summaries.map((summary) => (
              <article
                key={summary.domain_id}
                className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="truncate text-sm font-semibold">
                      {summary.domain_name}
                    </h3>
                    <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                      {summary.evaluation_count} evaluations · {summary.flagged_count} flagged
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
                          {route.evaluation_count} · {formatScore(averageScore(route.scores))}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        ) : (
          <EmptyState text="No completed evaluations yet." />
        )}
      </section>

      <section className="surface rounded-lg p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold">Moderation Queue</h2>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
              Answers enter this queue when any judge score is below threshold.
            </p>
          </div>
          <select
            className="control w-full sm:w-44"
            value={statusFilter}
            onChange={(event) =>
              setStatusFilter(event.target.value as typeof statusFilter)
            }
          >
            <option value="pending">Pending</option>
            <option value="accepted">Accepted</option>
            <option value="rejected">Rejected</option>
            <option value="all">All</option>
          </select>
        </div>

        {isLoading ? (
          <LoadingState />
        ) : moderationItems.length ? (
          <div className="mt-5 space-y-3">
            {moderationItems.map((item) => (
              <article
                key={item.id}
                className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800"
              >
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold">
                        {item.domain_name ?? "Unknown domain"}
                      </span>
                      <span className="rounded-lg bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-900 dark:bg-amber-950 dark:text-amber-100">
                        {item.status}
                      </span>
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
                        disabled={isUpdatingId === item.id}
                        onClick={() => void handleModerationUpdate(item.id, "accepted")}
                      >
                        <Check size={16} />
                        Accept
                      </button>
                      <button
                        className="button-secondary h-9"
                        type="button"
                        disabled={isUpdatingId === item.id}
                        onClick={() => void handleModerationUpdate(item.id, "rejected")}
                      >
                        <X size={16} />
                        Reject
                      </button>
                    </div>
                  ) : null}
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
            ))}
          </div>
        ) : (
          <EmptyState text="No moderation items match this filter." />
        )}
      </section>
    </div>
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


function ScoreGrid({
  scores,
}: {
  scores: Required<Pick<EvaluationScores, "faithfulness" | "relevance" | "completeness" | "citation_accuracy">>;
}) {
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


function averageScore(
  scores: Required<Pick<EvaluationScores, "faithfulness" | "relevance" | "completeness" | "citation_accuracy">>,
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
