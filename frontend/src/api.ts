import type { Domain, IngestionJob, LoginResponse, QueryResponse } from "./types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

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
      message = body.detail ?? message;
    } catch {
      // Keep the HTTP status message when the response is not JSON.
    }
    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

export function login(email: string, password: string): Promise<LoginResponse> {
  return apiRequest<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
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

  return apiRequest<IngestionJob>("/ingest", {
    method: "POST",
    token,
    body: formData,
  });
}

export function fetchIngestionJob(
  token: string,
  jobId: string,
): Promise<IngestionJob> {
  return apiRequest<IngestionJob>(`/ingest/${jobId}`, { token });
}
