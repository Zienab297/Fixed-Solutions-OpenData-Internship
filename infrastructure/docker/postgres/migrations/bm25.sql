-- =============================================================================
-- Migration: BM25 support for rag.chunks
-- Run once. All statements are idempotent (safe to re-run).
--
-- What this does:
-- 1. Enables unaccent extension (accent-insensitive matching: café → cafe)
-- 2. Creates a custom rag_unaccent TS config — the default used by content_tsv.
--    It chains unaccent → simple so it works for any language at index time.
--    At query time, lang_detect.py resolves the per-query config dynamically
--    (e.g. "arabic", "french") from Postgres's built-in stemmer configs.
--    No per-language config blocks needed here.
-- 3. Adds a generated content_tsv column — Postgres keeps it in sync
--    automatically on every INSERT / UPDATE.
-- 4. Adds a GIN index on content_tsv — makes tsvector queries fast.
--    Without this, every BM25 call is a full sequential scan of rag.chunks.
-- =============================================================================

-- 1. unaccent — handles accented characters across European languages
CREATE EXTENSION IF NOT EXISTS unaccent;

-- 2. Single custom config used for INDEXING.
--    Chains unaccent → simple: strips accents, lowercases, no stemming.
--    Stemming happens at query time via language-specific built-in configs.
--    (If you applied different stemmers at index vs query time, tsquery
--     wouldn't match tsvector correctly.)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_ts_config WHERE cfgname = 'rag_unaccent'
    ) THEN
        CREATE TEXT SEARCH CONFIGURATION rag_unaccent (COPY = simple);
        ALTER TEXT SEARCH CONFIGURATION rag_unaccent
            ALTER MAPPING FOR hword, hword_part, word
            WITH unaccent, simple;
    END IF;
END
$$;

-- 3. Generated tsvector column — always in sync, no manual maintenance.
--    Uses rag_unaccent (unaccent + simple) for broad cross-language indexing.
ALTER TABLE rag.chunks
    ADD COLUMN IF NOT EXISTS content_tsv tsvector
        GENERATED ALWAYS AS (
            to_tsvector('rag_unaccent', coalesce(content, ''))
        ) STORED;

-- 4. GIN index — required for fast tsvector lookups
CREATE INDEX IF NOT EXISTS idx_chunks_content_tsv
    ON rag.chunks USING GIN (content_tsv);

-- Composite btree on domain_id — used by the RBAC WHERE clause
CREATE INDEX IF NOT EXISTS idx_chunks_domain_id
    ON rag.chunks (domain_id);

-- =============================================================================
-- Verification queries (run after migration)
-- =============================================================================

-- Confirm column exists:
-- SELECT column_name FROM information_schema.columns
-- WHERE table_schema = 'rag' AND table_name = 'chunks' AND column_name = 'content_tsv';

-- Confirm index exists:
-- SELECT relname FROM pg_class WHERE relname = 'idx_chunks_content_tsv';

-- Confirm custom config exists:
-- SELECT cfgname FROM pg_ts_config WHERE cfgname = 'rag_unaccent';

-- Smoke test BM25 query (replace 'english' with detected lang at runtime):
-- SELECT id, ts_rank_cd(content_tsv, plainto_tsquery('english', 'revenue growth'), 32) AS score
-- FROM rag.chunks
-- WHERE content_tsv @@ plainto_tsquery('english', 'revenue growth')
-- ORDER BY score DESC LIMIT 5;