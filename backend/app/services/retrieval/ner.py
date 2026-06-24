"""
backend/app/services/retrieval/ner.py

Query-time NER (§3.3). Incoming queries are analysed for named entities
BEFORE retrieval begins — a first-class step, not a side effect of the
router. Output feeds graph_search.py (which entities/labels to traverse)
and the router's signal-weighting decision in pipeline.py.

PATCHED — this no longer loads its own spaCy model. §3.3 explicitly
requires "Shared self-hosted model used at both ingestion and query
time" — the only model that satisfies that is the GLiNER service
already running in Docker and already called by extractor.py via
app.services.ner.ner_client. Running a second, different, untyped
spaCy model here would silently violate that requirement: query-time
entity types would never line up with the AGE vertex labels ingestion
actually wrote (Disease, LegalNorm, ...), so graph_search.py could
never MATCH anything by label.

extract_triples() has been REMOVED from this file. Triple extraction
is an ingestion-only concern (§2.5) and already lives correctly in
app.services.llm.triple_extractor, called from extractor.py. It was
dead code here (always returned []) and didn't belong in the
query-time retrieval path at all — queries are matched against
existing graph nodes/edges, they don't write new ones.

Design notes:
- extract_entities() takes domain_names (already resolved, deduped
  ontology keys — see domain_resolver.py) rather than UUIDs, so this
  module has no DB dependency and stays a thin, easily-testable caller
  of ner_client, mirroring how extractor.py is also given a resolved
  domain string rather than resolving it itself.
- Multiple domains -> one ner_client.extract_entities() call PER
  distinct domain (label sets genuinely differ: medical vs legal), run
  concurrently, results merged + deduped by (lowercased text, label).
  This matches the access rule: pipeline.py is expected to pass only
  the domains the user can actually access (combine if >1 accessible,
  restrict to what's available if not) — this function just executes
  NER across whatever domain set it's given.
- classify_query() is unchanged — pure heuristic, no model dependency.
"""

import asyncio
import logging
from typing import List, Tuple

from app.services.ner import ner_client
from app.services.ner.ner_client import Entity
from app.services.retrieval.lang_detect import detect_language

logger = logging.getLogger(__name__)

_NER_THRESHOLD = 0.4   # matches extractor.py's ingestion-time threshold —
                        # keep these in sync; a divergent query-time
                        # threshold would mean a query and the chunks
                        # that should match it get extracted at different
                        # entity-confidence bars.


class NERService:
    async def extract_entities(
        self,
        text: str,
        domain_names: List[str],
    ) -> List[Tuple[str, str]]:
        """
        Extract (entity_text, entity_label) pairs from a query, using the
        SAME GLiNER service + domain ontology label sets as ingestion.

        domain_names: resolved, deduped ontology keys (e.g. ["medical"]
        or ["medical", "legal"]) for the domains this query is scoped to
        — already filtered down to what the requesting user can access.
        Pass an empty list if domain scoping isn't known yet (e.g. a
        pre-auth health check) — returns [] without calling the NER
        service, since there's no valid label set to ask GLiNER for.

        Runs one ner_client.extract_entities() call per domain
        concurrently (different domains have different label sets, so
        they can't be combined into a single GLiNER request), then
        merges and deduplicates by (lowercased text, label) the same
        way the original spaCy version did.

        A single domain's NER call failing (service hiccup, unknown
        ontology key) does not fail the others — logged and skipped,
        consistent with pipeline.py's per-signal isolation philosophy
        (a degraded NER result should weaken, not break, retrieval).
        """
        if not text.strip() or not domain_names:
            return []

        async def _extract_for_domain(domain: str) -> List[Entity]:
            try:
                return await ner_client.extract_entities(
                    text=text,
                    domain=domain,
                    threshold=_NER_THRESHOLD,
                )
            except Exception as exc:
                logger.warning(
                    "Query-time NER failed for domain '%s': %s", domain, exc
                )
                return []

        per_domain_results = await asyncio.gather(
            *(_extract_for_domain(d) for d in domain_names)
        )

        seen: set[tuple] = set()
        entities: List[Tuple[str, str]] = []
        for domain_entities in per_domain_results:
            for ent in domain_entities:
                key = (ent.text.lower(), ent.label)
                if key not in seen:
                    seen.add(key)
                    entities.append((ent.text, ent.label))

        return entities

    async def classify_query(self, query: str) -> str:
        """
        Classify query as 'keyword' or 'semantic'.
        Used by pipeline router to set BM25 vs vector signal weights.
        Unchanged from the original — pure heuristic, no model call.

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
