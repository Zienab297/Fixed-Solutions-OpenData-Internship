import type {
  Domain,
  EvaluationStatusResponse,
  IngestionJob,
  IngestionStatus,
  LoginResponse,
  Membership,
  ModerationItem,
  QualityDomainDetail,
  QualityDomainSummary,
  QueryResponse,
  User,
} from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export const tokenStorageKey = "rag_auth_token";
export const userStorageKey = "rag_auth_user";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

type RequestOptions = RequestInit & {
  token?: string | null;
};

async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData) && !(options.body instanceof URLSearchParams)) {
    headers.set("Content-Type", "application/json");
  }

  if (options.token) {
    headers.set("Authorization", `Bearer ${options.token}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") {
        message = body.detail;
      } else if (Array.isArray(body.detail)) {
        message = body.detail
          .map((item: { loc?: unknown[]; msg?: string }) => {
            const field = Array.isArray(item.loc)
              ? item.loc.filter((part) => part !== "body").join(".")
              : "field";
            return `${field}: ${item.msg ?? "Invalid value"}`;
          })
          .join("; ");
      } else if (body.detail?.message) {
        message = body.detail.message;
      } else if (body.message) {
        message = body.message;
      }
    } catch {
      // Keep the HTTP status message when the response is not JSON.
    }
    throw new ApiError(message, response.status);
  }

  return response.json() as Promise<T>;
}

function normalizeUser(user: User): User {
  return {
    ...user,
    role: user.role ?? (user.user_pool === "external" ? "reader" : "admin"),
  };
}

function normalizeIngestionStatus(status: string): IngestionStatus {
  const normalized = status.toLowerCase();
  if (normalized === "success" || normalized === "done") {
    return "completed";
  }
  if (normalized === "failure" || normalized === "failed") {
    return "failed";
  }
  if (normalized === "started" || normalized === "retry" || normalized === "processing") {
    return "processing";
  }
  return "pending";
}

type BackendIngestResponse = {
  job_id: string;
  document_id?: string | null;
  status: string;
  message: string;
};

type BackendJobStatusResponse = {
  job_id: string;
  status: string;
  result?: unknown;
};

function toIngestionJob(
  response: BackendIngestResponse,
  fallback?: { domainId?: string; filename?: string },
): IngestionJob {
  const now = new Date().toISOString();
  return {
    id: response.job_id,
    document_id: response.document_id,
    status: normalizeIngestionStatus(response.status),
    domain_id: fallback?.domainId,
    filename: fallback?.filename,
    message: response.message,
    created_at: now,
    updated_at: now,
  };
}

// Submits credentials to the real auth endpoint and returns the token + user.
export async function login(email: string, password: string): Promise<LoginResponse> {
  const body = new URLSearchParams();
  body.append("username", email);
  body.append("password", password);

  const response = await apiRequest<LoginResponse>("/auth/token", {
    method: "POST",
    body,
  });

  return {
    ...response,
    user: normalizeUser(response.user),
  };
}

export function fetchCurrentUser(token: string): Promise<User> {
  return apiRequest<User>("/auth/me", { token }).then(normalizeUser);
}

export type CreateUserPayload = {
  email: string;
  password: string;
  role: "reader" | "contributor" | "domain_admin";
  domain_id: string; // always required — roles are domain-scoped
};

// admin/domain_admin can create users scoped to a domain.
export function createUser(token: string, payload: CreateUserPayload): Promise<User> {
  return apiRequest<User>("/auth/users", {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  }).then(normalizeUser);
}

export function createDomain(token: string, name: string): Promise<Domain> {
  return apiRequest<Domain>("/domains/", {
    method: "POST",
    token,
    body: JSON.stringify({
      name,
      llm_route: "local",
      supported_languages: ["en"],
    }),
  });
}

export async function fetchDomains(token: string): Promise<Domain[]> {
  const [allDomains, memberships] = await Promise.all([
    apiRequest<Domain[]>("/domains/", { token }),
    apiRequest<Membership[]>("/domains/my", { token }),
  ]);

  const authorizedIds = new Set(memberships.map((m) => m.domain_id));
  return allDomains.filter((d) => authorizedIds.has(d.id));
}

export function askQuestion(
  token: string,
  query: string,
  domainId?: string,
): Promise<QueryResponse> {
  return apiRequest<QueryResponse>("/query", {
    method: "POST",
    token,
    body: JSON.stringify({
      query,
      domain_ids: domainId ? [domainId] : [],
      domain_routes: {},
      context: [],
    }),
  });
}

export function fetchEvaluation(
  token: string,
  queryId: string,
): Promise<EvaluationStatusResponse> {
  return apiRequest<EvaluationStatusResponse>(`/evaluate/${queryId}`, { token });
}

export function fetchQualitySummary(
  token: string,
): Promise<{ domains: QualityDomainSummary[] }> {
  return apiRequest<{ domains: QualityDomainSummary[] }>("/evaluate/quality/summary", {
    token,
  });
}

export function fetchQualityDomainDetail(
  token: string,
  domainId: string,
): Promise<QualityDomainDetail> {
  return apiRequest<QualityDomainDetail>(`/evaluate/quality/domains/${domainId}`, {
    token,
  });
}

export function fetchModerationItems(
  token: string,
  statusFilter: "pending" | "accepted" | "rejected" | "all" = "pending",
): Promise<{ items: ModerationItem[] }> {
  return apiRequest<{ items: ModerationItem[] }>(
    `/evaluate/moderation?status_filter=${encodeURIComponent(statusFilter)}`,
    { token },
  );
}

export function updateModerationItem(
  token: string,
  itemId: string,
  status: "pending" | "accepted" | "rejected",
  reviewerRationale?: string,
): Promise<{ id: string; status: string }> {
  return apiRequest<{ id: string; status: string }>(`/evaluate/moderation/${itemId}`, {
    method: "PATCH",
    token,
    body: JSON.stringify({
      status,
      reviewer_rationale: reviewerRationale,
    }),
  });
}

export function deleteDomainDocument(
  token: string,
  domainId: string,
  documentId: string,
): Promise<{ document_id: string; deleted: boolean; deleted_chunk_count: number }> {
  return apiRequest<{ document_id: string; deleted: boolean; deleted_chunk_count: number }>(
    `/evaluate/quality/domains/${domainId}/documents/${documentId}`,
    {
      method: "DELETE",
      token,
    },
  );
}

export function uploadDocument(
  token: string,
  file: File,
  domainId: string,
): Promise<IngestionJob> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("domain_id", domainId);

  return apiRequest<BackendIngestResponse>("/ingest/document", {
    method: "POST",
    token,
    body: formData,
  }).then((response) =>
    toIngestionJob(response, { domainId, filename: file.name }),
  );
}

export function fetchIngestionJob(
  token: string,
  jobId: string,
): Promise<IngestionJob> {
  return apiRequest<BackendJobStatusResponse>(`/ingest/status/${jobId}`, {
    token,
  }).then((response) => ({
    id: response.job_id,
    status: normalizeIngestionStatus(response.status),
    message:
      typeof response.result === "string" ? response.result : undefined,
    updated_at: new Date().toISOString(),
  }));
}
