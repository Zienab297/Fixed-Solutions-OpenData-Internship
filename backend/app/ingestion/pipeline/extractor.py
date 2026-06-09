import logging
from pathlib import Path

import pdfplumber


logger = logging.getLogger(__name__)


def extract_pdf_text(file_path: str) -> list[tuple[int, str]]:
    pages: list[tuple[int, str]] = []
    with pdfplumber.open(Path(file_path)) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                pages.append((index, text.strip()))

    if not pages:
        logger.warning(
            "No extractable text found in %s. OCR is intentionally skipped for Sprint 1.",
            file_path,
        )
    return pages
