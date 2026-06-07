from typing import Literal

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


class QueryResponse(BaseModel):
    answer: str
    llm_route: RouteName
    language_detected: str
    citations: list[str] = Field(default_factory=list)
