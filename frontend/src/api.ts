import type { Domain, IngestionJob, IngestionStatus, LoginResponse, QueryResponse, User } from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
const DEV_AUTH_TOKEN = "dev-mode";

export const tokenStorageKey = "rag_auth_token";
export const userStorageKey = "rag_auth_user";

type RequestOptions = RequestInit & {
  token?: string | null;
};

async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData)) {
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
    throw new Error(message);
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

export async function login(_email: string, _password: string): Promise<LoginResponse> {
  const user = await apiRequest<User>("/auth/me");
  return {
    access_token: DEV_AUTH_TOKEN,
    token_type: "bearer",
    user: normalizeUser(user),
  };
}

export function fetchCurrentUser(token: string): Promise<User> {
  return apiRequest<User>("/auth/me", { token }).then(normalizeUser);
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

export function fetchDomains(token: string): Promise<Domain[]> {
  return apiRequest<Domain[]>("/domains/", { token });
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

export function uploadPdf(
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
