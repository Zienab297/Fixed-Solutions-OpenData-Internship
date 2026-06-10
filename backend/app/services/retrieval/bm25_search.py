"""
BM25 keyword search using PostgreSQL full-text search.
Complements vector search for exact keyword and code matches.
"""
from typing import List
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


class BM25SearchService:
    async def search(
        self, query: str, domain_ids: List[UUID], top_k: int = 10, db: AsyncSession = None
    ) -> List[dict]:
        """
        BM25-style search using PostgreSQL tsvector/tsquery.
        Falls back gracefully if no results found.
        """
        if not db:
            return []

        # FIX: pass domain_ids as a plain Python list — SQLAlchemy + asyncpg
        # will bind it correctly. Do NOT use ::uuid[] cast inline in the SQL
        # because asyncpg translates named params to $N positional params first,
        # leaving the bare ::uuid[] cast as invalid syntax.
        domain_id_strings = [str(d) for d in domain_ids]

        result = await db.execute(
            text("""
                SELECT
                    c.id,
                    c.content,
                    c.page_number,
                    c.section,
                    c.domain_id,
                    d.name as domain_name,
                    doc.title as document_title,
                    c.created_at,
                    ts_rank(to_tsvector('simple', c.content), plainto_tsquery('simple', :query)) as score
                FROM rag.chunks c
                JOIN rag.domains d ON c.domain_id = d.id
                JOIN rag.documents doc ON c.document_id = doc.id
                WHERE c.domain_id::text = ANY(:domain_ids)
                AND to_tsvector('simple', c.content) @@ plainto_tsquery('simple', :query)
                ORDER BY score DESC
                LIMIT :top_k
            """),
            {"query": query, "domain_ids": domain_id_strings, "top_k": top_k},
        )

        rows = result.fetchall()
        return [
            {
                "id": str(row.id),
                "score": float(row.score),
                "content": row.content,
                "document_title": row.document_title,
                "page_number": row.page_number,
                "section": row.section,
                "domain_id": str(row.domain_id),
                "domain_name": row.domain_name,
                "created_at": str(row.created_at),
            }
            for row in rows
        ]