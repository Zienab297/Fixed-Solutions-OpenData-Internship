"""Embedding service backed by the project's configured HuggingFace model."""
from typing import List, Union
from app.core.config import settings

# Lazy load to avoid startup delay
_model = None

def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(settings.EMBEDDING_MODEL)
    return _model


class EmbeddingService:
    async def embed(self, text: Union[str, List[str]]) -> Union[List[float], List[List[float]]]:
        """Embed one query string or a batch of document passages."""
        model = _get_model()

        if isinstance(text, str):
            # Single query
            prefixed = f"query: {text}"
            embedding = model.encode(prefixed, normalize_embeddings=True)
            return embedding.tolist()
        else:
            # Batch of passages (ingestion)
            prefixed = [f"passage: {t}" for t in text]
            embeddings = model.encode(
                prefixed,
                normalize_embeddings=True,
                batch_size=settings.EMBEDDING_BATCH_SIZE,
            )
            return embeddings.tolist()
