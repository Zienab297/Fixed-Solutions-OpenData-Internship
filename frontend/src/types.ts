export type Role = "admin" | "contributor" | "reader";

export type User = {
  keycloak_id: string;
  email: string;
  role: Role;
};

export type LoginResponse = {
  access_token: string;
  token_type: "bearer";
  user: User;
};

export type Domain = {
  id: string;
  name: string;
  description?: string | null;
  is_archived: boolean;
  created_by: string;
  created_at: string;
};

export type QueryResponse = {
  answer: string;
  llm_route: "local" | "api";
  language_detected: string;
  citations: string[];
};

export type IngestionStatus = "pending" | "processing" | "done" | "failed";

export type IngestionJob = {
  id: string;
  status: IngestionStatus;
  domain_id: string;
  filename: string;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
};
