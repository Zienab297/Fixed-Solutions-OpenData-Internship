"""
Embedding service using bge-m3:latest via Ollama.
Replaces sentence-transformers local load — Ollama serves the model,
keeping the heavy model out of the FastAPI/Celery process memory.

bge-m3 output dimension: 1024 — matches Qdrant collection config.
Supports all required languages: EN, AR, FR, DE, ES.
"""
from typing import List, Union
import httpx
from app.core.config import settings


class EmbeddingService:
    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        self.model = settings.EMBEDDING_MODEL  # "bge-m3:latest"

    async def embed(
        self, text: Union[str, List[str]]
    ) -> Union[List[float], List[List[float]]]:
        """
        Embed one string or a batch via Ollama's /api/embed endpoint.
        Returns a single vector for str input, list of vectors for list input.
        """
        if isinstance(text, str):
            return await self._embed_one(text)
        else:
            return await self._embed_batch(text)

    async def _embed_one(self, text: str) -> List[float]:
        print(f"EMBEDDER HITTING: {self.base_url}/api/embed", flush=True)
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model, "input": text},
            )
            response.raise_for_status()
            return response.json()["embeddings"][0]

    async def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Ollama /api/embed accepts a list in the input field.
        One HTTP call for the whole batch.
        """
        print(f"EMBEDDER BATCH HITTING: {self.base_url}/api/embed", flush=True)
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.base_url}/api/embed",
                json={"model": self.model, "input": texts},
            )
            response.raise_for_status()
            return response.json()["embeddings"]
        