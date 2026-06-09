from collections.abc import Sequence

from sentence_transformers import SentenceTransformer


class EmbeddingService:
    def __init__(self, model_name: str, batch_size: int = 32) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self._model: SentenceTransformer | None = None

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        inputs = [f"passage: {text}" for text in texts]
        vectors = self.model.encode(
            inputs,
            batch_size=self.batch_size,
            normalize_embeddings=True,
        )
        return vectors.tolist()
