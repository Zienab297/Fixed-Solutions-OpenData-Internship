"""
Embedding service using bge-m3:latest via Ollama.
Replaces sentence-transformers local load — Ollama serves the model,
keeping the heavy model out of the FastAPI/Celery process memory.

bge-m3 output dimension: 1024 — matches Qdrant collection config.
Supports all required languages: EN, AR, FR, DE, ES.

PATCHED — retry-with-backoff + longer timeout.

This Ollama instance also serves local LLM generation calls (ontology
building, triple extraction, judge evaluation) on the SAME endpoint.
Those generation calls have been observed taking several minutes
end-to-end (see ontology_builder incident notes: one /v1/chat/completions
call took ~4m48s). If an embed call lands while Ollama is busy with one
of those, it can legitimately queue past a 60s timeout — that's not a
flaky network blip, it's real contention for one shared resource.

Previously: any exception here (timeout, connection reset, anything)
propagated straight out of EmbeddingService.embed() -> VectorSearchService
.search() -> pipeline._safe(), which silently swallowed it into an empty
vector-signal result. A single slow/contended Ollama response was
therefore enough to zero out the only consistently-working retrieval
signal for that query, with no retry and no visibility beyond a buried
logger.warning three layers up. See: "who created lab 8" intermittently
returning "I don't have enough information" purely based on Ollama load
at the moment of the request, despite the exact same chunk being
retrievable seconds/minutes apart.

Fix, two parts:
  1. Retry with exponential backoff on connect/timeout errors — handles
     transient blips and short queuing delays.
  2. Longer timeout (180s single, 240s batch) — gives a genuinely-busy
     Ollama instance room to finish a long generation call first rather
     than failing fast at 60s. Still bounded, not infinite — a stuck
     Ollama process should eventually surface as a real error rather
     than hang the request forever.

This does NOT fix the underlying resource contention (embedding and
generation competing for the same Ollama instance) — it just makes a
single query much less likely to fail outright because of it. If this
keeps showing up under load, the real fix is running embeddings on a
separate Ollama instance/model slot from generation, not a longer
timeout here.
"""
import asyncio
import logging
from typing import List, Union

import httpx
from app.core.config import settings

logger = logging.getLogger("embedder")

_SINGLE_TIMEOUT = httpx.Timeout(connect=10.0, read=180.0, write=10.0, pool=10.0)
_BATCH_TIMEOUT = httpx.Timeout(connect=10.0, read=240.0, write=10.0, pool=10.0)
_MAX_RETRIES = 2
_BACKOFF_BASE_SECONDS = 2.0


class EmbeddingServiceError(RuntimeError):
    """Raised when the embed call fails after all retries are exhausted."""


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

    async def _post_with_retry(
        self,
        payload: dict,
        timeout: httpx.Timeout,
        log_label: str,
    ) -> dict:
        """
        Shared retry/backoff logic for both single and batch embed calls.
        Retries on connection errors and timeouts only — a 4xx/5xx from
        Ollama itself (bad model name, malformed payload) won't be fixed
        by retrying, so those raise immediately via raise_for_status().
        """
        last_exc: Exception
        for attempt in range(1, _MAX_RETRIES + 2):  # 1 try + N retries
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        f"{self.base_url}/api/embed",
                        json=payload,
                    )
                response.raise_for_status()
                return response.json()
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                logger.warning(
                    "%s: embed call failed (attempt %d/%d): %s",
                    log_label, attempt, _MAX_RETRIES + 1, exc,
                )
                if attempt <= _MAX_RETRIES:
                    await asyncio.sleep(_BACKOFF_BASE_SECONDS * attempt)
                    continue
                raise EmbeddingServiceError(
                    f"{log_label}: embed call to {self.base_url}/api/embed failed after "
                    f"{_MAX_RETRIES + 1} attempts: {exc}"
                ) from exc
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "%s: Ollama returned %s: %s",
                    log_label, exc.response.status_code, exc.response.text[:300],
                )
                raise

        # Unreachable in practice (loop always returns or raises), kept
        # for type-checker satisfaction.
        raise EmbeddingServiceError(f"{log_label}: exhausted retries") from last_exc

    async def _embed_one(self, text: str) -> List[float]:
        data = await self._post_with_retry(
            payload={"model": self.model, "input": text},
            timeout=_SINGLE_TIMEOUT,
            log_label="embed_one",
        )
        return data["embeddings"][0]

    async def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Ollama /api/embed accepts a list in the input field.
        One HTTP call for the whole batch.
        """
        data = await self._post_with_retry(
            payload={"model": self.model, "input": texts},
            timeout=_BATCH_TIMEOUT,
            log_label="embed_batch",
        )
        return data["embeddings"]