"""
Hybrid Retrieval Pipeline
Orchestrates: Query-time NER → Router → Vector + BM25 + Graph → RRF Fusion
"""
from dataclasses import dataclass
from typing import List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.retrieval.vector_search import VectorSearchService
from app.services.retrieval.bm25_search import BM25SearchService
from app.services.retrieval.graph_search import GraphSearchService
from app.services.retrieval.ner import NERService
from app.services.retrieval.rrf import reciprocal_rank_fusion


@dataclass
class RetrievalResult:
    chunks: List[dict]
    citations: List[dict]
    graph_citations: Optional[List[dict]]
    confidence_score: float
    signals_used: List[str]


class RetrievalPipeline:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.vector_search = VectorSearchService()
        self.bm25_search = BM25SearchService()
        self.graph_search = GraphSearchService()
        self.ner_service = NERService()

    async def retrieve(
        self,
        query: str,
        domain_ids: List[UUID],
        top_k: int = 5,
    ) -> RetrievalResult:
        """
        Full hybrid retrieval pipeline:
        1. Query-time NER to detect entities
        2. Route to appropriate signals
        3. Run signals in parallel
        4. Fuse with RRF
        5. Calculate confidence score
        """
        # Step 1 — Query-time NER (required by spec §3.3)
        entities = await self.ner_service.extract_entities(query)
        has_entities = len(entities) > 0

        # Step 2 — Determine which signals to activate
        signals_used = self._route_signals(query, entities)

        # Step 3 — Run retrieval signals
        vector_results, bm25_results, graph_results = [], [], []

        if "vector" in signals_used:
            vector_results = await self.vector_search.search(
                query=query, domain_ids=domain_ids, top_k=top_k * 2
            )

        if "bm25" in signals_used:
            bm25_results = await self.bm25_search.search(
                query=query, domain_ids=domain_ids, top_k=top_k * 2, db=self.db
            )

        if "graph" in signals_used and has_entities:
            graph_results = await self.graph_search.search(
                entities=entities, domain_ids=domain_ids, db=self.db
            )

        # Step 4 — RRF fusion
        fused_chunks = reciprocal_rank_fusion(
            results_lists=[vector_results, bm25_results],
            top_k=top_k,
        )

        # Step 5 — Confidence score (top chunk similarity + graph strength)
        confidence_score = self._calculate_confidence(fused_chunks, graph_results)

        # Build citations
        citations = self._build_citations(fused_chunks)
        graph_citations = self._build_graph_citations(graph_results) if graph_results else None

        return RetrievalResult(
            chunks=fused_chunks,
            citations=citations,
            graph_citations=graph_citations,
            confidence_score=confidence_score,
            signals_used=signals_used,
        )

    def _route_signals(self, query: str, entities: list) -> List[str]:
        """
        Determine which retrieval signals to activate.
        Entity-rich queries → include graph.
        All queries → always use vector + BM25.
        """
        signals = ["vector", "bm25"]
        # Activate graph if named entities detected (§3.4)
        if entities:
            signals.append("graph")
        return signals

    def _calculate_confidence(self, chunks: list, graph_results: list) -> float:
        """Combine top-k chunk similarity with graph match strength (§3.6)."""
        if not chunks:
            return 0.0
        avg_chunk_score = sum(c.get("score", 0) for c in chunks[:3]) / min(3, len(chunks))
        graph_boost = 0.1 if graph_results else 0.0
        return min(1.0, avg_chunk_score + graph_boost)

    def _build_citations(self, chunks: list) -> list:
        return [
            {
                "chunk_id": c["id"],
                "document_title": c.get("document_title", ""),
                "page_number": c.get("page_number"),
                "section": c.get("section"),
                "domain_id": c.get("domain_id"),
                "domain_name": c.get("domain_name", ""),
                "ingest_timestamp": c.get("created_at"),
                "relevance_score": c.get("score", 0.0),
            }
            for c in chunks
        ]

    def _build_graph_citations(self, graph_results: list) -> list:
        return [
            {
                "node_id": g["node_id"],
                "entity_type": g["entity_type"],
                "entity_name": g["entity_name"],
                "traversal_path": g.get("path", []),
            }
            for g in graph_results
        ]
