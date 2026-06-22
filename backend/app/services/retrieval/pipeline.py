"""
Hybrid Retrieval Pipeline
Orchestrates: Query-time NER → Router → Vector + BM25 + Graph → RRF Fusion

PATCHED (this revision) — wires in the rebuilt ner.py / graph_search.py:

- ner.py and graph_search.py now operate on resolved ontology domain
  NAMES ("medical"/"legal"), not raw domain_id UUIDs — see
  domain_resolver.py. This pipeline now resolves domain_ids once, up
  front, via domain_resolver.get_accessible_domain_names(), and reuses
  the resolved name list for both the NER call and the graph search
  call, rather than resolving twice or (as before) never resolving at
  all and passing UUIDs straight into Cypher.
- RBAC: domain access is enforced HERE, before NER/graph even run —
  get_accessible_domain_names() intersects the caller's requested
  domain_ids against the domains the user actually holds a role in
  (domain_service.get_user_domains), per the rule: combine domains if
  the user can access more than one of the requested ones, restrict to
  whichever subset they do have otherwise. Vector/BM25 still receive
  the original `domain_ids` UUIDs unchanged — they already enforce
  RBAC at their own layer (Qdrant/Postgres filtering) and are untouched
  by this patch.
- graph_search.search()'s signature changed (entities, domain_names) —
  no more `db` param; it now goes through age_client's own pool
  instead of the request's AsyncSession, since AGE runs in a separate
  Postgres role/search_path context (see age_client.py). self.db is
  still used for bm25_search, which is unaffected.
- Everything else — parallel asyncio.gather, weighted RRF, graph
  boost, confidence calculation — is unchanged; it was already correct
  and didn't depend on the broken parts of ner.py/graph_search.py.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics import GRAPH_QUERY_LATENCY, RETRIEVAL_HIT_RATE, RETRIEVAL_SIGNAL_LATENCY
from app.services.retrieval.vector_search import VectorSearchService
from app.services.retrieval.bm25_search import BM25SearchService
from app.services.retrieval.graph_search import GraphSearchService
from app.services.retrieval.ner import NERService
from app.services.retrieval.rrf import reciprocal_rank_fusion
from app.services.retrieval.lang_detect import detect_language
from app.services.retrieval import domain_resolver

logger = logging.getLogger(__name__)

_WEIGHTS = {
    #              vector  bm25
    "semantic":   (1.0,   0.7),
    "keyword":    (0.7,   1.0),
}
_GRAPH_BOOST = 0.05


@dataclass
class RetrievalResult:
    chunks:           List[dict]
    citations:        List[dict]
    graph_citations:  Optional[List[dict]]
    confidence_score: float
    signals_used:     List[str]
    query_type:       str = "semantic"
    language:         Optional[str] = None


class RetrievalPipeline:
    def __init__(self, db: AsyncSession):
        self.db            = db
        self.vector_search = VectorSearchService()
        self.bm25_search   = BM25SearchService()
        self.graph_search  = GraphSearchService()
        self.ner_service   = NERService()

    async def retrieve(
        self,
        query: str,
        domain_ids: List[UUID],
        user_id: UUID,
        top_k: int = 5,
        language: Optional[str] = None,   # ISO 639-1 override (e.g. from user profile)
    ) -> RetrievalResult:
        """
        Full hybrid retrieval pipeline:
        0. Resolve domain_ids -> RBAC-filtered ontology domain names
           (NEW — required by both NER label selection and graph RBAC)
        1. Detect language + run NER + classify query — in parallel
        2. Compute per-query signal weights
        3. Run vector / BM25 / graph — in parallel
        4. Weighted RRF over vector + BM25
        5. Graph boost for confirmed chunks
        6. Confidence from original cosine scores

        user_id: NEW required param — needed to intersect requested
        domain_ids against the domains this user actually holds a role
        in (§1.2: "Permissions checked server-side at query time, not
        only in the UI"). Vector/BM25 enforce their own RBAC at their
        respective storage layers using the raw domain_ids, same as
        before; this resolution step is specifically what NER label
        selection and graph traversal scoping need.
        """

        # Step 0 — Resolve + RBAC-filter domain_ids to ontology domain
        # names once, shared by both NER and graph search below.
        domain_name_map = await domain_resolver.get_accessible_domain_names(
            db=self.db, user_id=user_id, requested_domain_ids=domain_ids,
        )
        domain_names = list(domain_name_map.values())
        if not domain_names:
            logger.info(
                "user_id=%s: no accessible/resolvable ontology domains among "
                "requested domain_ids=%s — NER and graph signals will be empty "
                "for this query; vector/BM25 still run.",
                user_id, domain_ids,
            )

        # Step 1 — Language detection + NER + query classification in parallel.
        # detect_language is sync but fast; wrap in executor to keep it non-blocking.
        loop = asyncio.get_event_loop()
        detected_lang, entities, query_type = await asyncio.gather(
            loop.run_in_executor(None, detect_language, query),
            self.ner_service.extract_entities(query, domain_names=domain_names),
            self.ner_service.classify_query(query),
        )

        # Caller-supplied override wins over auto-detection
        lang = language or detected_lang
        has_entities = bool(entities)

        # Step 2 — Signal weights
        w_vector, w_bm25 = _WEIGHTS.get(query_type, _WEIGHTS["semantic"])

        # Step 3 — Parallel signal execution
        vector_results, bm25_results, graph_results = await asyncio.gather(
            self._safe(
                self._timed(
                    "vector",
                    self.vector_search.search(
                        query=query, domain_ids=domain_ids, top_k=top_k * 2
                    ),
                ),
                "vector",
            ),
            self._safe(
                self._timed(
                    "bm25",
                    self.bm25_search.search(
                        query=query, domain_ids=domain_ids,
                        top_k=top_k * 2, db=self.db, language=lang,
                    ),
                ),
                "bm25",
            ),
            self._safe(
                self._timed(
                    "graph",
                    self.graph_search.search(
                        entities=entities, domain_names=domain_names,
                    ) if has_entities and domain_names else _empty(),
                ),
                "graph",
            ),
        )

        signals_used = _active([
            ("vector", vector_results),
            ("bm25",   bm25_results),
            ("graph",  graph_results),
        ])

        # Step 4 — Weighted RRF
        fused = reciprocal_rank_fusion(
            results_lists=[vector_results, bm25_results],
            weights=[w_vector, w_bm25],
            top_k=top_k,
        )

        # Step 5 — Graph boost
        if graph_results:
            fused = _apply_graph_boost(fused, graph_results, _GRAPH_BOOST)

        # Step 6 — Confidence
        confidence = _calculate_confidence(fused, graph_results)

        return RetrievalResult(
            chunks=fused,
            citations=_build_citations(fused),
            graph_citations=_build_graph_citations(graph_results) if graph_results else None,
            confidence_score=confidence,
            signals_used=signals_used,
            query_type=query_type,
            language=lang,
        )

    @staticmethod
    async def _safe(coro, name: str) -> List[dict]:
        try:
            result = await coro
            return result if isinstance(result, list) else []
        except Exception as exc:
            logger.warning("Signal '%s' failed: %s", name, exc)
            return []

    @staticmethod
    async def _timed(signal_name: str, coro) -> List[dict]:
        """
        Wraps a retrieval signal coroutine to record its latency and
        hit/miss outcome (§6.2: retrieval hit rate; graph query latency
        as its own metric). A raised exception is still timed and
        recorded as a miss before re-raising, so a failing signal shows
        up in the hit-rate ratio instead of silently disappearing from
        the metric entirely; _safe (the caller) is what turns the
        exception into an empty-list result for the pipeline itself.
        """
        start = time.perf_counter()
        try:
            result = await coro
        except Exception:
            elapsed = time.perf_counter() - start
            RETRIEVAL_SIGNAL_LATENCY.labels(signal=signal_name).observe(elapsed)
            if signal_name == "graph":
                GRAPH_QUERY_LATENCY.observe(elapsed)
            RETRIEVAL_HIT_RATE.labels(signal=signal_name, outcome="miss").inc()
            raise

        elapsed = time.perf_counter() - start
        RETRIEVAL_SIGNAL_LATENCY.labels(signal=signal_name).observe(elapsed)
        if signal_name == "graph":
            GRAPH_QUERY_LATENCY.observe(elapsed)

        outcome = "hit" if result else "miss"
        RETRIEVAL_HIT_RATE.labels(signal=signal_name, outcome=outcome).inc()

        return result


# ---------------------------------------------------------------------------
# Pure functions — no self, easier to test in isolation
# ---------------------------------------------------------------------------

async def _empty() -> List[dict]:
    return []


def _active(signal_pairs: list) -> List[str]:
    return [name for name, results in signal_pairs if results]


def _apply_graph_boost(
    chunks: List[dict],
    graph_results: List[dict],
    boost: float,
) -> List[dict]:
    confirmed: set[str] = {
        str(cid)
        for g in graph_results
        for cid in g.get("chunk_ids", [])
    }
    if not confirmed:
        return chunks
    for c in chunks:
        if c.get("id") in confirmed:
            c["rrf_score"] = c.get("rrf_score", 0.0) + boost
            c["score"]     = c["rrf_score"]
            c["graph_confirmed"] = True
    return sorted(chunks, key=lambda c: c.get("rrf_score", 0.0), reverse=True)


def _calculate_confidence(chunks: List[dict], graph_results: List[dict]) -> float:
    if not chunks:
        return 0.0
    top3 = chunks[:3]
    avg_cosine = sum(c.get("original_score", 0.0) for c in top3) / len(top3)
    graph_bonus = 0.05 if graph_results else 0.0
    return round(min(1.0, avg_cosine + graph_bonus), 4)


def _build_citations(chunks: List[dict]) -> List[dict]:
    return [
        {
            "chunk_id":         c["id"],
            "document_title":   c.get("document_title", ""),
            "page_number":      c.get("page_number"),
            "section":          c.get("section"),
            "domain_id":        c.get("domain_id"),
            "domain_name":      c.get("domain_name", ""),
            "ingest_timestamp": c.get("created_at"),
            "relevance_score":  c.get("original_score", c.get("score", 0.0)),
            "graph_confirmed":  c.get("graph_confirmed", False),
        }
        for c in chunks
    ]


def _build_graph_citations(graph_results: List[dict]) -> List[dict]:
    return [
        {
            "node_uuid":       g["node_uuid"],
            "entity_type":     g["entity_type"],
            "entity_name":     g["entity_name"],
            "traversal_path":  g.get("path", []),
            "domain_name":     g.get("domain_name"),
            "chunk_ids":       g.get("chunk_ids", []),
        }
        for g in graph_results
    ]