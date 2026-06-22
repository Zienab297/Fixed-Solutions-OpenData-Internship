"""
Judge LLM Service — async evaluation of generated answers (§4).
Separate from generation LLM to avoid resource contention.
"""
from dataclasses import dataclass
import json
import re
from typing import Any, List, Optional

import httpx

from app.core.config import settings


@dataclass
class JudgeEvaluationResult:
    faithfulness: float
    relevance: float
    completeness: float
    citation_accuracy: float
    rationale: dict
    raw_response: dict


class JudgeService:
    def __init__(self):
        self.judge_url = settings.JUDGE_LLM_BASE_URL.rstrip("/")
        self.model = settings.JUDGE_MODEL

    async def evaluate(
        self,
        query: str,
        context: List[dict],
        answer: str,
        graph_context: Optional[List[dict]] = None,
    ) -> JudgeEvaluationResult:
        """
        Run all 4 evaluation dimensions asynchronously.
        Returns structured scores + rationale for each.
        """
        prompt = self._build_judge_prompt(
            query=query,
            context=self._format_context(context),
            graph_context=self._format_graph_context(graph_context or []),
            answer=answer,
        )
        raw_response = await self._call_judge(prompt)
        return self._parse_response(raw_response)

    def _build_judge_prompt(
        self,
        query: str,
        context: str,
        graph_context: str,
        answer: str,
    ) -> str:
        return f"""You are an expert evaluator for a RAG (Retrieval-Augmented Generation) system.
Evaluate the answer on these 4 dimensions and respond ONLY with valid JSON.

QUERY: {query}

RETRIEVED CONTEXT:
{context}

GRAPH CONTEXT:
{graph_context}

ANSWER: {answer}

Evaluate and return ONLY this JSON structure (no other text):
{{
  "faithfulness": <0.0-1.0>,
  "faithfulness_rationale": "<brief explanation>",
  "relevance": <0.0-1.0>,
  "relevance_rationale": "<brief explanation>",
  "completeness": <0.0-1.0>,
  "completeness_rationale": "<brief explanation>",
  "citation_accuracy": <0.0-1.0>,
  "citation_accuracy_rationale": "<brief explanation>"
}}

Scoring guide:
- faithfulness: Is every claim in the answer supported by the context? (1.0 = fully grounded, 0.0 = hallucinated)
- relevance: Is the retrieved context relevant to the query? (1.0 = highly relevant, 0.0 = unrelated)
- completeness: Does the answer cover all key information in the context? (1.0 = complete, 0.0 = missing major points)
- citation_accuracy: Do inline citations [Source N] map to the correct context chunks? (1.0 = all correct, 0.0 = wrong/missing)"""

    async def _call_judge(self, prompt: str) -> dict:
        """Call the dedicated Ollama judge instance."""
        schema = {
            "type": "object",
            "properties": {
                "faithfulness": {"type": "number", "minimum": 0, "maximum": 1},
                "faithfulness_rationale": {"type": "string"},
                "relevance": {"type": "number", "minimum": 0, "maximum": 1},
                "relevance_rationale": {"type": "string"},
                "completeness": {"type": "number", "minimum": 0, "maximum": 1},
                "completeness_rationale": {"type": "string"},
                "citation_accuracy": {"type": "number", "minimum": 0, "maximum": 1},
                "citation_accuracy_rationale": {"type": "string"},
            },
            "required": [
                "faithfulness",
                "faithfulness_rationale",
                "relevance",
                "relevance_rationale",
                "completeness",
                "completeness_rationale",
                "citation_accuracy",
                "citation_accuracy_rationale",
            ],
        }
        timeout = httpx.Timeout(settings.JUDGE_TIMEOUT_SECONDS, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{self.judge_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "format": schema,
                    "options": {"temperature": 0},
                },
            )
            response.raise_for_status()
            return response.json()

    def _parse_response(self, raw: dict | str) -> JudgeEvaluationResult:
        """Parse JSON response from judge LLM."""
        try:
            raw_payload = raw if isinstance(raw, dict) else {"response": raw}
            response_text = raw_payload.get("response", raw)
            data = self._loads_json_response(response_text)
            return JudgeEvaluationResult(
                faithfulness=self._score(data.get("faithfulness")),
                relevance=self._score(data.get("relevance")),
                completeness=self._score(data.get("completeness")),
                citation_accuracy=self._score(data.get("citation_accuracy")),
                rationale={
                    "faithfulness": data.get("faithfulness_rationale", ""),
                    "relevance": data.get("relevance_rationale", ""),
                    "completeness": data.get("completeness_rationale", ""),
                    "citation_accuracy": data.get("citation_accuracy_rationale", ""),
                },
                raw_response=raw_payload,
            )
        except (TypeError, json.JSONDecodeError, KeyError, ValueError) as e:
            raise Exception(f"Failed to parse judge response: {e}")

    def _format_context(self, context: List[dict]) -> str:
        if not context:
            return "No retrieved context was provided."

        parts = []
        total_chars = 0
        for index, chunk in enumerate(context, start=1):
            source_number = chunk.get("source_number", index)
            page = chunk.get("page_number") or "N/A"
            section = chunk.get("section") or "N/A"
            domain = chunk.get("domain_name") or chunk.get("domain_id") or "N/A"
            chunk_id = chunk.get("chunk_id") or chunk.get("id") or "N/A"
            content = str(chunk.get("content", ""))
            entry = (
                f"[Source {source_number}]\n"
                f"chunk_id: {chunk_id}\n"
                f"title: {chunk.get('document_title', 'Unknown')}\n"
                f"page: {page}\n"
                f"section: {section}\n"
                f"domain: {domain}\n"
                f"relevance: {chunk.get('relevance_score', chunk.get('score', 0.0))}\n"
                f"content: {content}"
            )
            parts.append(entry)
            total_chars += len(entry)
            if total_chars >= settings.JUDGE_CONTEXT_CHARS:
                break
        return self._truncate("\n\n".join(parts), settings.JUDGE_CONTEXT_CHARS)

    def _format_graph_context(self, graph_context: List[dict]) -> str:
        if not graph_context:
            return "No graph context was provided."
        return self._truncate(json.dumps(graph_context, default=str), 2000)

    @staticmethod
    def _loads_json_response(response_text: Any) -> dict:
        if isinstance(response_text, dict):
            return response_text
        clean = str(response_text).strip()
        clean = clean.replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", clean, flags=re.DOTALL)
            if not match:
                raise
            return json.loads(match.group(0))

    @staticmethod
    def _score(value: Any) -> float:
        score = float(value)
        return min(1.0, max(0.0, score))

    @staticmethod
    def _truncate(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars].rsplit(" ", 1)[0] + "\n[truncated]"
