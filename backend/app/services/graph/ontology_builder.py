"""
backend/app/services/graph/ontology_builder.py

Step 2 of the auto-ontology pipeline (see ontology_loader.py for step 1,
the discovery side). This module only runs on a cache miss: a domain
that has no file under services/graph/ontologies/ yet.

Flow:
    1. Caller (extractor.py) sees domain not in ontology_loader.get_known_domains()
    2. Calls ensure_ontology(domain, sample_texts)
    3. This module takes a Redis lock for that domain (two Celery workers
       hitting a brand-new domain's first two documents at ~the same time
       must not both fire the LLM call and race to write the file — same
       class of bug as the ingest.py FK-violation race, see module history)
    4. Asks the local LLM, once, to propose node_labels + relationship_types
       in the EXACT shape ner_client.py / triple_extractor.py already parse
       (schema_version, node_labels[], relationship_types[])
    5. Validates the JSON structurally before writing anything to disk —
       a malformed file here would break extraction for every future
       document in this domain, not just this one
    6. Writes the file via ontology_loader.get_ontology_path(domain)

After this, ontology_loader.get_known_domains() picks the domain up on
its next call (it re-scans the directory) — no cache to bust, no second
code path to update.

No canonicalization, no drift-prevention, no schema evolution. The
first call's sample text is all the schema will ever be built from for
this domain, same limitation as the hand-written legal/medical files,
just self-inflicted instead of hand-written (per project scope decision).
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.core.config import settings
from app.core.metrics import (
    KNOWN_ONTOLOGY_DOMAINS,
    ONTOLOGY_BUILD_ATTEMPTS_TOTAL,
    ONTOLOGY_BUILD_DURATION_SECONDS,
    ONTOLOGY_BUILD_LOCK_WAIT_SECONDS,
)
from app.services.graph import ontology_loader
from app.services.llm.local_llm import LocalLLMService, LocalLLMTimeoutError

logger = logging.getLogger("ontology_builder")

_LOCK_TTL_SECONDS = 90  # generous; a local LLM JSON proposal call is slow, not 90s slow, but err safe
_MIN_NODE_LABELS = 4
_MIN_RELATIONSHIP_TYPES = 3
_MAX_SAMPLE_CHARS = 6000  # keep the proposal prompt small; this is a schema sketch, not full-text analysis

_llm = LocalLLMService()


class OntologyBuildError(RuntimeError):
    """Raised when the LLM's proposal can't be turned into a usable ontology file."""


async def ensure_ontology(domain: str, sample_texts: list[str]) -> bool:
    """
    Idempotent: if the domain already has a file (written by this call
    or by a concurrent one that won this lock), this is a no-op.

    Returns True if this call built and wrote a new ontology file,
    False if the domain already had one (no LLM call made).
    """
    if ontology_loader.ontology_exists(domain):
        return False

    redis_client = _get_redis()
    lock_key = f"ontology_build_lock:{domain}"

    got_lock = await redis_client.set(lock_key, "1", nx=True, ex=_LOCK_TTL_SECONDS)
    if not got_lock:
        # Someone else is building this domain's ontology right now.
        # Don't double-call the LLM; wait for them to finish and re-check.
        logger.info("ontology_builder: lock held for domain '%s', waiting on the build in progress.", domain)
        await _wait_for_file(domain)
        return False

    try:
        # Re-check after acquiring the lock — covers the gap between the
        # exists() check above and the lock being granted.
        if ontology_loader.ontology_exists(domain):
            return False

        logger.info("ontology_builder: building new ontology for domain '%s' from %d sample doc(s).",
                     domain, len(sample_texts))
        build_start = time.monotonic()
        try:
            proposal = await _propose_ontology(domain, sample_texts)
            _validate_proposal(domain, proposal)
        except OntologyBuildError as exc:
            outcome = "llm_timeout" if "timed out" in str(exc) else (
                "llm_invalid_json" if "valid JSON" in str(exc) else "validation_failed"
            )
            ONTOLOGY_BUILD_ATTEMPTS_TOTAL.labels(domain=domain, outcome=outcome).inc()
            ONTOLOGY_BUILD_DURATION_SECONDS.labels(domain=domain).observe(time.monotonic() - build_start)
            raise

        path = ontology_loader.get_ontology_path(domain)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(proposal, f, indent=2, ensure_ascii=False)

        ONTOLOGY_BUILD_ATTEMPTS_TOTAL.labels(domain=domain, outcome="success").inc()
        ONTOLOGY_BUILD_DURATION_SECONDS.labels(domain=domain).observe(time.monotonic() - build_start)
        KNOWN_ONTOLOGY_DOMAINS.set(len(ontology_loader.get_known_domains()))

        logger.info(
            "ontology_builder: wrote new ontology for domain '%s' (%d node_labels, %d relationship_types) to %s",
            domain, len(proposal["node_labels"]), len(proposal["relationship_types"]), path,
        )
        return True

    finally:
        await redis_client.delete(lock_key)


async def _wait_for_file(domain: str, timeout_seconds: float = 60.0, poll_seconds: float = 1.0) -> None:
    """Poll for the file another worker is building, instead of returning
    immediately and letting the caller hit a FileNotFoundError a moment later."""
    import asyncio
    start = time.monotonic()
    waited = 0.0
    while waited < timeout_seconds:
        if ontology_loader.ontology_exists(domain):
            ONTOLOGY_BUILD_LOCK_WAIT_SECONDS.labels(domain=domain).observe(time.monotonic() - start)
            return
        await asyncio.sleep(poll_seconds)
        waited += poll_seconds
    ONTOLOGY_BUILD_LOCK_WAIT_SECONDS.labels(domain=domain).observe(time.monotonic() - start)
    logger.warning(
        "ontology_builder: timed out waiting for concurrent build of domain '%s' "
        "after %.0fs — proceeding, caller's own ontology load will raise if it's still missing.",
        domain, timeout_seconds,
    )


def _get_redis():
    """
    Thin wrapper so this module's import doesn't hard-fail if redis.asyncio
    isn't installed in some environment — fails loudly only when actually
    called, with a clear message, rather than at import time for every
    module that imports ontology_builder.
    """
    import redis.asyncio as redis

    redis_url = (
        getattr(settings, "REDIS_URL", None)
        or getattr(settings, "CELERY_BROKER_URL", None)
        or getattr(settings, "CELERY_RESULT_BACKEND", None)
    )
    if not redis_url:
        raise OntologyBuildError(
            "No Redis URL found on settings (checked REDIS_URL, CELERY_BROKER_URL, "
            "CELERY_RESULT_BACKEND). Set one of these or hardcode the right attribute "
            "name in ontology_builder._get_redis()."
        )
    return redis.from_url(redis_url)


# ---------------------------------------------------------------------------
# LLM proposal
# ---------------------------------------------------------------------------
def _build_prompt(domain: str, sample_texts: list[str]) -> str:
    joined = "\n\n---\n\n".join(
        text[:_MAX_SAMPLE_CHARS] for text in sample_texts if text and text.strip()
    )
    joined = joined[: _MAX_SAMPLE_CHARS]  # hard cap even across multiple samples

    return f"""You are designing a knowledge-graph ontology for a new document domain: "{domain}".

Below are sample excerpts from real documents in this domain:

{joined}

Propose a closed ontology for this domain: 6-10 entity (node) types and their relationship (edge) types, in the EXACT JSON shape below. This will be used as a fixed schema — be specific to what's actually in the text above, not generic placeholders.

Respond with ONLY a JSON object, no preamble, no markdown fences, no explanation, matching this shape exactly:

{{
  "ontology": "{domain.title()} Domain Ontology",
  "schema_version": "v1.0",
  "node_labels": [
    {{
      "label": "PascalCaseEntityType",
      "description": "one-sentence description",
      "key_properties": ["name", "domain", "schema_version", "source_chunk_ids"]
    }}
  ],
  "relationship_types": [
    {{
      "relationship": "UPPER_SNAKE_CASE_PREDICATE",
      "from": "SourceEntityLabel",
      "to": "TargetEntityLabel",
      "meaning": "one-sentence description"
    }}
  ]
}}

Rules:
- node_labels: 6-10 entries, PascalCase labels, each key_properties list must always include exactly ["name", "domain", "schema_version", "source_chunk_ids"]
- relationship_types: at least 3 entries. "from" and "to" must each be one of the labels you defined in node_labels.
- Every relationship's predicate must be a single UPPER_SNAKE_CASE token.
"""


async def _propose_ontology(domain: str, sample_texts: list[str]) -> dict[str, Any]:
    prompt = _build_prompt(domain, sample_texts)
    try:
        raw = await _llm.generate(prompt)
    except LocalLLMTimeoutError as exc:
        raise OntologyBuildError(f"LLM timed out proposing ontology for domain '{domain}': {exc}") from exc

    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OntologyBuildError(
            f"LLM ontology proposal for domain '{domain}' was not valid JSON: {exc}. Raw: {raw[:500]}"
        ) from exc

    return parsed


# ---------------------------------------------------------------------------
# Validation — must pass before anything touches disk
# ---------------------------------------------------------------------------
def _validate_proposal(domain: str, proposal: Any) -> None:
    if not isinstance(proposal, dict):
        raise OntologyBuildError(f"Ontology proposal for '{domain}' is not a JSON object.")

    if not proposal.get("schema_version"):
        raise OntologyBuildError(f"Ontology proposal for '{domain}' is missing 'schema_version'.")

    node_labels = proposal.get("node_labels")
    if not isinstance(node_labels, list) or len(node_labels) < _MIN_NODE_LABELS:
        raise OntologyBuildError(
            f"Ontology proposal for '{domain}' has fewer than {_MIN_NODE_LABELS} node_labels."
        )

    label_names: set[str] = set()
    for entry in node_labels:
        if not isinstance(entry, dict) or not entry.get("label"):
            raise OntologyBuildError(f"Ontology proposal for '{domain}' has a malformed node_labels entry: {entry!r}")
        label_names.add(entry["label"])

    relationship_types = proposal.get("relationship_types")
    if not isinstance(relationship_types, list) or len(relationship_types) < _MIN_RELATIONSHIP_TYPES:
        raise OntologyBuildError(
            f"Ontology proposal for '{domain}' has fewer than {_MIN_RELATIONSHIP_TYPES} relationship_types."
        )

    for rel in relationship_types:
        if not isinstance(rel, dict) or not rel.get("relationship") or not rel.get("from") or not rel.get("to"):
            raise OntologyBuildError(f"Ontology proposal for '{domain}' has a malformed relationship entry: {rel!r}")
        if rel["from"] not in label_names or rel["to"] not in label_names:
            raise OntologyBuildError(
                f"Ontology proposal for '{domain}': relationship {rel['relationship']!r} references "
                f"a from/to label not present in node_labels ({rel['from']!r} -> {rel['to']!r})."
            )