"""
Language detection for query-time BM25 config resolution.

Two responsibilities:
1. detect_language(text) → ISO 639-1 code ("en", "ar", "fr" ...)
   Uses lingua — significantly more accurate than langdetect on short text
   (queries are often 3-15 words).

2. query_ts_config(text, override) → Postgres TS config name ("english", "arabic" ...)
   Resolves ISO code → Postgres config name via langcodes, then validates it
   against _PG_SUPPORTED_CONFIGS (the set of configs your Postgres instance
   actually has). Falls back to "simple" if unsupported (e.g. Chinese, Japanese
   which Postgres doesn't have built-in stemmers for).

Design decisions:
- lingua detector is built once at module import (~200ms, ~50MB RAM).
  Module-level singleton — safe under async because lingua is read-only
  after construction.
- _PG_SUPPORTED_CONFIGS starts as a frozenset of Postgres 14+ built-in configs.
  Call init_pg_configs(db) at startup to extend it with any custom configs
  (e.g. rag_english from migration_bm25.sql) from your live instance.
- Minimum word count of 2 before trusting detection — single-word queries
  are too ambiguous (e.g. "revenue" falsely detects as French in some models).
- Confidence threshold 0.20 as a second gate on top of lingua's built-in
  minimum_relative_distance(0.15).
"""

import logging
from functools import lru_cache
from typing import Optional

import langcodes
from lingua import LanguageDetectorBuilder, Language

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Postgres built-in TS configs (Postgres 14+).
# Source: SELECT cfgname FROM pg_ts_config ORDER BY cfgname;
# ---------------------------------------------------------------------------
_PG_BUILTIN_CONFIGS: frozenset[str] = frozenset({
    "arabic", "armenian", "basque", "catalan", "danish", "dutch",
    "english", "finnish", "french", "german", "greek", "hindi",
    "hungarian", "indonesian", "irish", "italian", "lithuanian",
    "nepali", "norwegian", "portuguese", "romanian", "russian",
    "serbian", "simple", "spanish", "swedish", "tamil", "turkish",
    "yiddish",
})

# Mutable — updated at startup via init_pg_configs() to include custom configs.
_PG_SUPPORTED_CONFIGS: set[str] = set(_PG_BUILTIN_CONFIGS)

_FALLBACK_CONFIG      = "simple"
_CONFIDENCE_THRESHOLD = 0.20
_MIN_WORDS_FOR_DETECTION = 2   # don't trust single-word detection


# ---------------------------------------------------------------------------
# Startup hook
# ---------------------------------------------------------------------------

async def init_pg_configs(db) -> None:
    """
    Populate _PG_SUPPORTED_CONFIGS from the live Postgres instance.
    Call once from your FastAPI lifespan:

        @asynccontextmanager
        async def lifespan(app):
            async with get_db() as db:
                await init_pg_configs(db)
            yield

    Safe to skip — falls back to the built-in frozenset.
    """
    from sqlalchemy import text as sa_text

    try:
        result = await db.execute(sa_text("SELECT cfgname FROM pg_ts_config"))
        rows = result.fetchall()
        configs = {row.cfgname for row in rows}
        _PG_SUPPORTED_CONFIGS.update(configs)
        logger.info(
            "Loaded %d Postgres TS configs: %s",
            len(_PG_SUPPORTED_CONFIGS),
            sorted(_PG_SUPPORTED_CONFIGS),
        )
    except Exception as exc:
        logger.warning("Could not load pg_ts_config, using built-ins: %s", exc)


# ---------------------------------------------------------------------------
# Lingua detector — singleton
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_detector():
    """
    Build lingua detector once per process.
    with_minimum_relative_distance(0.15): returns None when the top language
    isn't at least 15% more confident than the runner-up.
    """
    return (
        LanguageDetectorBuilder
        .from_all_languages()
        .with_minimum_relative_distance(0.15)
        .build()
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_language(text: str) -> Optional[str]:
    """
    Detect language of text. Returns ISO 639-1 code or None.

    Returns None when:
    - text is empty / whitespace
    - query is a single word (too ambiguous for reliable detection)
    - lingua confidence is below _CONFIDENCE_THRESHOLD
    - detection raises an unexpected error

    Designed to be called via loop.run_in_executor() since lingua is sync.
    """
    if not text or not text.strip():
        return None

    # Single-word latin-script queries are unreliable — business terms like
    # "revenue" or "Q3" get misclassified across European languages.
    # Non-latin scripts (Arabic, Chinese, Devanagari ...) carry strong script
    # signal even in a single word, so we skip the guard for them.
    is_latin_script = all(ord(c) < 128 for c in text if c.strip())
    if is_latin_script and len(text.split()) < _MIN_WORDS_FOR_DETECTION:
        logger.debug("Short latin query — skipping detection: %r", text)
        return None

    try:
        detector = _get_detector()
        lang: Optional[Language] = detector.detect_language_of(text)

        if lang is None:
            return None

        # Second confidence gate
        confidence_values = detector.compute_language_confidence_values(text)
        if not confidence_values or confidence_values[0].value < _CONFIDENCE_THRESHOLD:
            logger.debug("Low confidence for %r — falling back to simple", text[:40])
            return None

        iso = lang.iso_code_639_1.name.lower()   # "ar", "fr", "en" ...
        logger.debug("Detected '%s' for query: %r", iso, text[:40])
        return iso

    except Exception as exc:
        logger.warning("Language detection failed: %s", exc)
        return None


def iso_to_pg_config(iso_code: Optional[str]) -> str:
    """
    Resolve an ISO 639-1 code to a Postgres TS config name.

    Chain:
    1. iso_code → langcodes → English language name ("ar" → "arabic")
    2. Check against _PG_SUPPORTED_CONFIGS
    3. Supported → return it ("arabic", "french", "english" ...)
    4. Not supported (e.g. "chinese", "japanese") → return "simple"
    """
    if not iso_code:
        return _FALLBACK_CONFIG

    try:
        lang    = langcodes.get(iso_code)
        pg_name = lang.language_name().lower()

        if pg_name in _PG_SUPPORTED_CONFIGS:
            return pg_name

        logger.debug(
            "No Postgres TS config for '%s' (%s) — using '%s'",
            pg_name, iso_code, _FALLBACK_CONFIG,
        )
        return _FALLBACK_CONFIG

    except Exception as exc:
        logger.warning("iso_to_pg_config failed for '%s': %s", iso_code, exc)
        return _FALLBACK_CONFIG


def query_ts_config(text: str, override: Optional[str] = None) -> str:
    """
    Full pipeline: text → detect language → resolve Postgres TS config.

    Args:
        text:     Query string used for auto-detection.
        override: ISO 639-1 code from upstream (user profile, domain setting).
                  If provided, skips detection entirely — override always wins.

    Returns:
        A Postgres TS config name that exists in _PG_SUPPORTED_CONFIGS,
        or "simple" as the universal fallback.
    """
    iso = override if override else detect_language(text)
    return iso_to_pg_config(iso)