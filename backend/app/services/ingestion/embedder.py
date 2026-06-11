"""
Embedding service using Google Gemini gemini-embedding-2.

Supports both text (str / list[str]) and raw image bytes for multimodal RAG.
All public methods mirror the original interface so existing callers are
unaffected.
"""
import asyncio
import logging
from typing import List, Union

from google import genai
from google.genai import types

from app.core.config import settings

logger = logging.getLogger(__name__)

# Module-level Gemini client — created once, reused across calls.
_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


class EmbeddingService:
    """
    Thin wrapper around the Gemini Embeddings API.

    Text path  : embed_sync(str | list[str])   → list[float] | list[list[float]]
    Image path : embed_image_sync(bytes, mime)  → list[float]
    """

    def __init__(self):
        self.model_name = settings.EMBEDDING_MODEL   # "gemini-embedding-2"
        self.dimension = settings.EMBEDDING_DIMENSION  # 3072

    # ------------------------------------------------------------------
    # Async convenience wrappers (FastAPI / async callers)
    # ------------------------------------------------------------------

    async def embed(
        self, text: Union[str, List[str]]
    ) -> Union[List[float], List[List[float]]]:
        """Async text embedding — offloads blocking call to a thread."""
        return await asyncio.to_thread(self.embed_sync, text)

    async def embed_image(
        self, image_bytes: bytes, mime_type: str = "image/png"
    ) -> List[float]:
        """Async image embedding — offloads blocking call to a thread."""
        return await asyncio.to_thread(self.embed_image_sync, image_bytes, mime_type)

    # ------------------------------------------------------------------
    # Synchronous implementations (Celery tasks / sync callers)
    # ------------------------------------------------------------------

    def embed_sync(
        self, text: Union[str, List[str]]
    ) -> Union[List[float], List[List[float]]]:
        """
        Embed one string or a list of strings synchronously.
        Returns a single vector for str input, list of vectors for list input.
        """
        if isinstance(text, str):
            return self._embed_texts([text])[0]
        return self._embed_texts(text)

    def embed_image_sync(
        self, image_bytes: bytes, mime_type: str = "image/png"
    ) -> List[float]:
        """
        Embed raw image bytes using the natively multimodal Gemini model.
        mime_type should be one of: image/png, image/jpeg, image/webp, etc.
        """
        client = _get_client()
        response = client.models.embed_content(
            model=self.model_name,
            contents=types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
        )
        vector = list(response.embeddings[0].values)
        if len(vector) != self.dimension:
            raise ValueError(
                f"{self.model_name} produced {len(vector)} image dimensions; "
                f"expected {self.dimension}"
            )
        return vector

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        Call the Gemini Embeddings API for a list of text strings.
        Gemini embed_content accepts a single string or Part; we call it once
        per text to keep error isolation clean and stay within quota.
        """
        client = _get_client()
        vectors: List[List[float]] = []
        for text in texts:
            response = client.models.embed_content(
                model=self.model_name,
                contents=text,
                config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
            )
            vector = list(response.embeddings[0].values)
            if len(vector) != self.dimension:
                raise ValueError(
                    f"{self.model_name} produced {len(vector)} dimensions; "
                    f"expected {self.dimension}"
                )
            vectors.append(vector)
        return vectors
