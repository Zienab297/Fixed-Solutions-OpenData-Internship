"""
LLM Router — decides whether to use local Ollama or external API model.
Routing rules configurable per domain by domain admins.
"""
from dataclasses import dataclass
from typing import List
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.config import settings
from app.services.llm.local_llm import LocalLLMService
from app.services.llm.external_llm import ExternalLLMService
from app.services.llm.language_detector import detect_language


@dataclass
class GenerationResult:
    answer: str
    llm_route: str      # 'local' or 'api'
    language_detected: str


class LLMRouter:
    def __init__(self):
        self.local_llm = LocalLLMService()
        self.external_llm = ExternalLLMService()

    async def generate(
        self,
        query: str,
        context: List[dict],
        domain_ids: List[UUID],
        db: AsyncSession,
    ) -> GenerationResult:
        """
        Route query to appropriate LLM based on domain configuration.
        Local model for sensitive domains, API model for general queries.
        """
        # Detect query language for multilingual response
        language = detect_language(query)

        # Determine routing based on domain config
        llm_route = await self._determine_route(domain_ids, db)

        # Build context string from retrieved chunks
        context_text = self._build_context(context)

        # Generate answer in detected language
        prompt = self._build_prompt(query, context_text, language)

        if llm_route == "local":
            answer = await self.local_llm.generate(prompt, model=settings.GENERATION_MODEL)
        else:
            answer = await self.external_llm.generate(prompt)

        return GenerationResult(
            answer=answer,
            llm_route=llm_route,
            language_detected=language,
        )

    async def _determine_route(self, domain_ids: List[UUID], db: AsyncSession) -> str:
        """
        Check domain configurations for LLM routing preference.
        If any domain requires local, use local (most restrictive wins).
        """
        result = await db.execute(
            text("""
                SELECT llm_route FROM rag.domains
                WHERE id = ANY(:domain_ids::uuid[])
            """),
            {"domain_ids": [str(d) for d in domain_ids]},
        )
        routes = [row.llm_route for row in result.fetchall()]

        if "local" in routes:
            return "local"
        if "api" in routes:
            return "api"
        return "local"  # default to local for safety

    def _build_context(self, chunks: List[dict]) -> str:
        """Assemble retrieved chunks into context string with source markers."""
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            context_parts.append(
                f"[Source {i}: {chunk.get('document_title', 'Unknown')}, "
                f"Page {chunk.get('page_number', 'N/A')}]\n{chunk.get('content', '')}"
            )
        return "\n\n".join(context_parts)

    def _build_prompt(self, query: str, context: str, language: str) -> str:
        return f"""You are a helpful assistant. Answer the user's question based ONLY on the provided context.
If the context doesn't contain enough information, say so clearly.
Always respond in {language}.
Cite sources using [Source N] notation inline.

Context:
{context}

Question: {query}

Answer:"""
