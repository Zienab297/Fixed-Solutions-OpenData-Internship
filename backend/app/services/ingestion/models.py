"""
Embedding model reference for legacy rag.py.
NOTE: rag.py is NOT part of the active ingestion pipeline.
      The real pipeline is document_processor.py → embedder.py → Ollama.
      This file is kept only to avoid ImportError if something imports it,
      but the HuggingFace model is NO LONGER loaded at import time.
"""

# Intentionally empty — do not instantiate HuggingFaceEmbeddings here.
# If you need rag.py's SemanticChunker for experiments, instantiate it
# explicitly in a script, not at module level.
embedding_model = None
