import type { IngestionStatus } from "../types";

const statusClasses: Record<IngestionStatus, string> = {
  pending:
    "border-zinc-300 bg-zinc-100 text-zinc-700 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300",
  processing:
    "border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-200",
  completed:
    "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  failed:
    "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-200",
};

type Props = {
  status: IngestionStatus;
};

export default function StatusBadge({ status }: Props) {
  return (
    <span
      className={`inline-flex h-8 items-center rounded-lg border px-3 text-xs font-semibold uppercase tracking-[0.08em] ${statusClasses[status]}`}
    >
      {status}
    </span>
  );
}
