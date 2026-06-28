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
            evaluation_mode=self._evaluation_mode(query=query, answer=answer),
            context=self._format_context(context),
            graph_context=self._format_graph_context(graph_context or []),
            answer=answer,
        )
        raw_response = await self._call_judge(prompt)
        result = self._parse_response(raw_response)
        result = self._apply_refusal_calibration(
            result=result,
            query=query,
            context=context,
            answer=answer,
        )
        return self._apply_numeric_lookup_calibration(
            result=result,
            query=query,
            context=context,
            answer=answer,
        )

    def _build_judge_prompt(
        self,
        query: str,
        evaluation_mode: str,
        context: str,
        graph_context: str,
        answer: str,
    ) -> str:
        return f"""You are an expert evaluator for a RAG (Retrieval-Augmented Generation) system.
Evaluate the answer on these 4 dimensions and respond ONLY with valid JSON.
Score the answer against the user's query, not against every fact in the retrieved context.

QUERY: {query}

EVALUATION MODE: {evaluation_mode}

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
- faithfulness: Is every claim in the answer supported by the retrieved context? Give 1.0 when all answer claims are grounded. Lower the score only for a specific unsupported or contradicted claim.
- relevance: Is the retrieved context relevant to the query? Give 1.0 when the cited/retrieved source directly contains the information needed to answer.
- completeness: Does the answer satisfy the user's exact request? Do not penalize an answer for omitting extra context the user did not ask for.
- citation_accuracy: Do inline citations [Source N] map to source chunks that actually contain the cited claim or value?

Special rules for exact lookup, table, numeric, amount, rate, date, or identifier questions:
- Grade completeness against the requested value/cell/field only, not against the whole table or document.
- A concise answer with the requested value and a correct citation can receive 1.0 for faithfulness, completeness, relevance, and citation accuracy.
- Do not use generic middle scores such as 0.7 or 0.8 unless there is a concrete defect.
- If the answer cites [Source N], verify that Source N contains the quoted number/value. If the value is not in that cited source, citation_accuracy must be below 0.7.
- If the question appears to ask for one value but the answer gives multiple competing values, lower completeness and explain the ambiguity.

Special rules for refusal answers:
- If the answer says there is not enough information, completeness must be 0.0 because it did not answer the user's request.
- If the retrieved context contains direct evidence for the query, a refusal is contradicted by context: faithfulness must be below 0.7 and relevance should reflect that the retrieved context was relevant.
- If a refusal has no inline citations, citation_accuracy must be 0.0 for UI scoring, not 1.0 or not-applicable."""

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

    def _apply_refusal_calibration(
        self,
        result: JudgeEvaluationResult,
        query: str,
        context: List[dict],
        answer: str,
    ) -> JudgeEvaluationResult:
        if not self._is_refusal_answer(answer):
            return result

        check = self._refusal_context_check(query=query, context=context)
        result.raw_response["refusal_check"] = check

        result.completeness = 0.0
        if not self._cited_source_numbers(answer):
            result.citation_accuracy = 0.0
        else:
            result.citation_accuracy = min(result.citation_accuracy, 0.4)

        if check["context_appears_relevant"]:
            result.faithfulness = min(result.faithfulness, 0.6)
            result.relevance = max(result.relevance, 0.8)
            note = (
                "Refusal calibration found relevant retrieved context, so the "
                "answer's claim that there is not enough information is not fully supported."
            )
            self._append_rationale(result, "faithfulness", note)
            self._append_rationale(result, "relevance", note)
        else:
            result.relevance = min(result.relevance, 0.4)
            note = (
                "Refusal calibration kept completeness low because the answer "
                "does not answer the user's request."
            )

        self._append_rationale(result, "completeness", note)
        self._append_rationale(
            result,
            "citation_accuracy",
            "Refusal answers without supported inline citations are not awarded citation credit.",
        )
        return result

    def _refusal_context_check(self, query: str, context: List[dict]) -> dict:
        terms = self._query_terms(query)
        phrases = [
            f"{left} {right}"
            for left, right in zip(terms, terms[1:])
            if left and right
        ]
        best = {
            "context_appears_relevant": False,
            "matched_terms": [],
            "matched_phrases": [],
            "source_number": None,
        }
        for index, chunk in enumerate(context, start=1):
            source_number = self._safe_int(chunk.get("source_number"), index)
            content = str(chunk.get("content", "")).lower()
            matched_terms = [term for term in terms if term in content]
            matched_phrases = [phrase for phrase in phrases if phrase in content]
            relevant = bool(matched_phrases) or len(matched_terms) >= 2
            if not relevant:
                continue
            return {
                "context_appears_relevant": True,
                "matched_terms": matched_terms,
                "matched_phrases": matched_phrases,
                "source_number": source_number,
            }
        return best

    @staticmethod
    def _is_refusal_answer(answer: str) -> bool:
        answer_lower = answer.lower()
        refusal_phrases = (
            "don't have enough information",
            "do not have enough information",
            "not enough information",
            "cannot answer",
            "can't answer",
            "insufficient information",
        )
        return any(phrase in answer_lower for phrase in refusal_phrases)

    @staticmethod
    def _query_terms(query: str) -> list[str]:
        stopwords = {
            "a",
            "an",
            "and",
            "are",
            "for",
            "have",
            "his",
            "in",
            "is",
            "it",
            "of",
            "or",
            "that",
            "the",
            "this",
            "to",
            "what",
            "when",
            "where",
            "which",
            "who",
            "with",
        }
        seen = set()
        terms: list[str] = []
        for token in re.findall(r"[a-zA-Z0-9]+", query.lower()):
            if len(token) < 3 or token in stopwords or token in seen:
                continue
            terms.append(token)
            seen.add(token)
        return terms

    def _apply_numeric_lookup_calibration(
        self,
        result: JudgeEvaluationResult,
        query: str,
        context: List[dict],
        answer: str,
    ) -> JudgeEvaluationResult:
        check = self._numeric_lookup_check(query=query, context=context, answer=answer)
        if not check["is_numeric_lookup"] or not check["answer_values"]:
            return result

        result.raw_response["numeric_lookup_check"] = check

        if check["missing_from_context"]:
            missing = ", ".join(check["missing_from_context"])
            result.faithfulness = min(result.faithfulness, 0.65)
            result.completeness = min(result.completeness, 0.75)
            if check["cited_sources"]:
                result.citation_accuracy = min(result.citation_accuracy, 0.6)
            note = (
                f"Numeric lookup check found answer value(s) not present in the "
                f"retrieved context: {missing}."
            )
            self._append_rationale(result, "faithfulness", note)
            self._append_rationale(result, "completeness", note)
            self._append_rationale(result, "citation_accuracy", note)
            return result

        if check["missing_from_cited_sources"]:
            missing = ", ".join(check["missing_from_cited_sources"])
            result.faithfulness = min(result.faithfulness, 0.85)
            result.citation_accuracy = min(result.citation_accuracy, 0.6)
            note = (
                f"Numeric lookup check found answer value(s) in retrieved context "
                f"but not in the cited source(s): {missing}."
            )
            self._append_rationale(result, "faithfulness", note)
            self._append_rationale(result, "citation_accuracy", note)
            return result

        result.faithfulness = max(result.faithfulness, 0.95)
        result.relevance = max(result.relevance, 0.95)
        result.completeness = max(result.completeness, 0.95)
        if check["cited_sources"]:
            result.citation_accuracy = max(result.citation_accuracy, 0.95)

        note = (
            "Numeric lookup check verified that the answer value(s) are present "
            "in the cited retrieved source(s), so the exact lookup is complete."
        )
        self._append_rationale(result, "faithfulness", note)
        self._append_rationale(result, "relevance", note)
        self._append_rationale(result, "completeness", note)
        if check["cited_sources"]:
            self._append_rationale(result, "citation_accuracy", note)
        return result

    def _numeric_lookup_check(
        self,
        query: str,
        context: List[dict],
        answer: str,
    ) -> dict:
        answer_values = self._answer_value_tokens(query=query, answer=answer)
        cited_sources = self._cited_source_numbers(answer)
        source_values = self._source_value_index(context)
        all_context_values = set().union(*source_values.values()) if source_values else set()
        cited_values = set()
        for source_number in cited_sources:
            cited_values.update(source_values.get(source_number, set()))

        missing_from_context = [
            value for value in answer_values if value not in all_context_values
        ]
        missing_from_cited_sources = []
        if cited_sources:
            missing_from_cited_sources = [
                value
                for value in answer_values
                if value not in cited_values and value not in missing_from_context
            ]

        return {
            "is_numeric_lookup": self._is_numeric_lookup_query(query, answer),
            "answer_values": answer_values,
            "cited_sources": cited_sources,
            "missing_from_context": missing_from_context,
            "missing_from_cited_sources": missing_from_cited_sources,
        }

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

    def _evaluation_mode(self, query: str, answer: str) -> str:
        if self._is_numeric_lookup_query(query, answer):
            return (
                "exact_numeric_lookup - evaluate only whether the answer gives "
                "the requested value(s) with correct source support"
            )
        return "general_rag_answer"

    def _is_numeric_lookup_query(self, query: str, answer: str) -> bool:
        if not self._answer_value_tokens(query=query, answer=answer):
            return False

        query_lower = query.lower()
        lookup_phrases = (
            "what is the value",
            "what's the value",
            "what value",
            "which value",
            "how much",
            "what amount",
            "what number",
            "what rate",
            "what percentage",
            "what percent",
            "what is the wage",
            "what is the salary",
        )
        if any(phrase in query_lower for phrase in lookup_phrases):
            return True

        lookup_terms = ("value", "amount", "rate", "percentage", "percent", "wage", "salary", "tax")
        has_lookup_term = any(term in query_lower for term in lookup_terms)
        has_range_or_number = bool(re.search(r"\d[\d,]*(?:\.\d+)?", query))
        return has_lookup_term and has_range_or_number

    def _answer_value_tokens(self, query: str, answer: str) -> list[str]:
        query_values = set(self._numeric_tokens(query))
        return [
            value
            for value in self._numeric_tokens(self._strip_citations(answer))
            if value not in query_values
        ]

    def _source_value_index(self, context: List[dict]) -> dict[int, set[str]]:
        values_by_source: dict[int, set[str]] = {}
        for index, chunk in enumerate(context, start=1):
            source_number = self._safe_int(chunk.get("source_number"), index)
            content = str(chunk.get("content", ""))
            values_by_source.setdefault(source_number, set()).update(
                self._numeric_tokens(content)
            )
        return values_by_source

    @staticmethod
    def _numeric_tokens(text: str) -> list[str]:
        tokens = []
        seen = set()
        for match in re.finditer(r"(?<![\w])\$?\d[\d,]*(?:\.\d+)?%?", text):
            value = match.group(0).replace("$", "").replace(",", "").replace("%", "")
            if "." in value:
                value = value.rstrip("0").rstrip(".")
            value = value.lstrip("0") or "0"
            if value not in seen:
                tokens.append(value)
                seen.add(value)
        return tokens

    @staticmethod
    def _cited_source_numbers(answer: str) -> list[int]:
        sources = []
        seen = set()
        for match in re.finditer(r"\[Source\s+(\d+)\]", answer, flags=re.IGNORECASE):
            source_number = int(match.group(1))
            if source_number not in seen:
                sources.append(source_number)
                seen.add(source_number)
        return sources

    @staticmethod
    def _strip_citations(text: str) -> str:
        return re.sub(r"\[Source\s+\d+\]", "", text, flags=re.IGNORECASE)

    @staticmethod
    def _safe_int(value: Any, fallback: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return fallback

    @staticmethod
    def _append_rationale(
        result: JudgeEvaluationResult,
        key: str,
        note: str,
    ) -> None:
        existing = result.rationale.get(key, "")
        if note in existing:
            return
        result.rationale[key] = f"{existing} {note}".strip()

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
