"""
Request/response models for the NER microservice.

Kept deliberately separate from main.py so the backend's ner_client.py
can mirror these shapes exactly without importing FastAPI.
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class ExtractRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Raw text to run NER over.")
    labels: Optional[List[str]] = Field(
        default=None,
        description=(
            "Candidate entity labels for this call (GLiNER is zero-shot). "
            "Caller should pass the active domain ontology's node label set "
            "(e.g. medical_ontology_schema.md's labels). If omitted, the "
            "service falls back to DEFAULT_LABELS below."
        ),
    )
    threshold: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description="GLiNER confidence threshold below which entities are dropped.",
    )


class Entity(BaseModel):
    text: str
    label: str
    start: int
    end: int
    score: float


class ExtractResponse(BaseModel):
    entities: List[Entity]
    language_hint: Optional[str] = Field(
        default=None,
        description="Best-effort language guess, not a guaranteed detection.",
    )


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    model_name: str
