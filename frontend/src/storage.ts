const recentDomainIdsKey = "rag_recent_domain_ids";
const lastIngestionJobIdKey = "rag_last_ingestion_job_id";

export function readRecentDomainIds(): string[] {
  const value = localStorage.getItem(recentDomainIdsKey);
  if (!value) {
    return [];
  }

  try {
    const parsed = JSON.parse(value);
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter((item): item is string => typeof item === "string");
  } catch {
    localStorage.removeItem(recentDomainIdsKey);
    return [];
  }
}

export function rememberDomainId(domainId: string): string[] {
  const normalized = domainId.trim();
  if (!normalized) {
    return readRecentDomainIds();
  }

  const next = [
    normalized,
    ...readRecentDomainIds().filter((item) => item !== normalized),
  ].slice(0, 8);

  localStorage.setItem(recentDomainIdsKey, JSON.stringify(next));
  return next;
}

export function readLastIngestionJobId(): string | null {
  return localStorage.getItem(lastIngestionJobIdKey);
}

export function saveLastIngestionJobId(jobId: string): void {
  localStorage.setItem(lastIngestionJobIdKey, jobId);
}
