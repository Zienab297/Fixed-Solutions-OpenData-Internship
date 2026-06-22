-- Enable Apache AGE extension for graph queries


-- Enable pgcrypto for UUID generation
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Create application schema
CREATE SCHEMA IF NOT EXISTS rag;

-- Users table (mirrors Keycloak users locally for audit purposes)
CREATE TABLE IF NOT EXISTS rag.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    keycloak_id VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    user_pool VARCHAR(50) NOT NULL CHECK (user_pool IN ('internal', 'external')),
    password_hash VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Domains table
CREATE TABLE IF NOT EXISTS rag.domains (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    status VARCHAR(50) DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    llm_route VARCHAR(50) DEFAULT 'auto' CHECK (llm_route IN ('local', 'api', 'auto')),
    confidence_threshold FLOAT DEFAULT 0.7,
    chunk_size INTEGER DEFAULT 512,
    chunk_overlap INTEGER DEFAULT 64,
    supported_languages TEXT[] DEFAULT ARRAY['en'],
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- RBAC: user roles per domain
CREATE TABLE IF NOT EXISTS rag.domain_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES rag.users(id) ON DELETE CASCADE,
    domain_id UUID REFERENCES rag.domains(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL CHECK (role IN ('domain_admin', 'contributor', 'reader')),
    granted_at TIMESTAMPTZ DEFAULT NOW(),
    granted_by UUID REFERENCES rag.users(id),
    UNIQUE (user_id, domain_id)
);

-- API Keys table (for programmatic access)
CREATE TABLE IF NOT EXISTS rag.api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key_hash VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    owner_id UUID REFERENCES rag.users(id),
    allowed_domains UUID[],
    role VARCHAR(50) NOT NULL CHECK (role IN ('contributor', 'reader')),
    rate_limit_per_day INTEGER DEFAULT 1000,
    expires_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE
);

-- Documents table
CREATE TABLE IF NOT EXISTS rag.documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_id UUID REFERENCES rag.domains(id) ON DELETE CASCADE,
    title VARCHAR(500) NOT NULL,
    source_type VARCHAR(50) NOT NULL CHECK (source_type IN ('pdf', 'docx', 'csv', 'xlsx', 'webpage', 'database')),
    source_url TEXT,
    author VARCHAR(255),
    ingest_status VARCHAR(50) DEFAULT 'pending' CHECK (ingest_status IN ('pending', 'processing', 'completed', 'failed')),
    ocr_used BOOLEAN DEFAULT FALSE,
    language VARCHAR(10),
    content_hash VARCHAR(64),
    CONSTRAINT uq_document_hash_domain UNIQUE (content_hash, domain_id),
    metadata JSONB DEFAULT '{}',
    ingested_by UUID REFERENCES rag.users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Chunks table
CREATE TABLE IF NOT EXISTS rag.chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES rag.documents(id) ON DELETE CASCADE,
    domain_id UUID REFERENCES rag.domains(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    page_number INTEGER,
    section VARCHAR(255),
    embedding_model VARCHAR(255) NOT NULL,
    embedding_version INTEGER DEFAULT 1,
    graph_node_ids UUID[],
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Structured rows extracted from CSV/table-like documents.
-- These power deterministic table QA for counts, max/min, averages, grouping,
-- filtering, and exact lookups without relying on vector retrieval.
CREATE TABLE IF NOT EXISTS rag.table_rows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES rag.documents(id) ON DELETE CASCADE,
    domain_id UUID NOT NULL REFERENCES rag.domains(id) ON DELETE CASCADE,
    chunk_id UUID REFERENCES rag.chunks(id) ON DELETE SET NULL,
    row_number INTEGER NOT NULL,
    row_data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (document_id, row_number)
);

-- Audit log (immutable, append-only)
CREATE TABLE IF NOT EXISTS rag.audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_id UUID NOT NULL,
    user_id UUID REFERENCES rag.users(id),
    api_key_id UUID REFERENCES rag.api_keys(id),
    domains_queried UUID[] NOT NULL,
    retrieved_chunk_ids UUID[],
    graph_nodes_traversed UUID[],
    llm_route VARCHAR(50),
    confidence_score FLOAT,
    faithfulness_score FLOAT,
    relevance_score FLOAT,
    completeness_score FLOAT,
    citation_accuracy_score FLOAT,
    judge_rationale JSONB,
    flagged BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Evaluation results (immutable, append-only async judge records)
CREATE TABLE IF NOT EXISTS rag.evaluation_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_log_id UUID NOT NULL REFERENCES rag.audit_logs(id),
    query_id UUID NOT NULL,
    judge_model VARCHAR(255) NOT NULL,
    faithfulness_score FLOAT NOT NULL,
    relevance_score FLOAT NOT NULL,
    completeness_score FLOAT NOT NULL,
    citation_accuracy_score FLOAT NOT NULL,
    judge_rationale JSONB,
    raw_response JSONB,
    flagged BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Golden dataset for nightly regression
CREATE TABLE IF NOT EXISTS rag.golden_dataset (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_id UUID REFERENCES rag.domains(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    expected_answer TEXT NOT NULL,
    expected_chunk_ids UUID[],
    created_by UUID REFERENCES rag.users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Moderation queue
CREATE TABLE IF NOT EXISTS rag.moderation_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    audit_log_id UUID REFERENCES rag.audit_logs(id),
    evaluation_result_id UUID REFERENCES rag.evaluation_results(id),
    domain_id UUID REFERENCES rag.domains(id),
    status VARCHAR(50) DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected')),
    reviewed_by UUID REFERENCES rag.users(id),
    reviewer_rationale TEXT,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Web crawl config
CREATE TABLE IF NOT EXISTS rag.crawl_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_id UUID REFERENCES rag.domains(id) ON DELETE CASCADE UNIQUE,
    seed_urls TEXT[] NOT NULL,
    url_whitelist TEXT[] NOT NULL,
    max_depth INTEGER DEFAULT 2,
    crawl_schedule VARCHAR(100) DEFAULT '0 2 * * *',
    last_crawled_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_chunks_domain ON rag.chunks(domain_id);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON rag.chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_table_rows_domain ON rag.table_rows(domain_id);
CREATE INDEX IF NOT EXISTS idx_table_rows_document ON rag.table_rows(document_id);
CREATE INDEX IF NOT EXISTS idx_table_rows_chunk ON rag.table_rows(chunk_id);
CREATE INDEX IF NOT EXISTS idx_table_rows_data_gin ON rag.table_rows USING GIN (row_data);
CREATE INDEX IF NOT EXISTS idx_audit_user ON rag.audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON rag.audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_eval_query ON rag.evaluation_results(query_id);
CREATE INDEX IF NOT EXISTS idx_eval_audit ON rag.evaluation_results(audit_log_id);
CREATE INDEX IF NOT EXISTS idx_eval_created ON rag.evaluation_results(created_at);
CREATE INDEX IF NOT EXISTS idx_eval_flagged ON rag.evaluation_results(flagged);
CREATE INDEX IF NOT EXISTS idx_documents_domain ON rag.documents(domain_id);
CREATE INDEX IF NOT EXISTS idx_domain_roles_user ON rag.domain_roles(user_id);
