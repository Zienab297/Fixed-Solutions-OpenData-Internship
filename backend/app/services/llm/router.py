from dataclasses import dataclass
from typing import Mapping, Sequence

from app.core.config import settings
from app.schemas.query import ContextChunk, RouteName
from app.services.llm.external_llm import ExternalLLMService
from app.services.llm.language_detector import detect_language
from app.services.llm.local_llm import LocalLLMService


VALID_ROUTES = {"local", "api"}


@dataclass(frozen=True)
class GenerationResult:
    answer: str
    llm_route: RouteName
    language_detected: str


class LLMRouter:
    def __init__(
        self,
        local_llm: LocalLLMService | None = None,
        external_llm: ExternalLLMService | None = None,
    ) -> None:
        self.local_llm = local_llm or LocalLLMService()
        self.external_llm = external_llm or ExternalLLMService()

    def determine_route(
        self,
        domain_ids: Sequence[str],
        domain_routes: Mapping[str, str],
    ) -> RouteName:
        if not domain_ids:
            return "local"

        selected_routes: list[str] = []
        for domain_id in domain_ids:
            route = domain_routes.get(str(domain_id))
            if route not in VALID_ROUTES:
                return "local"
            selected_routes.append(route)

        if "local" in selected_routes:
            return "local"
        return "api"

    async def generate(
        self,
        query: str,
        context: Sequence[ContextChunk],
        domain_ids: Sequence[str],
        domain_routes: Mapping[str, str],
    ) -> GenerationResult:
        language = detect_language(query)
        llm_route = self.determine_route(domain_ids, domain_routes)
        context_text = self._build_context(context)
        prompt = self._build_prompt(query=query, context=context_text, language=language)

        if llm_route == "local":
            print(f"PROMPT LENGTH: {len(prompt)} chars", flush=True)
            answer = await self.local_llm.generate(prompt, model=settings.LOCAL_LLM_MODEL)
        else:
            print(f"PROMPT LENGTH: {len(prompt)} chars", flush=True)
            answer = await self.external_llm.generate(prompt)

        return GenerationResult(
            answer=answer,
            llm_route=llm_route,
            language_detected=language,
        )

    def _build_context(self, chunks: Sequence[ContextChunk]) -> str:
        if not chunks:
            return "No retrieved context was provided."

        parts = []
        for index, chunk in enumerate(chunks, start=1):
            page = chunk.page_number if chunk.page_number is not None else "N/A"
            parts.append(
                f"[Source {index}: {chunk.document_title}, Page {page}]\n{chunk.content}"
            )
        return "\n\n".join(parts)

    def _build_prompt(self, query: str, context: str, language: str) -> str:
        return f"""You are a RAG assistant.
Answer only from the provided context.
If the context is insufficient, say that clearly.
Respond in language code: {language}.
Cite sources with [Source N].

Context:
{context}

Question:
{query}

Answer:"""
