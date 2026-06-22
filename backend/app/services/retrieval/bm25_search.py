"""
BM25 keyword search using PostgreSQL full-text search.

Key improvements over original:
- Language detection via lingua — no hardcoded language list.
- ts_rank_cd with normalisation flag 32 (length penalty) instead of ts_rank.
- Queries the pre-built GIN-indexed content_tsv column — no inline to_tsvector().
- Postgres TS config resolved dynamically at query time from detected language.
- Graceful degradation: any DB error returns [] so pipeline keeps running.
"""

import logging
from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.services.retrieval.lang_detect import query_ts_config

logger = logging.getLogger(__name__)


class BM25SearchService:
    async def search(
        self,
        query: str,
        domain_ids: List[UUID],
        top_k: int = 10,
        db: AsyncSession = None,
        language: Optional[str] = None,   # ISO 639-1 override from upstream
    ) -> List[dict]:
        """
        BM25-style search using PostgreSQL tsvector / tsquery.

        language param is an ISO 639-1 code (e.g. "ar", "fr", "en").
        If None, we detect it from the query text via lingua.
        If detection confidence is too low, we fall back to 'rag_unaccent'.

        The Postgres TS config is resolved once per call — no hardcoded map,
        no per-language if/else. Any language Postgres natively supports works.
        """
        if not db or not query.strip():
            return []

        domain_id_strings = [str(d) for d in domain_ids]

        # Resolve config — dynamic, no hardcoded language list
        ts_cfg = query_ts_config(query, override=language)
        logger.debug("BM25 using TS config '%s' for query: %r", ts_cfg, query[:60])

        try:
            result = await db.execute(
                # ts_cfg comes from our own validated _PG_SUPPORTED_CONFIGS set,
                # never from raw user input — f-string interpolation is safe here.
                # The index was built with 'rag_unaccent'; querying with a language-
                # specific config (e.g. 'arabic') still matches because both
                # normalise through unaccent + lowercasing before token comparison.
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
                            plainto_tsquery('{ts_cfg}', :query),
                            32
                        ) AS score
                    FROM rag.chunks c
                    JOIN rag.domains   d   ON c.domain_id   = d.id
                    JOIN rag.documents doc ON c.document_id = doc.id
                    WHERE c.domain_id::text = ANY(:domain_ids)
                      AND c.content_tsv @@ plainto_tsquery('{ts_cfg}', :query)
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
            logger.warning("BM25 search failed (config=%s): %s", ts_cfg, exc)
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
