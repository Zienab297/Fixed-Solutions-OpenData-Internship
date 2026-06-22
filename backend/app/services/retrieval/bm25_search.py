"""
BM25 keyword search using PostgreSQL full-text search.

Key improvements over original:
- ts_rank_cd with normalisation flag 32 (length penalty) instead of ts_rank.
- Queries the pre-built GIN-indexed content_tsv column — no inline to_tsvector().
- Graceful degradation: any DB error returns [] so pipeline keeps running.


The query-side config MUST match whatever config content_tsv was
built with. There is no per-language detection here anymore — if you
need genuine multilingual stemming, that requires multiple stored
tsvector columns (one per config) generated at ingestion, with the
query picking which column to hit, not swapping the config against a
single fixed-config column.
"""

import logging
from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Must match the Postgres TS config content_tsv was generated with at
# ingestion time. Do not resolve this dynamically per query language —
# see module docstring for why that breaks tsvector/tsquery matching.
_TS_CONFIG = "rag_unaccent"


class BM25SearchService:
    async def search(
        self,
        query: str,
        domain_ids: List[UUID],
        top_k: int = 5,
        db: AsyncSession = None,
        language: Optional[str] = None,   # ISO 639-1 override from upstream
    ) -> List[dict]:
        """
        BM25-style search using PostgreSQL tsvector / tsquery.

        language param is accepted for API compatibility with callers
        (pipeline.py passes the detected query language through) but is
        intentionally UNUSED for TS config selection — see module
        docstring. content_tsv was built with a single fixed config
        ('rag_unaccent'); querying with any other config would silently
        return near-zero results due to lexeme mismatch. If per-language
        stemming is needed later, it requires additional stored tsvector
        columns at ingestion, not a query-side config swap here.
        """
        if not db or not query.strip():
            return []

        domain_id_strings = [str(d) for d in domain_ids]

        try:
            result = await db.execute(
                # _TS_CONFIG is a fixed module constant, never user input —
                # f-string interpolation is safe here. It MUST match the
                # config content_tsv was generated with at ingestion.
                text(f"""
                    SELECT
                        c.id,
                        c.content,
                        c.page_number,
                        c.section,
                        c.domain_id,
                        d.name            AS domain_name,
                        doc.title         AS document_title,
                        c.created_at,
                        ts_rank_cd(
                            c.content_tsv,
                            plainto_tsquery('{_TS_CONFIG}', :query),
                            32
                        ) AS score
                    FROM rag.chunks c
                    JOIN rag.domains   d   ON c.domain_id   = d.id
                    JOIN rag.documents doc ON c.document_id = doc.id
                    WHERE c.domain_id::text = ANY(:domain_ids)
                      AND c.content_tsv @@ plainto_tsquery('{_TS_CONFIG}', :query)
                    ORDER BY score DESC
                    LIMIT :top_k
                """),
                {
                    "query":      query,
                    "domain_ids": domain_id_strings,
                    "top_k":      top_k,
                },
            )
        except Exception as exc:
            logger.warning("BM25 search failed (config=%s): %s", _TS_CONFIG, exc)
            return []

        rows = result.fetchall()
        return [
            {
                "id":             str(row.id),
                "score":          float(row.score),
                "content":        row.content,
                "document_title": row.document_title,
                "page_number":    row.page_number,
                "section":        row.section,
                "domain_id":      str(row.domain_id),
                "domain_name":    row.domain_name,
                "created_at":     str(row.created_at),
            }
            for row in rows
        ]