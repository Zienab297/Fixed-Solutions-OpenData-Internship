from langchain_community.document_loaders import PyPDFLoader
from langchain_experimental.text_splitter import SemanticChunker
from models import embedding_model   

def process_pdf(pdf_path):
    loader = PyPDFLoader(pdf_path)
    docs = loader.load()

    chunker = SemanticChunker(
        embedding_model,
        breakpoint_threshold_type="percentile",
        breakpoint_threshold_amount=90
    )

    chunks = chunker.split_documents(docs)
    return chunks