"""Embedding service using a local Sentence Transformers model."""
import asyncio
from functools import lru_cache
from typing import List, Union

from sentence_transformers import SentenceTransformer

from app.core.config import settings


@lru_cache(maxsize=1)
def _load_model(model_name: str) -> SentenceTransformer:
    return SentenceTransformer(model_name)


class EmbeddingService:
    def __init__(self):
        self.model_name = settings.EMBEDDING_MODEL
        self.dimension = settings.EMBEDDING_DIMENSION

    async def embed(
        self, text: Union[str, List[str]]
    ) -> Union[List[float], List[List[float]]]:
        """
        Embed one string or a batch via a locally loaded SentenceTransformer.
        Returns a single vector for str input, list of vectors for list input.
        """
        return await asyncio.to_thread(self.embed_sync, text)

    def embed_sync(
        self, text: Union[str, List[str]]
    ) -> Union[List[float], List[List[float]]]:
        if isinstance(text, str):
            return self._embed_batch([text])[0]
        return self._embed_batch(text)

    def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        model = _load_model(self.model_name)
        embeddings = model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        vectors = embeddings.tolist()
        for vector in vectors:
            if len(vector) != self.dimension:
                raise ValueError(
                    f"{self.model_name} produced {len(vector)} dimensions; "
                    f"expected {self.dimension}"
                )
        return vectors
