from collections.abc import Sequence

from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, PointStruct, VectorParams

from app.ingestion.pipeline.chunker import DocumentChunk


class QdrantIndexer:
    def __init__(self, url: str, collection_name: str) -> None:
        self.client = QdrantClient(url=url)
        self.collection_name = collection_name

    def upsert(
        self,
        chunks: Sequence[DocumentChunk],
        vectors: Sequence[Sequence[float]],
    ) -> None:
        if not chunks or not vectors:
            return

        vector_size = len(vectors[0])
        self._ensure_collection(vector_size)

        points = [
            PointStruct(
                id=chunk.chunk_id,
                vector=list(vector),
                payload={
                    "chunk_id": chunk.chunk_id,
                    "doc_id": chunk.doc_id,
                    "domain_id": chunk.domain_id,
                    "page_number": chunk.page_number,
                    "text": chunk.text,
                },
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        self.client.upsert(collection_name=self.collection_name, points=points)

    def _ensure_collection(self, vector_size: int) -> None:
        if self.client.collection_exists(self.collection_name):
            return

        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
