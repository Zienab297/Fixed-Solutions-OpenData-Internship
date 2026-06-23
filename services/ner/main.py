"""
main.py — NER microservice entrypoint.

Run with: uvicorn main:app --host 0.0.0.0 --port 8001

Exposes:
  GET  /health   -> liveness + model-loaded check (used by docker healthcheck)
  POST /extract  -> text -> [(entity, type, start, end, score)]

This service is intentionally "dumb": it has no knowledge of domains,
ontologies, or RBAC. It only does NER. The caller (backend's
ner_client.py, in either the ingestion Celery task or the query-time
retrieval router) is responsible for deciding which label set to send
and what to do with the results.
"""
import logging

from fastapi import FastAPI, HTTPException

import gliner_wrapper
from schemas import ExtractRequest, ExtractResponse, Entity, HealthResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ner_service.main")

app = FastAPI(title="NER Service", version="1.0.0")


@app.on_event("startup")
def startup_event():
    gliner_wrapper.load_model()


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok" if gliner_wrapper.is_loaded() else "model_not_loaded",
        model_loaded=gliner_wrapper.is_loaded(),
        model_name=gliner_wrapper.MODEL_NAME,
    )


@app.post("/extract", response_model=ExtractResponse)
def extract(request: ExtractRequest):
    if not gliner_wrapper.is_loaded():
        raise HTTPException(status_code=503, detail="Model not loaded yet.")

    try:
        raw_entities = gliner_wrapper.extract(
            text=request.text,
            labels=request.labels,
            threshold=request.threshold,
        )
    except Exception as exc:
        logger.exception("NER extraction failed")
        raise HTTPException(status_code=500, detail=f"Extraction failed: {exc}")

    entities = [Entity(**e) for e in raw_entities]
    return ExtractResponse(entities=entities, language_hint=None)
