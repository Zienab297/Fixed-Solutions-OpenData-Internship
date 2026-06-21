"""
Hybrid Retrieval Pipeline
Orchestrates: Query-time NER → Router → Vector + BM25 + Graph → RRF Fusion

Key improvements over original:
- Signals run in parallel via asyncio.gather().
- Language detected once here and threaded to BM25 + NER — no duplicate detection.
- Signal weights computed per-query (keyword vs. semantic).
- Graph boost applied to RRF output for chunks confirmed by graph traversal.
- Confidence uses original vector cosine scores, not RRF artifacts.
- Each signal failure is isolated — pipeline degrades gracefully.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.retrieval.vector_search import VectorSearchService
from app.services.retrieval.bm25_search import BM25SearchService
from app.services.retrieval.graph_search import GraphSearchService
from app.services.retrieval.ner import NERService
from app.services.retrieval.rrf import reciprocal_rank_fusion
from app.services.retrieval.lang_detect import detect_language

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
        top_k: int = 5,
        language: Optional[str] = None,   # ISO 639-1 override (e.g. from user profile)
    ) -> RetrievalResult:
        """
        Full hybrid retrieval pipeline:
        1. Detect language + run NER + classify query — in parallel
        2. Compute per-query signal weights
        3. Run vector / BM25 / graph — in parallel
        4. Weighted RRF over vector + BM25
        5. Graph boost for confirmed chunks
        6. Confidence from original cosine scores
        """

        # Step 1 — Language detection + NER + query classification in parallel.
        # detect_language is sync but fast; wrap in executor to keep it non-blocking.
        loop = asyncio.get_event_loop()
        detected_lang, entities, query_type = await asyncio.gather(
            loop.run_in_executor(None, detect_language, query),
            self.ner_service.extract_entities(query),
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
                self.vector_search.search(
                    query=query, domain_ids=domain_ids, top_k=top_k * 2
                ),
                "vector",
            ),
            self._safe(
                self.bm25_search.search(
                    query=query, domain_ids=domain_ids,
                    top_k=top_k * 2, db=self.db, language=lang,
                ),
                "bm25",
            ),
            self._safe(
                self.graph_search.search(
                    entities=entities, domain_ids=domain_ids, db=self.db
                ) if has_entities else _empty(),
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
            "node_id":        g["node_id"],
            "entity_type":    g["entity_type"],
            "entity_name":    g["entity_name"],
            "traversal_path": g.get("path", []),
            "domain_id":      g.get("domain_id"),
            "chunk_ids":      g.get("chunk_ids", []),
        }
        for g in graph_results
    ]