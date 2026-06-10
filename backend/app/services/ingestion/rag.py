"""
rag.py — LEGACY / EXPERIMENTAL FILE.

This file is NOT wired into the active ingestion pipeline.
The active pipeline is:
    Celery task → DocumentProcessor → ChunkerService → EmbeddingService (Ollama)

SemanticChunker from LangChain embeds every sentence during splitting,
which means embeddings are generated TWICE if this is mixed with
document_processor.py. Keep this file for research/experiments only.

To use it standalone (outside the app), install langchain dependencies
and instantiate HuggingFaceEmbeddings manually before calling process_pdf().
"""
from __future__ import annotations


def process_pdf(pdf_path: str):
    """
    Experimental semantic chunking pipeline using LangChain + bge-m3.
    NOT called by any active code path. Import cost: zero (lazy imports below).
    """
    from langchain_community.document_loaders import PyPDFLoader
    from langchain_experimental.text_splitter import SemanticChunker
    from langchain_huggingface import HuggingFaceEmbeddings

    loader = PyPDFLoader(pdf_path)
    docs = loader.load()

    _embedding_model = HuggingFaceEmbeddings(model_name="BAAI/bge-m3")

    chunker = SemanticChunker(
        _embedding_model,
        breakpoint_threshold_type="percentile",
        breakpoint_threshold_amount=90,
    )

    chunks = chunker.split_documents(docs)
    return chunks
