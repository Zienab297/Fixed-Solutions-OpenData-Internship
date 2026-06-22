"""
Named Entity Recognition service.
Used at BOTH ingestion time and query time (§3.3).

Improvements over original:
- spaCy model loaded once as a module-level singleton via @lru_cache.
- extract_entities() runs spaCy in a thread pool — sync call doesn't block
  the async event loop under concurrent requests.
- classify_query() uses lingua confidence scores, not just length heuristics,
  so short but unambiguous foreign-language queries still route correctly.
- Entity deduplication by (lowercased text, label).
- Language detection reuses lang_detect.py — single source of truth.
"""

import asyncio
import logging
from functools import lru_cache
from typing import List, Optional, Tuple

import spacy
from spacy.language import Language

from app.services.retrieval.lang_detect import detect_language

logger = logging.getLogger(__name__)

_NER_MODEL = "xx_ent_wiki_sm"   # multilingual; swap for fine-tuned in prod


@lru_cache(maxsize=1)
def _load_nlp() -> Optional[Language]:
    """Load spaCy model once and cache it for the lifetime of the process."""
    try:
        return spacy.load(_NER_MODEL)
    except OSError:
        logger.warning(
            "spaCy model '%s' not found. Run: python -m spacy download %s",
            _NER_MODEL, _NER_MODEL,
        )
        return None


class NERService:
    def __init__(self):
        self._nlp = _load_nlp()

    async def extract_entities(self, text: str) -> List[Tuple[str, str]]:
        """
        Extract (entity_text, entity_type) pairs from text.
        Returns e.g. [("Vodafone", "ORG"), ("2024", "DATE")]

        Runs spaCy in a thread pool — non-blocking for async callers.
        Deduplicates by (lowercased text, label).
        """
        if not self._nlp or not text.strip():
            return []

        loop = asyncio.get_event_loop()
        doc = await loop.run_in_executor(None, self._nlp, text)

        seen: set[tuple] = set()
        entities: List[Tuple[str, str]] = []
        for ent in doc.ents:
            key = (ent.text.lower(), ent.label_)
            if key not in seen:
                seen.add(key)
                entities.append((ent.text, ent.label_))

        return entities

    async def classify_query(self, query: str) -> str:
        """
        Classify query as 'keyword' or 'semantic'.
        Used by pipeline router to set BM25 vs vector signal weights.

        Heuristics (no model, sub-millisecond):
        - Quoted terms, slashes, underscores → keyword (exact match intent)
        - Very short (<=3 tokens) AND no detected language → keyword
        - Otherwise → semantic
        """
        tokens = query.split()

        if any(c in query for c in ('"', "'", "/", "_", "#")):
            return "keyword"

        if len(tokens) <= 3 and detect_language(query) is None:
            return "keyword"

        return "semantic"

    async def extract_triples(self, text: str, ontology_schema: dict) -> List[dict]:
        """
        Extract subject → predicate → object triples from text.
        Constrained to declared ontology schema (§2.5).
        Used during ingestion to populate graph DB.

        TODO: implement relation extraction via local LLM prompt.
        """
        await self.extract_entities(text)   # warm-up / validation
        return []
