from typing import Literal, Optional, List
from uuid import UUID
from pydantic import BaseModel, Field

RouteName = Literal["local", "api"]


class ContextChunk(BaseModel):
    content: str
    document_title: str = "Unknown"
    page_number: int | None = None


class QueryRequest(BaseModel):
    query: str = Field(min_length=1)
    domain_ids: list[str] = Field(default_factory=list)
    domain_routes: dict[str, RouteName] = Field(default_factory=dict)
    context: list[ContextChunk] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=20)


class Citation(BaseModel):
    chunk_id: str
    document_title: str
    page_number: Optional[int] = None
    section: Optional[str] = None
    domain_id: str
    domain_name: str = ""
    relevance_score: float = 0.0


class EvaluationScores(BaseModel):
    faithfulness: Optional[float] = None
    relevance: Optional[float] = None
    completeness: Optional[float] = None
    citation_accuracy: Optional[float] = None
    rationale: Optional[dict] = None
    flagged: Optional[bool] = None


class QueryResponse(BaseModel):
    query_id: UUID
    answer: str
    llm_route: RouteName
    language_detected: str
    citations: List[Citation] = Field(default_factory=list)
    confidence_score: float = 0.0
    signals_used: List[str] = Field(default_factory=list)
    evaluation: Optional[EvaluationScores] = None
