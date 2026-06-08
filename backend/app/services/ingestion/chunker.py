"""
Document chunking service.
Configurable chunk size and overlap per domain (§2.4).
"""
from typing import List
from dataclasses import dataclass


@dataclass
class Chunk:
    content: str
    chunk_index: int
    page_number: int = None
    section: str = None
    metadata: dict = None


class ChunkerService:
    def chunk_text(
        self,
        text: str,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        page_number: int = None,
        section: str = None,
    ) -> List[Chunk]:
        """
        Split text into overlapping chunks.
        Overlap preserves context at chunk boundaries.
        """
        words = text.split()
        chunks = []
        i = 0
        chunk_index = 0

        while i < len(words):
            chunk_words = words[i : i + chunk_size]
            chunk_text = " ".join(chunk_words)

            if chunk_text.strip():
                chunks.append(
                    Chunk(
                        content=chunk_text,
                        chunk_index=chunk_index,
                        page_number=page_number,
                        section=section,
                        metadata={},
                    )
                )
                chunk_index += 1

            i += chunk_size - chunk_overlap  # step forward with overlap

        return chunks

    def chunk_structured_data(self, rows: List[dict], context_key: str = None) -> List[Chunk]:
        """
        Schema-aware chunking for CSV/XLSX data (§2.2).
        Groups rows by semantic context rather than raw count.
        """
        # Group by context_key if provided (e.g. department, category)
        if context_key and rows and context_key in rows[0]:
            from itertools import groupby
            groups = {}
            for row in rows:
                key = row.get(context_key, "unknown")
                groups.setdefault(key, []).append(row)

            chunks = []
            for group_key, group_rows in groups.items():
                content = f"Group: {group_key}\n"
                content += "\n".join(str(r) for r in group_rows)
                chunks.append(Chunk(content=content, chunk_index=len(chunks)))
            return chunks

        # Default: fixed-size row groups
        chunk_size = 50
        chunks = []
        for i in range(0, len(rows), chunk_size):
            batch = rows[i : i + chunk_size]
            content = "\n".join(str(r) for r in batch)
            chunks.append(Chunk(content=content, chunk_index=len(chunks)))
        return chunks
