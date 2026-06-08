from pydantic import BaseModel, Field
from typing import Optional, List
from uuid import UUID
from datetime import datetime

class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    domain_ids: List[UUID] = Field(..., min_items=1)
    top_k: int = Field(default=5, ge=1, le=20)
    language: Optional[str] = None  # auto-detect if not provided

class CitationSource(BaseModel):
    chunk_id: UUID
    document_title: str
    page_number: Optional[int]
    section: Optional[str]
    domain_id: UUID
    domain_name: str
    ingest_timestamp: datetime
    relevance_score: float

class GraphCitation(BaseModel):
    node_id: str
    entity_type: str
    entity_name: str
    traversal_path: List[str]

class EvaluationScores(BaseModel):
    faithfulness: Optional[float] = None
    relevance: Optional[float] = None
    completeness: Optional[float] = None
    citation_accuracy: Optional[float] = None
    rationale: Optional[dict] = None

class QueryResponse(BaseModel):
    query_id: UUID
    answer: str
    citations: List[CitationSource]
    graph_citations: Optional[List[GraphCitation]] = None
    confidence_score: float
    llm_route: str  # 'local' or 'api'
    language_detected: str
    evaluation: Optional[EvaluationScores] = None  # null until async judge completes
    created_at: datetime
