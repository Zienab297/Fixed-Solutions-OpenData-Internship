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

export type Membership = {
  id: string;
  user_id: string;
  domain_id: string;
  role: Role;
  granted_at: string;
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
  owner_id?: string | null;  // ← add this
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
  query_id: string;
  answer: string;
  llm_route: "local" | "api";
  language_detected: string;
  citations: Citation[];
  confidence_score: number;
  signals_used: string[];
  evaluation?: EvaluationScores | null;
};

export type EvaluationScores = {
  id?: string;
  audit_log_id?: string;
  judge_model?: string;
  faithfulness?: number | null;
  relevance?: number | null;
  completeness?: number | null;
  citation_accuracy?: number | null;
  rationale?: Record<string, unknown> | null;
  flagged?: boolean | null;
  created_at?: string | null;
};

export type EvaluationStatusResponse = {
  query_id: string;
  status: "pending" | "completed";
  evaluation: EvaluationScores | null;
};

export type QualityDomainSummary = {
  domain_id: string;
  domain_name: string;
  evaluation_count: number;
  flagged_count: number;
  scores: Required<Pick<EvaluationScores, "faithfulness" | "relevance" | "completeness" | "citation_accuracy">>;
  route_breakdown: Array<{
    llm_route: string;
    evaluation_count: number;
    flagged_count: number;
    scores: Required<Pick<EvaluationScores, "faithfulness" | "relevance" | "completeness" | "citation_accuracy">>;
  }>;
  last_evaluated_at?: string | null;
};

export type ModerationItem = {
  id: string;
  audit_log_id: string;
  evaluation_result_id: string;
  query_id: string;
  domain_id?: string | null;
  domain_name?: string | null;
  status: "pending" | "accepted" | "rejected";
  reviewer_rationale?: string | null;
  judge_model: string;
  scores: Required<Pick<EvaluationScores, "faithfulness" | "relevance" | "completeness" | "citation_accuracy">>;
  rationale: Record<string, unknown>;
  flagged: boolean;
  llm_route?: string | null;
  confidence_score?: number | null;
  created_at?: string | null;
  evaluated_at?: string | null;
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
