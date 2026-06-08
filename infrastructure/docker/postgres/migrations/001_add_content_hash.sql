-- Migration: add content_hash to rag.documents for duplicate detection
-- Run this against your existing DB if you've already applied init.sql.
-- If you're starting fresh, just add it to init.sql directly (see comment below).

ALTER TABLE rag.documents
    ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64);

-- Index for the duplicate lookup (hash + domain)
CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON rag.documents(content_hash);

-- Unique constraint: same file content can't appear twice in the same domain
ALTER TABLE rag.documents
    DROP CONSTRAINT IF EXISTS uq_document_hash_domain;

ALTER TABLE rag.documents
    ADD CONSTRAINT uq_document_hash_domain
    UNIQUE (content_hash, domain_id);

-- NOTE: for a fresh setup, add this to init.sql in the documents table definition:
--   content_hash VARCHAR(64),
--   CONSTRAINT uq_document_hash_domain UNIQUE (content_hash, domain_id)
-- and add to the indexes section:
--   CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON rag.documents(content_hash);