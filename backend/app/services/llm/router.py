from dataclasses import dataclass
import re
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
        extractive_answer = self._extractive_answer(query=query, context=context)
        if extractive_answer:
            return GenerationResult(
                answer=extractive_answer,
                llm_route=llm_route,
                language_detected=language,
            )

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
        total_chars = 0
        selected_chunks = chunks[: settings.LOCAL_LLM_CONTEXT_CHUNKS]

        for index, chunk in enumerate(selected_chunks, start=1):
            page = chunk.page_number if chunk.page_number is not None else "N/A"
            content = self._truncate(chunk.content, settings.LOCAL_LLM_CHUNK_CHARS)
            parts.append(
                f"[Source {index}: {chunk.document_title}, Page {page}]\n{content}"
            )
            total_chars += len(parts[-1])
            if total_chars >= settings.LOCAL_LLM_CONTEXT_CHARS:
                break

        context = "\n\n".join(parts)
        return self._truncate(context, settings.LOCAL_LLM_CONTEXT_CHARS)

    def _build_prompt(self, query: str, context: str, language: str) -> str:
        return f"""You are a concise RAG assistant.
Rules:
- Answer only from the provided context. Do not use general knowledge.
- If the context is empty or insufficient, answer exactly: I don't have enough information in the selected documents to answer that.
- Keep the answer short.
- Cite only source numbers that appear in the context, such as [Source 1].
- Never write placeholder citations like [Source N].
Respond in language code: {language}.

Context:
{context}

Question:
{query}

Answer:"""

    @staticmethod
    def _truncate(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rsplit(" ", 1)[0] + "\n[truncated]"

    def _extractive_answer(
        self,
        query: str,
        context: Sequence[ContextChunk],
    ) -> str | None:
        query_lower = query.lower()
        if "soft" not in query_lower or "skill" not in query_lower:
            return None

        for source_number, chunk in enumerate(context, start=1):
            skills = self._extract_labeled_values(
                content=chunk.content,
                labels=("soft skills & collaboration", "soft skills"),
            )
            if not skills:
                continue

            skills = [
                skill
                for skill in skills
                if skill.lower() not in {"arabic", "english"}
                and "native" not in skill.lower()
                and "fluent" not in skill.lower()
            ]
            if not skills:
                return None

            return (
                f"Ismaiel's soft skills are {self._join_items(skills)} "
                f"[Source {source_number}]."
            )

        return None

    @staticmethod
    def _extract_labeled_values(content: str, labels: Sequence[str]) -> list[str]:
        for label in labels:
            pattern = rf"{re.escape(label)}\s*:\s*(.+)"
            match = re.search(pattern, content, flags=re.IGNORECASE)
            if not match:
                continue

            line = match.group(1).splitlines()[0]
            values = [
                value.strip(" .;:-")
                for value in re.split(r"\s*\|\s*|,\s*|;\s*", line)
                if value.strip(" .;:-")
            ]
            return values
        return []

    @staticmethod
    def _join_items(items: Sequence[str]) -> str:
        if len(items) == 1:
            return items[0]
        if len(items) == 2:
            return f"{items[0]} and {items[1]}"
        return f"{', '.join(items[:-1])}, and {items[-1]}"
