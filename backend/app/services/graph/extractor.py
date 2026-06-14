"""Graph extraction placeholder.

The ingestion worker already queues this task after documents are embedded, but
graph extraction itself is not implemented yet. Keep a no-op class here so the
worker can complete cleanly until the real extractor lands.
"""
from __future__ import annotations


class GraphExtractor:
    async def extract_and_store(self, document_id: str, domain_id: str) -> None:
        return None
