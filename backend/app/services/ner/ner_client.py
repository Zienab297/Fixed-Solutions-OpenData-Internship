"""
backend/app/services/ner/ner_client.py

Thin async HTTP client the backend uses to call the standalone NER
microservice (services/ner). This is explicitly NOT NER logic itself —
the backend owns label selection (which domain → which GLiNER labels)
and result handling; the NER service just runs the model.

Request/response shapes mirror services/ner/schemas.py exactly
(ExtractRequest / ExtractResponse / Entity) so this client can be a
drop-in caller without importing FastAPI.

Domain label lists are loaded from the ontology JSON files under
    backend/app/services/graph/ontologies/
discovered dynamically via ontology_loader.py (see that module for why
this used to be a hardcoded dict and isn't anymore). Adding a node
label to a domain's ontology file is all that's needed to change what
GLiNER is asked to extract for that domain — no hardcoded label lists
live in this file.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import httpx
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.graph import ontology_loader

logger = logging.getLogger("ner_client")


# ---------------------------------------------------------------------------
# Response shapes — mirror services/ner/schemas.py exactly
# ---------------------------------------------------------------------------
class Entity(BaseModel):
    text: str
    label: str
    start: int
    end: int
    score: float


class ExtractResponse(BaseModel):
    entities: list[Entity]
    language_hint: Optional[str] = None


# ---------------------------------------------------------------------------
# Domain → label list, loaded from the ontology JSON files
# ---------------------------------------------------------------------------
class _DomainOntology(BaseModel):
    """Just what ner_client needs out of each ontology file."""
    schema_version: str = Field(alias="schema_version")
    labels: list[str]


_ontology_cache: dict[str, _DomainOntology] = {}


def _load_ontology(domain: str) -> _DomainOntology:
    """
    Load and cache a domain's label list from its ontology JSON file.

    Raises FileNotFoundError / KeyError loudly on a bad domain or
    malformed file — silently falling back to empty labels would mean
    every entity in that domain gets dropped at extraction time with
    no obvious cause, which is worse than failing fast here.
    """
    if domain in _ontology_cache:
        return _ontology_cache[domain]

    path = ontology_loader.get_ontology_path(domain)
    if not path.exists():
        raise FileNotFoundError(f"Ontology file not found for domain '{domain}': {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    schema_version = raw.get("schema_version")
    if not schema_version:
        raise ValueError(f"Ontology file for '{domain}' is missing 'schema_version': {path}")

    node_labels = raw.get("node_labels")
    if not node_labels:
        raise ValueError(f"Ontology file for '{domain}' has no 'node_labels': {path}")

    labels = [entry["label"] for entry in node_labels]

    ontology = _DomainOntology(schema_version=schema_version, labels=labels)
    _ontology_cache[domain] = ontology
    logger.info("Loaded %d labels for domain '%s' (schema_version=%s)", len(labels), domain, schema_version)
    return ontology


def get_domain_labels(domain: str) -> list[str]:
    """Public helper — e.g. for Phase 5's entity→node-label mapping step."""
    return _load_ontology(domain).labels


def get_domain_schema_version(domain: str) -> str:
    """Public helper — Phase 8 re-extraction uses this for staleness checks."""
    return _load_ontology(domain).schema_version


def get_known_domains() -> frozenset[str]:
    """
    Public helper — the authoritative set of domain keys this service
    actually has an ontology for. Used by callers (extractor.py) that
    resolve a domain key from somewhere else (e.g. a Domain table's
    display name) and need to validate that guess against reality
    before using it, instead of finding out three calls later via a
    FileNotFoundError with no context about which document triggered it.

    Delegates to ontology_loader, which scans the ontologies/ folder on
    disk rather than reading a hardcoded dict — this is what lets a
    freshly-written ontology file (from ontology_builder.py) become
    "known" without any code change or cache-bust call.
    """
    return ontology_loader.get_known_domains()


def clear_ontology_cache() -> None:
    """Call after an ontology file is edited (e.g. Phase 8 admin update) so
    the next extract_entities() call picks up the new label set instead of
    serving stale cached labels."""
    _ontology_cache.clear()


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------
_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=5.0, pool=5.0)
_MAX_RETRIES = 2


async def extract_entities(
    text: str,
    domain: str,
    threshold: float = 0.4,
) -> list[Entity]:
    """
    Call the NER service for the given text, using the active domain's
    full label set (never relies on the NER service's DEFAULT_LABELS
    fallback in real calls — labels are always explicit).

    Retries on connection/timeout errors (NER service down or slow)
    up to _MAX_RETRIES times with a short backoff, so a transient blip
    doesn't hang ingestion forever. Does NOT retry on 4xx responses
    (e.g. bad request) since retrying won't fix a malformed payload.
    """
    labels = get_domain_labels(domain)

    payload = {
        "text": text,
        "labels": labels,
        "threshold": threshold,
    }

    last_exc: Optional[Exception] = None
    for attempt in range(1, _MAX_RETRIES + 2):  # e.g. 1 try + 2 retries = 3 attempts
        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                response = await client.post(
                    f"{settings.NER_SERVICE_URL}/extract",
                    json=payload,
                )
            response.raise_for_status()
            parsed = ExtractResponse.model_validate(response.json())
            return parsed.entities

        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            last_exc = exc
            logger.warning(
                "NER service call failed (attempt %d/%d): %s",
                attempt, _MAX_RETRIES + 1, exc,
            )
            if attempt <= _MAX_RETRIES:
                continue
            raise

        except httpx.HTTPStatusError as exc:
            logger.error(
                "NER service returned %s for domain '%s': %s",
                exc.response.status_code, domain, exc.response.text[:300],
            )
            raise

    # Unreachable in practice (loop either returns or raises), but keeps
    # type checkers happy and guards against future refactors of the loop.
    raise last_exc  # type: ignore[misc]