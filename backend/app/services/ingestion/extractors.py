"""
Document text extraction helpers.

Each extractor returns blocks of text with lightweight location metadata. The
DocumentProcessor owns chunking, embedding, and persistence.
"""
from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ExtractedBlock:
    text: str
    page_number: int | None = None
    section: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def extract_document(
    filename: str,
    file_bytes: bytes,
    source_type: str | None = None,
) -> list[ExtractedBlock]:
    resolved_type = (source_type or _source_type_from_filename(filename)).lower()

    if resolved_type == "pdf":
        return extract_pdf(file_bytes)
    if resolved_type == "docx":
        return extract_docx(file_bytes)
    if resolved_type == "csv":
        return extract_csv(file_bytes)

    raise ValueError(f"Unsupported document type: {resolved_type or filename}")


def extract_pdf(file_bytes: bytes) -> list[ExtractedBlock]:
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    blocks: list[ExtractedBlock] = []

    for page_number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        has_images = _page_has_images(page)

        if not has_images:
            if text:
                blocks.append(
                    ExtractedBlock(
                        text=text,
                        page_number=page_number,
                        metadata={"source_type": "pdf"},
                    )
                )
            continue

        ocr_text = _ocr_page(file_bytes, page_number)
        ocr_metadata = {"source_type": "pdf", "ocr_used": True}

        if text:
            blocks.append(
                ExtractedBlock(
                    text=text,
                    page_number=page_number,
                    metadata=ocr_metadata,
                )
            )

        if ocr_text:
            blocks.append(
                ExtractedBlock(
                    text=ocr_text,
                    page_number=page_number,
                    metadata={**ocr_metadata, "block_type": "ocr"},
                )
            )
        elif not text:
            blocks.append(
                ExtractedBlock(
                    text="",
                    page_number=page_number,
                    metadata=ocr_metadata,
                )
            )

    return blocks


def _page_has_images(page: Any) -> bool:
    try:
        return len(page.images) > 0
    except Exception:
        return False


def _ocr_page(file_bytes: bytes, page_number: int) -> str:
    import fitz  # pymupdf

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    page = doc[page_number - 1]
    pix = page.get_pixmap(dpi=200)
    img_bytes = pix.tobytes("png")
    doc.close()

    from PIL import Image
    import numpy as np

    img_array = np.array(Image.open(io.BytesIO(img_bytes)).convert("RGB"))

    ocr = _get_ocr_engine()
    try:
        result = ocr.predict(img_array)
    except Exception as exc:
        from app.core.config import settings

        if settings.OCR_DEVICE == "cpu":
            raise
        logger.warning(
            "OCR prediction failed on device=%s (%s); retrying on CPU",
            settings.OCR_DEVICE,
            exc,
        )
        result = _get_ocr_engine("cpu").predict(img_array)

    lines: list[str] = []
    for res in result:
        for item in res.get("rec_texts", []) or []:
            if item and item.strip():
                lines.append(item.strip())

    return "\n".join(lines)


_OCR_ENGINE = None
_OCR_ENGINE_DEVICE = None


def _get_ocr_engine(device: str | None = None):
    global _OCR_ENGINE, _OCR_ENGINE_DEVICE

    from app.core.config import settings

    requested_device = device or settings.OCR_DEVICE
    if _OCR_ENGINE is None or _OCR_ENGINE_DEVICE != requested_device:
        from paddleocr import PaddleOCR

        try:
            _OCR_ENGINE = PaddleOCR(lang=settings.OCR_LANG, device=requested_device)
            _OCR_ENGINE_DEVICE = requested_device
        except Exception as exc:
            if requested_device == "cpu":
                raise
            logger.warning(
                "OCR engine failed to start on device=%s (%s); falling back to CPU",
                requested_device,
                exc,
            )
            _OCR_ENGINE = PaddleOCR(lang=settings.OCR_LANG, device="cpu")
            _OCR_ENGINE_DEVICE = "cpu"
    return _OCR_ENGINE


def extract_docx(file_bytes: bytes) -> list[ExtractedBlock]:
    from docx import Document as DocxDocument
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = DocxDocument(io.BytesIO(file_bytes))
    blocks: list[ExtractedBlock] = []
    current_section: str | None = None

    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            paragraph = Paragraph(child, document)
            text = paragraph.text.strip()
            if not text:
                continue

            style_name = paragraph.style.name if paragraph.style else ""
            is_heading = style_name.lower().startswith("heading")
            if is_heading:
                current_section = text

            blocks.append(
                ExtractedBlock(
                    text=text,
                    section=current_section,
                    metadata={
                        "source_type": "docx",
                        "style": style_name,
                    },
                )
            )

        elif isinstance(child, CT_Tbl):
            table = Table(child, document)
            table_text = _format_docx_table(table)
            if table_text:
                blocks.append(
                    ExtractedBlock(
                        text=table_text,
                        section=current_section,
                        metadata={"source_type": "docx", "block_type": "table"},
                    )
                )

    return blocks


def extract_csv(file_bytes: bytes, rows_per_block: int = 10) -> list[ExtractedBlock]:
    text = _decode_text(file_bytes)
    rows = _read_csv_rows(text)
    if not rows:
        return []

    blocks: list[ExtractedBlock] = []
    columns = _collect_columns(rows)

    for start in range(0, len(rows), rows_per_block):
        batch = rows[start : start + rows_per_block]
        row_start = start + 1
        row_end = start + len(batch)
        lines = [f"CSV rows {row_start}-{row_end}"]

        for row_number, row in enumerate(batch, start=row_start):
            values = [
                f"{column}: {value}"
                for column, value in row.items()
                if str(value).strip()
            ]
            lines.append(f"Row {row_number}: {'; '.join(values)}")

        blocks.append(
            ExtractedBlock(
                text="\n".join(lines),
                section=f"rows {row_start}-{row_end}",
                metadata={
                    "source_type": "csv",
                    "row_start": row_start,
                    "row_end": row_end,
                    "columns": columns,
                    "rows": [
                        {
                            "row_number": row_number,
                            "values": row,
                        }
                        for row_number, row in enumerate(batch, start=row_start)
                    ],
                },
            )
        )

    return blocks


def _source_type_from_filename(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    return {
        ".pdf": "pdf",
        ".docx": "docx",
        ".csv": "csv",
    }.get(suffix, "")


def _format_docx_table(table: Any) -> str:
    rows = [
        [_normalize_cell_text(cell.text) for cell in row.cells]
        for row in table.rows
    ]
    rows = [row for row in rows if any(cell for cell in row)]
    if not rows:
        return ""

    header = rows[0]
    has_header = len(rows) > 1 and any(header)
    lines = ["Table:"]

    if has_header:
        for row_number, row in enumerate(rows[1:], start=1):
            pairs = []
            for index, value in enumerate(row):
                if not value:
                    continue
                column = (
                    header[index]
                    if index < len(header) and header[index]
                    else f"Column {index + 1}"
                )
                pairs.append(f"{column}: {value}")
            if pairs:
                lines.append(f"Row {row_number}: {'; '.join(pairs)}")
    else:
        lines.extend(" | ".join(cell for cell in row if cell) for row in rows)

    return "\n".join(line for line in lines if line.strip())


def _normalize_cell_text(text: str) -> str:
    return " ".join(text.split())


def _decode_text(file_bytes: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="replace")


def _read_csv_rows(text: str) -> list[dict[str, str]]:
    sample = text[:4096]
    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(sample)
    except csv.Error:
        dialect = csv.excel

    try:
        has_header = sniffer.has_header(sample)
    except csv.Error:
        has_header = True

    raw_rows = list(csv.reader(io.StringIO(text), dialect))
    raw_rows = [row for row in raw_rows if any(cell.strip() for cell in row)]
    if not raw_rows:
        return []

    if has_header:
        headers = [
            header.strip() or f"column_{index + 1}"
            for index, header in enumerate(raw_rows[0])
        ]
        data_rows = raw_rows[1:]
    else:
        width = max(len(row) for row in raw_rows)
        headers = [f"column_{index + 1}" for index in range(width)]
        data_rows = raw_rows

    normalized_rows: list[dict[str, str]] = []
    for row in data_rows:
        normalized_rows.append(
            {
                _column_name(headers, index): value.strip()
                for index, value in enumerate(row)
            }
        )

    return normalized_rows


def _column_name(headers: list[str], index: int) -> str:
    if index < len(headers):
        return headers[index]
    return f"extra_column_{index + 1}"


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
