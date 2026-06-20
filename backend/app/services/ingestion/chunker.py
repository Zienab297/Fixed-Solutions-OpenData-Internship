"""
Unified ingestion pipeline supporting PDF, CSV, and DOCX/DOC.
Strictly rejects any other file formats. Import cost: zero (lazy imports).

Tables are extracted separately and chunked row-by-row to preserve
structure (column headers stay attached to each row's values) instead
of letting RecursiveCharacterTextSplitter break them mid-row.
"""
import os
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


def process_file(file_path: str) -> list[Document]:
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        from langchain_community.document_loaders import PyMuPDFLoader
        loader = PyMuPDFLoader(file_path)
        docs = loader.load()
        table_docs = _extract_pdf_tables(file_path)

    elif ext == ".csv":
        from langchain_community.document_loaders import CSVLoader
        loader = CSVLoader(file_path)
        docs = loader.load()
        return docs

    elif ext in [".docx", ".doc"]:
        from langchain_community.document_loaders import Docx2txtLoader
        loader = Docx2txtLoader(file_path)
        docs = loader.load()
        table_docs = _extract_docx_tables(file_path)

    else:
        raise ValueError(
            f"❌ Unsupported file format! The system is configured to process only PDF, CSV, and DOCX/DOC files. "
            f"Rejected file: {os.path.basename(file_path)}"
        )

    chunker = RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", " ", ""],
        chunk_size=650,
        chunk_overlap=120,
    )
    text_chunks = chunker.split_documents(docs)

    return text_chunks + table_docs


def _extract_pdf_tables(file_path: str) -> list[Document]:
    """
    Extract tables from a PDF using camelot (lattice flavor — works best
    for tables with visible grid lines, like the W-4 withholding tables).
    Each table row becomes its own Document chunk so the embedding model
    sees complete, structured rows instead of broken fragments.
    """
    import camelot

    table_docs: list[Document] = []

    try:
        tables = camelot.read_pdf(file_path, pages="all", flavor="lattice")
    except Exception:
        return table_docs

    for table_index, table in enumerate(tables):
        df = table.df
        if df.empty:
            continue

        headers = df.iloc[0].tolist()
        page_number = table.page

        for row_index, row in df.iloc[1:].iterrows():
            row_text = " | ".join(
                f"{headers[i]}: {value}"
                for i, value in enumerate(row.tolist())
                if str(value).strip()
            )
            if not row_text.strip():
                continue

            table_docs.append(
                Document(
                    page_content=row_text,
                    metadata={
                        "page": page_number,
                        "type": "table",
                        "table_index": table_index,
                        "row_index": row_index,
                        "source_type": "pdf",
                    },
                )
            )

    return table_docs


def _extract_docx_tables(file_path: str) -> list[Document]:
    """
    Extract tables from a DOCX using python-docx. Each table row becomes
    its own Document chunk, mirroring the PDF table handling above.
    """
    from docx import Document as DocxDocument

    table_docs: list[Document] = []

    try:
        docx_file = DocxDocument(file_path)
    except Exception:
        return table_docs

    for table_index, table in enumerate(docx_file.tables):
        rows = [
            [cell.text.strip() for cell in row.cells]
            for row in table.rows
        ]
        rows = [row for row in rows if any(cell for cell in row)]
        if len(rows) < 2:
            continue

        headers = rows[0]

        for row_index, row in enumerate(rows[1:], start=1):
            row_text = " | ".join(
                f"{headers[i]}: {value}"
                for i, value in enumerate(row)
                if value.strip()
            )
            if not row_text.strip():
                continue

            table_docs.append(
                Document(
                    page_content=row_text,
                    metadata={
                        "section": f"table_{table_index}",
                        "type": "table",
                        "table_index": table_index,
                        "row_index": row_index,
                        "source_type": "docx",
                    },
                )
            )

    return table_docs