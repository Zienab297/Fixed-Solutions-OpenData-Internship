export type Role = "admin" | "domain_admin" | "contributor" | "reader";

export type User = {
  id: string;
  keycloak_id: string;
  email: string;
  user_pool?: "internal" | "external";
  role: Role;
  created_at?: string;
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
  status: "active" | "archived";
  llm_route: "local" | "api" | "auto";
  confidence_threshold: number;
  chunk_size: number;
  chunk_overlap: number;
  supported_languages: string[];
  created_at: string;
};

export type Citation = {
  chunk_id: string;
  document_title: string;
  page_number?: number | null;
  section?: string | null;
  domain_id: string;
  domain_name?: string;
  relevance_score: number;
};

export type QueryResponse = {
  answer: string;
  llm_route: "local" | "api";
  language_detected: string;
  citations: Citation[];
  confidence_score: number;
  signals_used: string[];
};

export type IngestionStatus = "pending" | "processing" | "completed" | "failed";

export type IngestionJob = {
  id: string;
  status: IngestionStatus;
  document_id?: string | null;
  domain_id?: string;
  filename?: string;
  message?: string;
  error_message?: string | null;
  created_at?: string;
  updated_at?: string;
};
