"""
Embedding service using multilingual-e5-large from HuggingFace.
Runs locally — no external API needed.
Supports all 5 required languages: EN, AR, FR, DE, ES.
"""
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
        """
        Embed text(s) using multilingual-e5-large.
        mE5 requires a prefix: 'query: ' for queries, 'passage: ' for documents.
        """
        model = _get_model()

        if isinstance(text, str):
            # Single query
            prefixed = f"query: {text}"
            embedding = model.encode(prefixed, normalize_embeddings=True)
            return embedding.tolist()
        else:
            # Batch of passages (ingestion)
            prefixed = [f"passage: {t}" for t in text]
            embeddings = model.encode(prefixed, normalize_embeddings=True, batch_size=32)
            return embeddings.tolist()
