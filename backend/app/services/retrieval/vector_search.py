"""Vector search via Qdrant. One collection per domain for isolation."""
from typing import List
from uuid import UUID
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchAny
from app.core.config import settings
from app.services.ingestion.embedder import EmbeddingService


class VectorSearchService:
    def __init__(self):
        self.client = AsyncQdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        self.embedder = EmbeddingService()

    def _collection_name(self, domain_id: UUID) -> str:
        return f"domain_{str(domain_id).replace('-', '_')}"

    async def search(self, query: str, domain_ids: List[UUID], top_k: int = 10) -> List[dict]:
        """
        Semantic search across one or more domain collections.
        RBAC already verified upstream — these domain_ids are pre-authorized.
        """
        query_vector = await self.embedder.embed(query)
        all_results = []

        for domain_id in domain_ids:
            collection = self._collection_name(domain_id)
            try:
                results = await self.client.search(
                    collection_name=collection,
                    query_vector=query_vector,
                    limit=top_k,
                    with_payload=True,
                )
                for r in results:
                    all_results.append({
                        "id": r.id,
                        "score": r.score,
                        "content": r.payload.get("content", ""),
                        "document_title": r.payload.get("document_title", ""),
                        "page_number": r.payload.get("page_number"),
                        "section": r.payload.get("section"),
                        "domain_id": str(domain_id),
                        "domain_name": r.payload.get("domain_name", ""),
                        "created_at": r.payload.get("created_at"),
                    })
            except Exception:
                # Collection may not exist yet for new domains
                continue

        return sorted(all_results, key=lambda x: x["score"], reverse=True)[:top_k]

    async def create_domain_collection(self, domain_id: UUID):
        """Create a Qdrant collection for a new domain (idempotent)."""
        from qdrant_client.models import VectorParams, Distance
        collection = self._collection_name(domain_id)
        existing = {c.name for c in (await self.client.get_collections()).collections}
        if collection in existing:
            return  # already provisioned
        await self.client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=settings.EMBEDDING_DIMENSION, distance=Distance.COSINE),
        )

    async def delete_domain_collection(self, domain_id: UUID) -> bool:
        """
        Drop the Qdrant collection for an archived domain.
        Returns True if deleted, False if it did not exist.
        """
        collection = self._collection_name(domain_id)
        existing = {c.name for c in (await self.client.get_collections()).collections}
        if collection not in existing:
            return False
        await self.client.delete_collection(collection_name=collection)
        return True