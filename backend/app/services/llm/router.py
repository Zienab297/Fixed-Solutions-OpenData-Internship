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
        # PATCHED — the old "If the context is ... insufficient" rule gave
        # the model zero guidance on what "insufficient" means, so it was
        # free to demand literal/verbatim phrasing before answering. A
        # chunk like "LAB 8 INTELLIGENT SYSTEMS Eng. Mariam Rashad" never
        # uses the words "created" or "author", so a cautious model could
        # (and intermittently did) refuse a question like "who created
        # lab 8" even with the right chunk sitting right there — the
        # refusal is a real LLM output each time, not a retrieval miss,
        # and a borderline judgment call like this can land differently
        # run to run even at temperature 0.0 depending on the inference
        # engine. The fix is giving the model an explicit, worked example
        # of the kind of direct inference it SHOULD make (a name next to
        # a title/heading answers "who made this"), while keeping the
        # refusal behavior for genuinely unrelated/missing context.
        return f"""You are a concise RAG assistant.

Rules:
- Answer only using facts stated or directly implied in the provided context. Do not use outside/general knowledge.
- Make reasonable, direct inferences from the context. You do NOT need an exact phrase match — if the context clearly implies the answer, state it directly.
  Example: if a source reads "LAB 8 INTELLIGENT SYSTEMS  Eng. Mariam Rashad" and the question asks who created/made/wrote Lab 8, the correct answer is "Eng. Mariam Rashad" — a name attached to a title/heading like this identifies that person as the creator, even though the word "created" never appears.
- Only refuse when the context is genuinely empty, or covers a different topic entirely with nothing relevant to infer from. In that case, and ONLY in that case, answer exactly: I don't have enough information in the selected documents to answer that.
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