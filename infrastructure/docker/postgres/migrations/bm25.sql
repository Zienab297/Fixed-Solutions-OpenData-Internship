-- =============================================================================
-- Migration: BM25 support for rag.chunks
-- Run once. All statements are idempotent (safe to re-run).
--
-- What this does:
-- 1. Enables unaccent extension (accent-insensitive matching: café → cafe)
-- 2. Creates a custom rag_unaccent TS config — the ONLY config used by
--    content_tsv, both at index time and at query time. It chains
--    unaccent → simple: strips accents, lowercases, does NOT stem.
--    bm25_search.py must always query with this same config
--    (plainto_tsquery('rag_unaccent', ...)) — never a language-specific
--    built-in config (e.g. "english", "arabic"). Those apply stemming/
--    stopword rules that 'rag_unaccent' does not, so tsquery lexemes
--    built under a different config will not match the tsvector lexemes
--    stored here, and BM25 will silently return near-zero results.
-- 3. Adds a generated content_tsv column — Postgres keeps it in sync
--    automatically on every INSERT / UPDATE.
-- 4. Adds a GIN index on content_tsv — makes tsvector queries fast.
--    Without this, every BM25 call is a full sequential scan of rag.chunks.
-- =============================================================================

-- 1. unaccent — handles accented characters across European languages
CREATE EXTENSION IF NOT EXISTS unaccent;

-- 2. Single custom config — used for BOTH indexing and querying.
--    Chains unaccent → simple: strips accents, lowercases, no stemming.
--    bm25_search.py queries with this exact same config. Do not swap in
--    a different built-in language config (e.g. 'english', 'arabic') at
--    query time — those stem and remove stopwords differently, so their
--    tsquery lexemes won't match the tsvector lexemes generated here,
--    and the query will silently return almost nothing.
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

-- Smoke test BM25 query — always use 'rag_unaccent', the same config
-- content_tsv was generated with. Never substitute a detected/runtime
-- language here (e.g. 'english', 'arabic') — see notes above.
-- SELECT id, ts_rank_cd(content_tsv, plainto_tsquery('rag_unaccent', 'revenue growth'), 32) AS score
-- FROM rag.chunks
-- WHERE content_tsv @@ plainto_tsquery('rag_unaccent', 'revenue growth')
-- ORDER BY score DESC LIMIT 5;