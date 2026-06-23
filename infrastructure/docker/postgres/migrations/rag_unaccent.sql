-- Migration: add rag_unaccent text search configuration
--
-- Required by bm25_search.py — content_tsv columns in rag.chunks were
-- generated at ingestion time using this config, and BM25 query-time
-- search uses the SAME fixed config (plainto_tsquery('rag_unaccent', ...)).
-- Without this config existing in Postgres, BM25 search fails outright
-- with: text search configuration "rag_unaccent" does not exist.
--
-- Safe to re-run: each statement is idempotent / guarded.

CREATE EXTENSION IF NOT EXISTS unaccent;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_ts_config WHERE cfgname = 'rag_unaccent'
    ) THEN
        CREATE TEXT SEARCH CONFIGURATION rag_unaccent ( COPY = pg_catalog.english );
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_ts_dict WHERE dictname = 'rag_unaccent_dict'
    ) THEN
        CREATE TEXT SEARCH DICTIONARY rag_unaccent_dict (
            TEMPLATE = unaccent,
            RULES = unaccent
        );
    END IF;
END
$$;

ALTER TEXT SEARCH CONFIGURATION rag_unaccent
    ALTER MAPPING FOR hword, hword_part, word
    WITH rag_unaccent_dict, english_stem;

-- Verify:
--   SELECT cfgname FROM pg_ts_config WHERE cfgname = 'rag_unaccent';
-- Should return exactly one row.