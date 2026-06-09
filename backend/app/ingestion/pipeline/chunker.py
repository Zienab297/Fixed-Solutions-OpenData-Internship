from dataclasses import dataclass
from uuid import uuid4


@dataclass(frozen=True)
class DocumentChunk:
    chunk_id: str
    doc_id: str
    domain_id: str
    page_number: int
    text: str


def split_pages(
    pages: list[tuple[int, str]],
    doc_id: str,
    domain_id: str,
    chunk_size: int,
    overlap: int,
) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    step = max(chunk_size - overlap, 1)

    for page_number, text in pages:
        normalized = " ".join(text.split())
        for start in range(0, len(normalized), step):
            chunk_text = normalized[start : start + chunk_size].strip()
            if not chunk_text:
                continue
            chunks.append(
                DocumentChunk(
                    chunk_id=str(uuid4()),
                    doc_id=doc_id,
                    domain_id=domain_id,
                    page_number=page_number,
                    text=chunk_text,
                )
            )
            if start + chunk_size >= len(normalized):
                break

    return chunks
