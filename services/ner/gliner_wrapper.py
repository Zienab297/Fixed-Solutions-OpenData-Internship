"""
gliner_wrapper.py

Loads the multilingual GLiNER model ONCE at process startup and exposes
a single `extract()` function used by every request. This is what makes
this a "shared instance" rather than a per-request model load.

Default labels exist only as a fallback for manual testing (e.g. curling
/extract without a body). In real use, callers (ingestion pipeline,
query-time retrieval) should always pass the active domain's ontology
labels explicitly — GLiNER has no fixed label set, it's zero-shot.
"""
import logging
import os
from typing import List, Optional

from gliner import GLiNER

logger = logging.getLogger("ner_service.gliner_wrapper")

MODEL_NAME = os.environ.get("GLINER_MODEL_NAME", "urchade/gliner_multi-v2.1")

# Fallback label set ONLY — real calls should pass ontology-derived labels.
DEFAULT_LABELS = [
    "person", "organization", "location", "date", "disease", "drug", "law",
]

_model: Optional[GLiNER] = None


def load_model() -> None:
    """Load the GLiNER model into memory. Called once at app startup."""
    global _model
    if _model is not None:
        logger.info("Model already loaded, skipping reload.")
        return
    logger.info("Loading GLiNER model '%s'...", MODEL_NAME)
    _model = GLiNER.from_pretrained(MODEL_NAME)
    logger.info("GLiNER model loaded successfully.")


def is_loaded() -> bool:
    return _model is not None


def extract(text: str, labels: Optional[List[str]] = None, threshold: float = 0.4):
    """
    Run NER over `text` using `labels` as the candidate entity types.

    Returns a list of dicts: {text, label, start, end, score}
    Matches the Entity schema in schemas.py.
    """
    if _model is None:
        raise RuntimeError(
            "GLiNER model not loaded yet. load_model() must run before extract()."
        )

    active_labels = labels if labels else DEFAULT_LABELS

    raw_entities = _model.predict_entities(text, active_labels, threshold=threshold)

    # GLiNER's predict_entities already returns dicts shaped like:
    # {"text": ..., "label": ..., "start": ..., "end": ..., "score": ...}
    # We pass them through but make sure every required key is present.
    results = []
    for ent in raw_entities:
        results.append(
            {
                "text": ent.get("text", ""),
                "label": ent.get("label", ""),
                "start": ent.get("start", -1),
                "end": ent.get("end", -1),
                "score": float(ent.get("score", 0.0)),
            }
        )
    return results
