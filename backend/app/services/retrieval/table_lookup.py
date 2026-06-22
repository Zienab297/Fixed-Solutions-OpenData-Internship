"""Structured CSV table QA backed by Postgres JSONB rows.

CSV questions should be computed over the full table, not answered from a few
retrieved chunks. This module loads rows from rag.table_rows, backfills older
CSV uploads from chunk metadata/text when needed, validates the intended table
operation, executes it in Python, and returns grounded citations.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class TableLookupResult:
    answer: str
    chunks: list[dict]
    confidence_score: float = 1.0
    signals_used: list[str] | None = None


@dataclass
class CsvRow:
    row_number: int | None
    values: dict[str, str]
    chunk: dict


@dataclass
class FilterSpec:
    column: str
    mode: str
    value: Any


@dataclass
class LookupIntent:
    return_column: str | None
    condition_column: str
    condition_value: str


class CsvTableLookupService:
    async def lookup(
        self,
        query: str,
        domain_ids: list[UUID],
        db: AsyncSession,
    ) -> TableLookupResult | None:
        if not _has_table_intent(query):
            return None

        rows = await self._load_rows(domain_ids, db)
        if not rows:
            return None

        rows = _dedupe_rows_by_document_row(rows)
        columns = _collect_columns([row.values for row in rows])

        return (
            self._answer_remote_comparison(query, rows, columns)
            or self._answer_exact_lookup(query, rows, columns)
            or self._answer_salary_range(query, rows, columns)
            or self._answer_grouped_numeric(query, rows, columns)
            or self._answer_extreme(query, rows, columns)
            or self._answer_common_group(query, rows, columns)
            or self._answer_count(query, rows, columns)
            or self._answer_average(query, rows, columns)
            or self._answer_examples(query, rows, columns)
        )

    async def search_context(
        self,
        query: str,
        domain_ids: list[UUID],
        db: AsyncSession,
        top_k: int = 5,
    ) -> list[dict]:
        rows = await self._load_rows(domain_ids, db)
        if not rows:
            return []

        terms = _query_terms(query)
        if not terms:
            return []

        scored_rows: list[tuple[float, CsvRow]] = []
        for row in rows:
            row_text = _row_search_text(row)
            score = sum(1.0 for term in terms if _phrase_in_query(term, row_text))
            score += _structured_row_score(query, row)
            if score > 0:
                scored_rows.append((score, row))

        if not scored_rows:
            return []

        scored_rows.sort(key=lambda item: (-item[0], item[1].row_number or 999999))
        return _dedupe_chunks([row.chunk | {"score": score} for score, row in scored_rows[:top_k]])

    async def _load_rows(self, domain_ids: list[UUID], db: AsyncSession) -> list[CsvRow]:
        await _ensure_table_rows_schema(db)

        rows = await self._load_rows_from_table(domain_ids, db)
        if rows:
            return rows

        rows = await self._load_rows_from_chunks(domain_ids, db)
        if rows:
            await _backfill_table_rows(rows, db)
        return rows

    async def _load_rows_from_table(
        self,
        domain_ids: list[UUID],
        db: AsyncSession,
    ) -> list[CsvRow]:
        domain_id_strings = [str(domain_id) for domain_id in domain_ids]
        result = await db.execute(
            text(
                """
                SELECT
                    tr.row_number,
                    tr.row_data,
                    c.id,
                    c.document_id,
                    c.content,
                    c.page_number,
                    c.section,
                    c.domain_id,
                    d.name as domain_name,
                    doc.title as document_title,
                    c.created_at
                FROM rag.table_rows tr
                JOIN rag.chunks c ON c.id = tr.chunk_id
                JOIN rag.domains d ON c.domain_id = d.id
                JOIN rag.documents doc ON c.document_id = doc.id
                WHERE tr.domain_id::text = ANY(:domain_ids)
                  AND doc.source_type = 'csv'
                  AND doc.ingest_status = 'completed'
                ORDER BY doc.created_at DESC, tr.row_number ASC
                LIMIT 50000
                """
            ),
            {"domain_ids": domain_id_strings},
        )

        loaded: list[CsvRow] = []
        for row in result.fetchall():
            row_data = row.row_data
            if isinstance(row_data, str):
                row_data = json.loads(row_data)
            if not isinstance(row_data, dict):
                continue
            loaded.append(
                CsvRow(
                    row_number=row.row_number,
                    values={str(key): str(value) for key, value in row_data.items()},
                    chunk=_chunk_dict(row),
                )
            )
        return loaded

    async def _load_rows_from_chunks(
        self,
        domain_ids: list[UUID],
        db: AsyncSession,
    ) -> list[CsvRow]:
        domain_id_strings = [str(domain_id) for domain_id in domain_ids]
        result = await db.execute(
            text(
                """
                SELECT
                    c.id,
                    c.document_id,
                    c.content,
                    c.page_number,
                    c.section,
                    c.domain_id,
                    c.metadata,
                    d.name as domain_name,
                    doc.title as document_title,
                    c.created_at
                FROM rag.chunks c
                JOIN rag.domains d ON c.domain_id = d.id
                JOIN rag.documents doc ON c.document_id = doc.id
                WHERE c.domain_id::text = ANY(:domain_ids)
                  AND doc.source_type = 'csv'
                  AND doc.ingest_status = 'completed'
                ORDER BY doc.created_at DESC, c.chunk_index ASC
                LIMIT 10000
                """
            ),
            {"domain_ids": domain_id_strings},
        )

        loaded: list[CsvRow] = []
        for chunk_row in result.fetchall():
            chunk = _chunk_dict(chunk_row)
            metadata = chunk_row.metadata or {}
            extracted_rows = _rows_from_metadata(metadata)
            if not extracted_rows:
                extracted_rows = _rows_from_content(chunk_row.content)

            for row_number, values in extracted_rows:
                loaded.append(CsvRow(row_number=row_number, values=values, chunk=chunk))

        return loaded

    def _answer_remote_comparison(
        self,
        query: str,
        rows: list[CsvRow],
        columns: list[str],
    ) -> TableLookupResult | None:
        remote_column = _find_column(columns, "remote")
        if not remote_column:
            return None

        normalized = _normalize_text(query)
        compares_remote = "remote" in normalized and (
            "non remote" in normalized
            or "not remote" in normalized
            or "onsite" in normalized
            or "on site" in normalized
            or "more common" in normalized
            or "common" in normalized
        )
        if not compares_remote:
            return None

        filters = _filters_for_query(query, rows, columns, include_remote=False)
        matches = _apply_filters(rows, filters)
        if not matches:
            return None

        remote_rows = [row for row in matches if _as_bool(row.values.get(remote_column))]
        non_remote_rows = [row for row in matches if _as_bool(row.values.get(remote_column)) is False]
        if not remote_rows and not non_remote_rows:
            return None

        if len(remote_rows) > len(non_remote_rows):
            winner = "Remote jobs"
        elif len(non_remote_rows) > len(remote_rows):
            winner = "Non-remote jobs"
        else:
            winner = "Remote and non-remote jobs are tied"

        answer = (
            f"{winner} are more common in the matching CSV rows: "
            f"{len(non_remote_rows):,} non-remote vs {len(remote_rows):,} remote "
            f"out of {len(matches):,} rows counted."
        )
        chunks = _chunks_for_rows(matches)
        return TableLookupResult(answer, chunks, signals_used=["table", "csv_query_plan"])

    def _answer_exact_lookup(
        self,
        query: str,
        rows: list[CsvRow],
        columns: list[str],
    ) -> TableLookupResult | None:
        intent = _parse_exact_lookup_intent(query, columns, rows)
        if not intent:
            return None

        matches = [
            row
            for row in rows
            if _values_equal(row.values.get(intent.condition_column, ""), intent.condition_value)
        ]
        if not matches:
            return None

        if not intent.return_column:
            answer = _format_row_summary(matches[:5])
        else:
            values = _unique(
                [
                    row.values.get(intent.return_column, "").strip()
                    for row in matches
                    if row.values.get(intent.return_column, "").strip()
                ]
            )
            if not values:
                answer = _format_row_summary(matches[:5])
            elif len(values) == 1:
                answer = (
                    f"The {intent.return_column.lower()} is {values[0]}"
                    f"{_row_hint(matches[0])}."
                )
            else:
                answer = (
                    f"The matching {intent.return_column.lower()} values are: "
                    f"{', '.join(values[:8])}{'...' if len(values) > 8 else ''}."
                )

        return TableLookupResult(
            answer=answer,
            chunks=_chunks_for_rows(matches),
            signals_used=["table", "csv_query_plan", "exact_lookup"],
        )

    def _answer_salary_range(
        self,
        query: str,
        rows: list[CsvRow],
        columns: list[str],
    ) -> TableLookupResult | None:
        normalized = _normalize_text(query)
        if "salary" not in normalized:
            return None
        if not any(word in normalized for word in ("range", "ranges", "common", "typical", "span")):
            return None

        filters = _filters_for_query(query, rows, columns)
        matches = _apply_filters(rows, filters)
        salary_column = _find_column(columns, "salary")
        average_column = _find_column(columns, "average salary")
        if not matches or not salary_column:
            return None

        rows_with_salary = [row for row in matches if row.values.get(salary_column, "").strip()]
        if not rows_with_salary:
            return None

        numbers = sorted(
            number
            for number in (_numeric_value(row.values.get(average_column or "", "")) for row in rows_with_salary)
            if number is not None
        )
        selected = _dedupe_rows_by_identity(rows_with_salary)[:6]
        chunks = _chunks_for_rows(selected)
        source_numbers = _source_numbers(chunks)

        if numbers:
            summary = (
                f"Among {len(rows_with_salary):,} matching rows, listed average salaries "
                f"span {_format_numeric(numbers[0], average_column)} to "
                f"{_format_numeric(numbers[-1], average_column)}."
            )
        else:
            summary = f"Among {len(rows_with_salary):,} matching rows, example listed ranges include:"

        lines = []
        for index, row in enumerate(selected, start=1):
            source = source_numbers.get(str(row.chunk.get("id")), 1)
            lines.append(f"{index}. {_format_row_brief(row)} [Source {source}]")

        return TableLookupResult(
            answer=summary + "\n" + "\n".join(lines),
            chunks=chunks,
            signals_used=["table", "csv_query_plan", "range"],
        )

    def _answer_grouped_numeric(
        self,
        query: str,
        rows: list[CsvRow],
        columns: list[str],
    ) -> TableLookupResult | None:
        normalized = _normalize_text(query)
        target_column = _resolve_numeric_column(query, columns, rows)
        group_column = _resolve_group_column(query, columns)
        if not target_column or not group_column:
            return None
        if " by " not in f" {normalized} " and not (
            _has_extreme_word(normalized) and group_column in {_find_column(columns, "city"), _find_column(columns, "state"), _find_column(columns, "remote")}
        ):
            return None

        filters = _filters_for_query(query, rows, columns)
        filters = [flt for flt in filters if flt.column != group_column]
        matches = _apply_filters(rows, filters)
        grouped: dict[str, list[float]] = {}
        group_rows: dict[str, list[CsvRow]] = {}
        for row in matches:
            key = row.values.get(group_column, "").strip() or "Unknown"
            number = _numeric_value(row.values.get(target_column, ""))
            if number is None:
                continue
            grouped.setdefault(key, []).append(number)
            group_rows.setdefault(key, []).append(row)

        if not grouped:
            return None

        aggregate_name = "average"
        scored = [
            (sum(values) / len(values), key, len(values))
            for key, values in grouped.items()
        ]
        descending = not _has_lowest_word(normalized)
        scored.sort(key=lambda item: item[0], reverse=descending)
        limit = min(_extract_limit(query, default=5), len(scored))
        selected = scored[:limit]

        metric = _metric_label(target_column)
        lines = [
            f"{index}. {key}: {_format_numeric(value, target_column)} average {metric} "
            f"across {_row_count_label(count)}"
            for index, (value, key, count) in enumerate(selected, start=1)
        ]
        citation_rows = []
        for _, key, _ in selected:
            citation_rows.extend(group_rows.get(key, [])[:2])

        direction = "highest" if descending else "lowest"
        answer = (
            f"Grouped by {group_column}, the {direction} average {metric} values are:\n"
            + "\n".join(lines)
        )
        return TableLookupResult(
            answer=answer,
            chunks=_chunks_for_rows(citation_rows),
            signals_used=["table", "csv_query_plan", "grouped_numeric"],
        )

    def _answer_extreme(
        self,
        query: str,
        rows: list[CsvRow],
        columns: list[str],
    ) -> TableLookupResult | None:
        normalized = _normalize_text(query)
        if not _has_extreme_word(normalized):
            return None

        target_column = _resolve_numeric_column(query, columns, rows)
        if not target_column:
            return None

        filters = _filters_for_query(query, rows, columns)
        matches = _apply_filters(rows, filters)
        scored = [
            (number, row)
            for row in matches
            if (number := _numeric_value(row.values.get(target_column, ""))) is not None
        ]
        if not scored:
            return None

        descending = not _has_lowest_word(normalized)
        scored.sort(key=lambda item: item[0], reverse=descending)
        limit = _extract_limit(query, default=1 if "top" not in normalized else 5)
        selected_pairs = scored[:limit]
        selected_rows = [row for _, row in selected_pairs]
        return_column = _resolve_return_column(query, columns, exclude={target_column})
        chunks = _chunks_for_rows(selected_rows)
        source_numbers = _source_numbers(chunks)

        if limit == 1:
            value, row = selected_pairs[0]
            source = source_numbers.get(str(row.chunk.get("id")), 1)
            if return_column:
                returned = row.values.get(return_column, "").strip() or "Unknown"
                answer = (
                    f"The {return_column.lower()} with the "
                    f"{'lowest' if not descending else 'highest'} {target_column.lower()} "
                    f"is {returned}, with {target_column} "
                    f"{_format_numeric(value, target_column)}{_row_hint(row)} [Source {source}]."
                )
            else:
                answer = (
                    f"The {'lowest' if not descending else 'highest'} {target_column.lower()} "
                    f"is {_format_numeric(value, target_column)} for {_format_row_brief(row)} "
                    f"[Source {source}]."
                )
        else:
            lines = []
            for index, (value, row) in enumerate(selected_pairs, start=1):
                source = source_numbers.get(str(row.chunk.get("id")), 1)
                lines.append(
                    f"{index}. {_format_row_brief(row)}; {target_column}: "
                    f"{_format_numeric(value, target_column)} [Source {source}]"
                )
            answer = (
                f"The top {len(selected_pairs)} rows by {target_column.lower()} are:\n"
                + "\n".join(lines)
            )

        return TableLookupResult(
            answer=answer,
            chunks=chunks,
            signals_used=["table", "csv_query_plan", "extreme"],
        )

    def _answer_common_group(
        self,
        query: str,
        rows: list[CsvRow],
        columns: list[str],
    ) -> TableLookupResult | None:
        normalized = _normalize_text(query)
        wants_common = any(
            phrase in normalized
            for phrase in ("most common", "least common", "common", "frequent", "popular")
        )
        if not wants_common:
            return None
        if "salary" in normalized and "range" in normalized:
            return None

        group_column = _resolve_group_column(query, columns)
        if not group_column:
            return None

        filters = [flt for flt in _filters_for_query(query, rows, columns) if flt.column != group_column]
        matches = _apply_filters(rows, filters)
        if not matches:
            return None

        counts: dict[str, int] = {}
        group_rows: dict[str, list[CsvRow]] = {}
        for row in matches:
            key = _display_value(row.values.get(group_column, "")) or "Unknown"
            counts[key] = counts.get(key, 0) + 1
            group_rows.setdefault(key, []).append(row)

        if not counts:
            return None

        descending = "least" not in normalized
        ranked = sorted(counts.items(), key=lambda item: item[1], reverse=descending)
        limit = min(_extract_limit(query, default=5), len(ranked))
        selected = ranked[:limit]
        lines = [
            f"{index}. {value}: {count:,} rows"
            for index, (value, count) in enumerate(selected, start=1)
        ]
        citation_rows = []
        for value, _ in selected:
            citation_rows.extend(group_rows.get(value, [])[:2])

        label = "most common" if descending else "least common"
        answer = f"The {label} {group_column.lower()} values are:\n" + "\n".join(lines)
        return TableLookupResult(
            answer=answer,
            chunks=_chunks_for_rows(citation_rows),
            signals_used=["table", "csv_query_plan", "group_count"],
        )

    def _answer_count(
        self,
        query: str,
        rows: list[CsvRow],
        columns: list[str],
    ) -> TableLookupResult | None:
        normalized = _normalize_text(query)
        if not any(phrase in normalized for phrase in ("how many", "number of", "count")):
            return None

        filters = _filters_for_query(query, rows, columns)
        matches = _apply_filters(rows, filters)
        subject = _filter_description(filters) or "matching rows"
        if filters:
            answer = f"There are {len(matches):,} rows matching {subject} in the CSV."
        else:
            answer = f"There are {len(matches):,} rows in the CSV."
        return TableLookupResult(
            answer=answer,
            chunks=_chunks_for_rows(matches),
            signals_used=["table", "csv_query_plan", "count"],
        )

    def _answer_average(
        self,
        query: str,
        rows: list[CsvRow],
        columns: list[str],
    ) -> TableLookupResult | None:
        normalized = _normalize_text(query)
        if not any(word in normalized for word in ("average", "avg", "mean")):
            return None
        if _has_extreme_word(normalized):
            return None

        target_column = _resolve_numeric_column(query, columns, rows)
        if not target_column:
            return None

        filters = _filters_for_query(query, rows, columns)
        matches = _apply_filters(rows, filters)
        numbers = [
            number
            for number in (_numeric_value(row.values.get(target_column, "")) for row in matches)
            if number is not None
        ]
        if not numbers:
            return None

        average = sum(numbers) / len(numbers)
        subject = _filter_description(filters) or "matching rows"
        metric = _metric_label(target_column)
        answer = (
            f"The average {metric} for {subject} is "
            f"{_format_numeric(average, target_column)} across {len(numbers):,} rows."
        )
        return TableLookupResult(
            answer=answer,
            chunks=_chunks_for_rows(matches),
            signals_used=["table", "csv_query_plan", "average"],
        )

    def _answer_examples(
        self,
        query: str,
        rows: list[CsvRow],
        columns: list[str],
    ) -> TableLookupResult | None:
        normalized = _normalize_text(query)
        filters = _filters_for_query(query, rows, columns)
        asks_for_rows = any(
            word in normalized
            for word in ("example", "examples", "list", "show", "jobs", "roles", "which")
        )
        if not asks_for_rows and not filters:
            return None

        matches = _apply_filters(rows, filters)
        if not matches:
            return None

        limit = _extract_limit(query, default=5)
        selected = _dedupe_rows_by_identity(matches)[:limit]
        chunks = _chunks_for_rows(selected)
        source_numbers = _source_numbers(chunks)
        lines = []
        for index, row in enumerate(selected, start=1):
            source = source_numbers.get(str(row.chunk.get("id")), 1)
            lines.append(f"{index}. {_format_row_brief(row)} [Source {source}]")

        return TableLookupResult(
            answer=f"Matching CSV rows include:\n" + "\n".join(lines),
            chunks=chunks,
            signals_used=["table", "csv_query_plan", "filtered_rows"],
        )


async def _ensure_table_rows_schema(db: AsyncSession) -> None:
    await db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS rag.table_rows (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                document_id UUID NOT NULL REFERENCES rag.documents(id) ON DELETE CASCADE,
                domain_id UUID NOT NULL REFERENCES rag.domains(id) ON DELETE CASCADE,
                chunk_id UUID REFERENCES rag.chunks(id) ON DELETE SET NULL,
                row_number INTEGER NOT NULL,
                row_data JSONB NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (document_id, row_number)
            )
            """
        )
    )
    await db.execute(text("CREATE INDEX IF NOT EXISTS idx_table_rows_domain ON rag.table_rows(domain_id)"))
    await db.execute(text("CREATE INDEX IF NOT EXISTS idx_table_rows_document ON rag.table_rows(document_id)"))
    await db.execute(text("CREATE INDEX IF NOT EXISTS idx_table_rows_chunk ON rag.table_rows(chunk_id)"))
    await db.execute(text("CREATE INDEX IF NOT EXISTS idx_table_rows_data_gin ON rag.table_rows USING GIN (row_data)"))


async def _backfill_table_rows(rows: list[CsvRow], db: AsyncSession) -> None:
    for row in rows:
        document_id = row.chunk.get("document_id")
        domain_id = row.chunk.get("domain_id")
        chunk_id = row.chunk.get("id")
        if not document_id or not domain_id or not chunk_id or row.row_number is None:
            continue
        await db.execute(
            text(
                """
                INSERT INTO rag.table_rows (
                    document_id, domain_id, chunk_id, row_number, row_data
                )
                VALUES (
                    :document_id,
                    :domain_id,
                    :chunk_id,
                    :row_number,
                    CAST(:row_data AS jsonb)
                )
                ON CONFLICT (document_id, row_number)
                DO UPDATE SET
                    domain_id = EXCLUDED.domain_id,
                    chunk_id = EXCLUDED.chunk_id,
                    row_data = EXCLUDED.row_data
                """
            ),
            {
                "document_id": str(document_id),
                "domain_id": str(domain_id),
                "chunk_id": str(chunk_id),
                "row_number": row.row_number,
                "row_data": json.dumps({str(k): str(v) for k, v in row.values.items()}),
            },
        )


def _chunk_dict(row: Any) -> dict:
    return {
        "id": str(row.id),
        "document_id": str(row.document_id),
        "score": 1.0,
        "content": row.content,
        "document_title": row.document_title,
        "page_number": row.page_number,
        "section": row.section,
        "domain_id": str(row.domain_id),
        "domain_name": row.domain_name,
        "created_at": str(row.created_at),
    }


def _rows_from_metadata(metadata: dict) -> list[tuple[int | None, dict[str, str]]]:
    rows = metadata.get("rows")
    if not isinstance(rows, list):
        return []

    extracted: list[tuple[int | None, dict[str, str]]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        values = row.get("values")
        if not isinstance(values, dict):
            continue
        row_number = row.get("row_number")
        extracted.append(
            (
                row_number if isinstance(row_number, int) else None,
                {str(key): str(value) for key, value in values.items()},
            )
        )
    return extracted


def _rows_from_content(content: str) -> list[tuple[int | None, dict[str, str]]]:
    rows: list[tuple[int | None, dict[str, str]]] = []
    pattern = re.compile(r"Row\s+(\d+):\s*(.*?)(?=\s+Row\s+\d+:|$)", re.DOTALL)

    for match in pattern.finditer(content):
        row_number = int(match.group(1))
        row_text = match.group(2).strip()
        values = _parse_row_text(row_text)
        if values:
            rows.append((row_number, values))

    return rows


def _parse_row_text(row_text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    parts = [part.strip() for part in row_text.split(";") if part.strip()]

    for part in parts:
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key:
            values[key] = value

    return values


def _parse_exact_lookup_intent(
    query: str,
    columns: list[str],
    rows: list[CsvRow],
) -> LookupIntent | None:
    query_normalized = _normalize_text(query)
    value_candidates = _extract_value_candidates(query)
    if not value_candidates:
        return None

    condition_column, condition_value = _find_condition_column(
        query_normalized=query_normalized,
        columns=columns,
        rows=rows,
        value_candidates=value_candidates,
    )
    if not condition_column:
        return None

    return_column = _resolve_return_column(query, columns, exclude={condition_column})
    return LookupIntent(
        return_column=return_column,
        condition_column=condition_column,
        condition_value=condition_value,
    )


def _find_condition_column(
    query_normalized: str,
    columns: list[str],
    rows: list[CsvRow],
    value_candidates: list[str],
) -> tuple[str | None, str]:
    candidates: list[tuple[int, str, str]] = []

    for column in columns:
        phrase_score = max(
            (
                len(phrase)
                for phrase in _column_phrases(column)
                if _phrase_in_query(phrase, query_normalized)
            ),
            default=0,
        )
        if not phrase_score:
            continue

        for value in value_candidates:
            if any(_values_equal(row.values.get(column, ""), value) for row in rows):
                candidates.append((phrase_score, column, value))

    if not candidates:
        return None, ""

    candidates.sort(key=lambda item: item[0], reverse=True)
    _, column, value = candidates[0]
    return column, value


def _filters_for_query(
    query: str,
    rows: list[CsvRow],
    columns: list[str],
    include_remote: bool = True,
) -> list[FilterSpec]:
    normalized = _normalize_text(query)
    filters: list[FilterSpec] = []

    state_column = _find_column(columns, "state")
    if state_column:
        states = _state_filters(query)
        if states:
            filters.append(FilterSpec(state_column, "in_upper", states))

    remote_column = _find_column(columns, "remote")
    if include_remote and remote_column:
        if _asks_for_non_remote(normalized):
            filters.append(FilterSpec(remote_column, "bool", False))
        elif _asks_for_remote(normalized):
            filters.append(FilterSpec(remote_column, "bool", True))

    title_column = _find_column(columns, "job title")
    if title_column:
        if any(_phrase_in_query(word, normalized) for word in ("senior", "sr")):
            filters.append(FilterSpec(title_column, "contains_any", ["senior", "sr"]))

        job_terms = [
            term
            for term in ("software", "engineer", "developer", "backend", "frontend", "fullstack", "cloud")
            if _phrase_in_query(term, normalized)
        ]
        if job_terms:
            filters.append(FilterSpec(title_column, "contains_all", job_terms))

    filters.extend(_known_value_filters(query, rows, columns, include_remote=include_remote))
    filters.extend(_numeric_filters(query, rows, columns))
    return _dedupe_filters(filters)


def _known_value_filters(
    query: str,
    rows: list[CsvRow],
    columns: list[str],
    include_remote: bool = True,
) -> list[FilterSpec]:
    normalized = _normalize_text(query)
    states = _state_filters(query)
    candidate_columns = [
        column
        for column in columns
        if _normalize_text(column)
        in {"company", "city", "location", "estimate type", "state"}
    ]
    filters: list[FilterSpec] = []

    for column in candidate_columns:
        if _normalize_text(column) == "state" and states:
            continue

        values = _unique(
            [
                row.values.get(column, "").strip()
                for row in rows
                if row.values.get(column, "").strip()
            ]
        )
        for value in values:
            value_normalized = _normalize_text(value)
            if len(value_normalized) < 3 or value_normalized == "unknown":
                continue
            if states and (
                value_normalized in STATE_ALIASES
                or value.strip().upper() in states
                or STATE_ALIASES.get(value_normalized) in states
            ):
                continue
            if not include_remote and value_normalized in {"remote", "non remote", "not remote"}:
                continue
            if value_normalized == "remote" and _find_column(columns, "remote") and "remote" in normalized:
                continue
            if _phrase_in_query(value_normalized, normalized):
                filters.append(FilterSpec(column, "equals", value))
                break

    return filters


def _numeric_filters(
    query: str,
    rows: list[CsvRow],
    columns: list[str],
) -> list[FilterSpec]:
    normalized = _normalize_text(query)
    filters: list[FilterSpec] = []
    for value in _extract_value_candidates(query):
        if _number_is_limit(query, value):
            continue
        if _numeric_value(value) is None:
            continue
        for column in _numeric_columns(columns, rows):
            if any(_phrase_in_query(phrase, normalized) for phrase in _column_phrases(column)):
                filters.append(FilterSpec(column, "numeric_equals", value))
                break
    return filters


def _apply_filters(rows: list[CsvRow], filters: list[FilterSpec]) -> list[CsvRow]:
    if not filters:
        return rows
    return [row for row in rows if all(_row_matches_filter(row, flt) for flt in filters)]


def _row_matches_filter(row: CsvRow, flt: FilterSpec) -> bool:
    value = row.values.get(flt.column, "")
    if flt.mode == "equals":
        return _values_equal(value, str(flt.value))
    if flt.mode == "numeric_equals":
        return _values_equal(value, str(flt.value))
    if flt.mode == "in_upper":
        return value.strip().upper() in flt.value
    if flt.mode == "bool":
        return _as_bool(value) is flt.value
    if flt.mode == "contains_any":
        normalized = _normalize_text(value)
        return any(_phrase_in_query(term, normalized) for term in flt.value)
    if flt.mode == "contains_all":
        normalized = _normalize_text(value)
        return all(_phrase_in_query(term, normalized) for term in flt.value)
    return False


def _resolve_numeric_column(
    query: str,
    columns: list[str],
    rows: list[CsvRow],
) -> str | None:
    normalized = _normalize_text(query)
    numeric_columns = _numeric_columns(columns, rows)
    if not numeric_columns:
        return None

    preference_groups = [
        ("average salary", ("average salary", "avg salary", "average pay", "salary")),
        ("company score", ("company score", "score", "rating")),
        ("datex", ("datex", "days", "date")),
    ]
    for canonical, phrases in preference_groups:
        column = _find_column(columns, canonical)
        if column in numeric_columns and any(_phrase_in_query(phrase, normalized) for phrase in phrases):
            return column

    for column in numeric_columns:
        if any(_phrase_in_query(phrase, normalized) for phrase in _column_phrases(column)):
            return column

    return None


def _resolve_group_column(query: str, columns: list[str]) -> str | None:
    normalized = _normalize_text(query)
    priority = [
        ("remote", ("remote", "non remote", "not remote")),
        ("city", ("city", "cities")),
        ("state", ("state", "states", "california")),
        ("company", ("company", "companies", "employer")),
        ("job title", ("role", "roles", "job title", "job", "jobs", "position", "title")),
        ("estimate type", ("estimate type", "estimate")),
        ("location", ("location", "place")),
    ]
    for canonical, phrases in priority:
        column = _find_column(columns, canonical)
        if column and any(_phrase_in_query(phrase, normalized) for phrase in phrases):
            return column

    by_match = re.search(r"\bby\s+([a-zA-Z ]+)$", normalized)
    if by_match:
        return _find_column(columns, by_match.group(1))
    return None


def _resolve_return_column(
    query: str,
    columns: list[str],
    exclude: set[str] | None = None,
) -> str | None:
    normalized = _normalize_text(query)
    exclude = exclude or set()
    priority = [
        ("job title", ("role", "job title", "position", "title", "job")),
        ("company", ("company", "employer")),
        ("city", ("city",)),
        ("state", ("state",)),
        ("location", ("location", "place")),
        ("salary", ("salary range", "listed salary", "range")),
        ("average salary", ("average salary", "avg salary", "average pay", "salary")),
        ("remote", ("remote",)),
    ]
    for canonical, phrases in priority:
        column = _find_column(columns, canonical)
        if column and column not in exclude and any(_phrase_in_query(phrase, normalized) for phrase in phrases):
            return column
    return None


def _numeric_columns(columns: list[str], rows: list[CsvRow]) -> list[str]:
    numeric: list[str] = []
    for column in columns:
        values = [row.values.get(column, "") for row in rows]
        non_empty = [value for value in values if str(value).strip()]
        if not non_empty:
            continue
        numeric_count = sum(1 for value in non_empty if _numeric_value(str(value)) is not None)
        if numeric_count / len(non_empty) >= 0.7:
            numeric.append(column)
    return numeric


def _collect_columns(rows: list[dict[str, str]]) -> list[str]:
    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for column in row:
            if column in seen:
                continue
            seen.add(column)
            columns.append(column)
    return columns


def _find_column(columns: list[str], requested: str) -> str | None:
    requested_normalized = _normalize_text(requested)
    for column in columns:
        if _normalize_text(column) == requested_normalized:
            return column
    for column in columns:
        if requested_normalized in _column_phrases(column):
            return column
    return None


def _column_phrases(column: str) -> list[str]:
    normalized = _normalize_text(column)
    aliases = {
        "average salary": ["average salary", "avg salary", "average pay", "salary average", "salary"],
        "job title": ["job title", "job", "jobs", "role", "roles", "position", "title"],
        "company": ["company", "companies", "employer"],
        "company score": ["company score", "score", "rating"],
        "city": ["city", "cities"],
        "state": ["state", "states"],
        "location": ["location", "place"],
        "remote": ["remote", "non remote", "not remote", "onsite", "on site"],
        "salary": ["salary range", "listed salary", "salary", "range"],
        "estimate type": ["estimate type", "estimate"],
        "datex": ["datex", "days"],
    }

    phrases = [normalized]
    phrases.extend(aliases.get(normalized, []))
    return _unique([phrase for phrase in phrases if phrase])


STATE_ALIASES = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "give",
    "has",
    "have",
    "in",
    "include",
    "is",
    "me",
    "of",
    "on",
    "or",
    "please",
    "show",
    "some",
    "the",
    "to",
    "what",
    "which",
    "whose",
    "with",
}


def _has_table_intent(query: str) -> bool:
    normalized = _normalize_text(query)

    table_operation_words = (
        "average",
        "avg",
        "mean",
        "highest",
        "lowest",
        "largest",
        "smallest",
        "maximum",
        "minimum",
        "max",
        "min",
        "top",
        "count",
        "how many",
        "number of",
        "more common",
        "most common",
        "least common",
        "common",
        "frequent",
        "range",
        "ranges",
        "group by",
        " by ",
    )
    if any(word in normalized for word in table_operation_words):
        return True

    column_words = (
        "salary",
        "average salary",
        "remote",
        "non remote",
        "not remote",
        "onsite",
        "job",
        "jobs",
        "role",
        "roles",
        "company",
        "city",
        "state",
        "location",
        "estimate",
        "score",
    )
    row_listing_words = ("example", "examples", "list", "show", "which")
    if any(word in normalized for word in row_listing_words) and any(
        word in normalized for word in column_words
    ):
        return True

    if _state_filters(query):
        return True

    return False


def _state_filters(query: str) -> set[str]:
    normalized = _normalize_text(query)
    states: set[str] = set()
    for state_name, abbreviation in STATE_ALIASES.items():
        if _phrase_in_query(state_name, normalized):
            states.add(abbreviation)
        if re.search(rf"(?<![A-Za-z]){re.escape(abbreviation)}(?![A-Za-z])", query):
            states.add(abbreviation)
    return states


def _asks_for_remote(normalized: str) -> bool:
    return "remote" in normalized and not _asks_for_non_remote(normalized)


def _asks_for_non_remote(normalized: str) -> bool:
    return any(phrase in normalized for phrase in ("non remote", "not remote", "onsite", "on site", "in office"))


def _has_extreme_word(normalized: str) -> bool:
    return any(
        word in normalized
        for word in ("highest", "largest", "maximum", "max", "top", "lowest", "smallest", "minimum", "min")
    )


def _has_lowest_word(normalized: str) -> bool:
    return any(word in normalized for word in ("lowest", "smallest", "minimum", "min"))


def _extract_limit(query: str, default: int = 5) -> int:
    normalized = _normalize_text(query)
    match = re.search(r"\b(?:top|first|show|list)\s+(\d{1,2})\b", normalized)
    if not match:
        return default
    return max(1, min(20, int(match.group(1))))


def _extract_value_candidates(query: str) -> list[str]:
    candidates: list[str] = []
    for quoted in re.findall(r'"([^"]+)"|\'([^\']+)\'', query):
        value = quoted[0] or quoted[1]
        if value:
            candidates.append(value.strip())

    candidates.extend(
        match.group(0)
        for match in re.finditer(r"\b\d+(?:,\d{3})*(?:\.\d+)?\b", query)
    )

    return _unique(candidates)


def _number_is_limit(query: str, value: str) -> bool:
    normalized = _normalize_text(query)
    normalized_value = _normalize_text(value)
    return bool(re.search(rf"\b(?:top|first|show|list)\s+{re.escape(normalized_value)}\b", normalized))


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(value).lower())).strip()


def _normalize_value(value: str) -> str:
    value = str(value).replace("\xa0", " ")
    return re.sub(r"\s+", " ", value.strip().lower())


def _numeric_value(value: str) -> float | None:
    cleaned = str(value).strip().replace("$", "").replace(",", "")
    multiplier = 1.0
    if cleaned.lower().endswith("k"):
        multiplier = 1000.0
        cleaned = cleaned[:-1]
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", cleaned):
        return None
    return float(cleaned) * multiplier


def _as_bool(value: str | None) -> bool | None:
    normalized = _normalize_value(value or "")
    if normalized in {"true", "yes", "y", "1", "remote"}:
        return True
    if normalized in {"false", "no", "n", "0", "non remote", "not remote", "onsite", "on site"}:
        return False
    return None


def _values_equal(cell_value: str, query_value: str) -> bool:
    cell_number = _numeric_value(cell_value)
    query_number = _numeric_value(query_value)
    if cell_number is not None and query_number is not None:
        return cell_number == query_number

    return _normalize_value(cell_value) == _normalize_value(query_value)


def _phrase_in_query(phrase: str, query_normalized: str) -> bool:
    return _phrase_position(phrase, query_normalized) != -1


def _phrase_position(phrase: str, query_normalized: str) -> int:
    normalized_phrase = _normalize_text(phrase)
    if not normalized_phrase:
        return -1
    pattern = rf"(^|\s){re.escape(normalized_phrase)}(\s|$)"
    match = re.search(pattern, query_normalized)
    return match.start() if match else -1


def _structured_row_score(query: str, row: CsvRow) -> float:
    query_normalized = _normalize_text(query)
    score = 0.0

    state_filters = _state_filters(query)
    if state_filters and row.values.get("State", "").strip().upper() in state_filters:
        score += 4.0

    title = _normalize_text(row.values.get("Job Title", ""))
    if "senior" in query_normalized and any(_phrase_in_query(term, title) for term in ("senior", "sr")):
        score += 3.0
    if "software engineer" in query_normalized and "software" in title and "engineer" in title:
        score += 3.0

    for column in ("Company", "Job Title", "Location", "City", "State", "Salary", "Average Salary"):
        value = _normalize_text(row.values.get(column, ""))
        if len(value) >= 3 and _phrase_in_query(value, query_normalized):
            score += 1.0

    return score


def _row_search_text(row: CsvRow) -> str:
    parts = []
    for key, value in row.values.items():
        parts.append(key)
        parts.append(value)
    return _normalize_text(" ".join(parts))


def _query_terms(query: str) -> list[str]:
    query_normalized = _normalize_text(query)
    terms = [
        term
        for term in query_normalized.split()
        if len(term) > 1 and term not in STOPWORDS
    ]
    for state_name, abbreviation in STATE_ALIASES.items():
        if _phrase_in_query(state_name, query_normalized):
            terms.append(abbreviation.lower())
        if re.search(rf"(?<![A-Za-z]){re.escape(abbreviation)}(?![A-Za-z])", query):
            terms.append(abbreviation.lower())
    return _unique(terms)


def _dedupe_filters(filters: list[FilterSpec]) -> list[FilterSpec]:
    deduped: list[FilterSpec] = []
    seen: set[tuple[str, str, str]] = set()
    for flt in filters:
        key = (flt.column, flt.mode, str(flt.value))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(flt)
    return deduped


def _dedupe_chunks(chunks: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[str] = set()
    for chunk in chunks:
        chunk_id = str(chunk.get("id", ""))
        if not chunk_id or chunk_id in seen:
            continue
        seen.add(chunk_id)
        deduped.append(chunk)
    return deduped


def _chunks_for_rows(rows: list[CsvRow], limit: int = 8) -> list[dict]:
    return _dedupe_chunks([row.chunk for row in rows])[:limit]


def _source_numbers(chunks: list[dict]) -> dict[str, int]:
    return {str(chunk.get("id")): index for index, chunk in enumerate(chunks, start=1)}


def _dedupe_rows_by_document_row(rows: list[CsvRow]) -> list[CsvRow]:
    deduped: list[CsvRow] = []
    seen: set[tuple[str, int | None]] = set()
    for row in rows:
        key = (str(row.chunk.get("document_id", "")), row.row_number)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _dedupe_rows_by_identity(rows: list[CsvRow]) -> list[CsvRow]:
    deduped: list[CsvRow] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in rows:
        key = (
            row.values.get("Company", "").strip().lower(),
            row.values.get("Job Title", "").strip().lower(),
            row.values.get("Location", "").strip().lower(),
            row.values.get("Salary", "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _row_hint(row: CsvRow) -> str:
    company = row.values.get("Company", "").strip()
    row_number = f"row {row.row_number}" if row.row_number is not None else "the matching row"
    if company:
        return f" ({row_number}, {company})"
    return f" ({row_number})"


def _format_row_summary(rows: list[CsvRow]) -> str:
    summaries = []
    for row in rows:
        summaries.append(_format_row_brief(row))
    return "Matching rows: " + " | ".join(summaries)


def _format_row_brief(row: CsvRow) -> str:
    company = row.values.get("Company", "").strip()
    title = row.values.get("Job Title", "").strip()
    location = row.values.get("Location", "").strip()
    salary = _display_value(row.values.get("Salary", ""))
    average_salary = row.values.get("Average Salary", "").strip()

    pieces = []
    if title and company:
        pieces.append(f"{title} at {company}")
    elif title:
        pieces.append(title)
    elif company:
        pieces.append(company)
    if location:
        pieces.append(location)
    if salary:
        pieces.append(salary)
    elif average_salary:
        pieces.append(f"Average Salary {_format_numeric(_numeric_value(average_salary) or 0, 'Average Salary')}")
    return "; ".join(pieces) if pieces else f"row {row.row_number}"


def _format_numeric(value: float, column: str | None = None) -> str:
    column_normalized = _normalize_text(column or "")
    if "salary" in column_normalized or "pay" in column_normalized:
        return f"${value:,.0f}"
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}"


def _metric_label(column: str) -> str:
    normalized = _normalize_text(column)
    if normalized == "average salary":
        return "salary"
    return column.lower()


def _display_value(value: str) -> str:
    return str(value).replace("\xa0", " ").strip()


def _filter_description(filters: list[FilterSpec]) -> str:
    if not filters:
        return ""
    pieces = []
    for flt in filters:
        label = flt.column.lower()
        if flt.mode == "bool":
            pieces.append("remote rows" if flt.value else "non-remote rows")
        elif flt.mode == "in_upper":
            values = ", ".join(sorted(flt.value))
            pieces.append(f"{label} = {values}" if len(flt.value) == 1 else f"{label} in {values}")
        elif flt.mode in {"contains_all", "contains_any"}:
            pieces.append(f"{label} containing {' '.join(flt.value)}")
        else:
            pieces.append(f"{label} = {flt.value}")
    return " and ".join(pieces)


def _unique(values: list[str]) -> list[str]:
    unique_values: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = str(value).lower()
        if key in seen:
            continue
        seen.add(key)
        unique_values.append(value)
    return unique_values


def _row_count_label(count: int) -> str:
    return f"{count:,} row" if count == 1 else f"{count:,} rows"
