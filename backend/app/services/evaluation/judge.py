"""
Judge LLM Service — async evaluation of generated answers (§4).
Separate from generation LLM to avoid resource contention.
"""
from dataclasses import dataclass
from typing import List, Optional
import httpx
import json
from app.core.config import settings


@dataclass
class EvaluationResult:
    faithfulness: float
    relevance: float
    completeness: float
    citation_accuracy: float
    rationale: dict


class JudgeService:
    def __init__(self):
        # Judge uses separate Ollama instance (different port or service name)
        self.judge_url = settings.OLLAMA_BASE_URL.replace(":11434", ":11435")
        # Falls back to same instance if separate not configured
        self.fallback_url = settings.OLLAMA_BASE_URL

    async def evaluate(
        self,
        query: str,
        context: List[dict],
        answer: str,
    ) -> EvaluationResult:
        """
        Run all 4 evaluation dimensions asynchronously.
        Returns structured scores + rationale for each.
        """
        context_text = "\n\n".join(c.get("content", "") for c in context)

        prompt = self._build_judge_prompt(query, context_text, answer)

        try:
            raw_response = await self._call_judge(prompt)
            return self._parse_response(raw_response)
        except Exception as e:
            # Never let judge failure affect the user-facing response
            return EvaluationResult(
                faithfulness=0.0,
                relevance=0.0,
                completeness=0.0,
                citation_accuracy=0.0,
                rationale={"error": str(e)},
            )

    def _build_judge_prompt(self, query: str, context: str, answer: str) -> str:
        return f"""You are an expert evaluator for a RAG (Retrieval-Augmented Generation) system.
Evaluate the answer on these 4 dimensions and respond ONLY with valid JSON.

QUERY: {query}

CONTEXT:
{context}

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

    async def _call_judge(self, prompt: str) -> str:
        """Call judge LLM — tries dedicated instance first, falls back to shared."""
        for url in [self.judge_url, self.fallback_url]:
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.post(
                        f"{url}/api/generate",
                        json={
                            "model": settings.JUDGE_MODEL,
                            "prompt": prompt,
                            "stream": False,
                        },
                    )
                    response.raise_for_status()
                    return response.json()["response"]
            except Exception:
                continue
        raise Exception("Judge LLM unavailable")

    def _parse_response(self, raw: str) -> EvaluationResult:
        """Parse JSON response from judge LLM."""
        try:
            # Strip any markdown fences
            clean = raw.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(clean)
            return EvaluationResult(
                faithfulness=float(data.get("faithfulness", 0.0)),
                relevance=float(data.get("relevance", 0.0)),
                completeness=float(data.get("completeness", 0.0)),
                citation_accuracy=float(data.get("citation_accuracy", 0.0)),
                rationale={
                    "faithfulness": data.get("faithfulness_rationale", ""),
                    "relevance": data.get("relevance_rationale", ""),
                    "completeness": data.get("completeness_rationale", ""),
                    "citation_accuracy": data.get("citation_accuracy_rationale", ""),
                },
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            raise Exception(f"Failed to parse judge response: {e}")
