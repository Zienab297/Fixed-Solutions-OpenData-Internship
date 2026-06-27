"""
backend/app/services/llm/triple_extractor.py

Phase 3 (per NER_KG_Implementation_Roadmap.md addendum) — typed relation
extraction. Takes a chunk's NER entities + raw chunk text and asks the
local LLM to produce Subject -> Predicate -> Object triples, where every
triple is validated against the domain's closed ontology before it's
allowed anywhere near AGE.

This replaces the old generic MENTIONED_WITH edge in extractor.py.
Per medical_ontology_schema.json / legal_ontology_schema.json (and any
ontology auto-built by ontology_builder.py for a new domain, which
writes the same shape):

    "Treat the relationship types as the closed predicate set the
    triple-extraction LLM must map to — reject/flag any triple whose
    predicate doesn't match one of these."

Validation rules (strict, fail-closed):
    1. predicate must be one of the domain's relationship_types[].relationship
    2. subject entity's NER label must match that relationship's "from" label
    3. object entity's NER label must match that relationship's "to" label
    4. subject/object text must both be entities GLiNER actually found in
       this chunk (the LLM is not free to invent new entity names — it
       only gets to propose relationships *between* entities NER already
       extracted)

Any triple failing any of the above is dropped and logged as a warning,
not coerced or silently fixed (see extractor.py Phase-5 patch notes).

This module is async throughout, matching ner_client.py / age_client.py.
"""
from __future__ import annotations

import json
import logging
from typing import NamedTuple, Optional

from pydantic import BaseModel

from app.services.graph import ontology_loader
from app.services.llm.local_llm import LocalLLMService, LocalLLMTimeoutError

logger = logging.getLogger("triple_extractor")


class RelationshipType(NamedTuple):
    predicate: str
    from_label: str
    to_label: str


class _DomainRelationships(BaseModel):
    schema_version: str
    relationships: list[RelationshipType]


_relationship_cache: dict[str, _DomainRelationships] = {}


def _load_relationship_types(domain: str) -> _DomainRelationships:
    """
    Load and cache a domain's closed relationship_types list.

    Raises loudly on a bad/missing domain or malformed file — same
    fail-fast philosophy as ner_client._load_ontology, since silently
    extracting zero relationships with no obvious cause is worse than
    an explicit startup-time error.
    """
    if domain in _relationship_cache:
        return _relationship_cache[domain]

    path = ontology_loader.get_ontology_path(domain)
    if not path.exists():
        raise FileNotFoundError(f"Ontology file not found for domain '{domain}': {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    schema_version = raw.get("schema_version")
    if not schema_version:
        raise ValueError(f"Ontology file for '{domain}' is missing 'schema_version': {path}")

    raw_rels = raw.get("relationship_types")
    if not raw_rels:
        raise ValueError(f"Ontology file for '{domain}' has no 'relationship_types': {path}")

    relationships = [
        RelationshipType(
            predicate=r["relationship"],
            from_label=r["from"],
            to_label=r["to"],
        )
        for r in raw_rels
    ]

    domain_rels = _DomainRelationships(schema_version=schema_version, relationships=relationships)
    _relationship_cache[domain] = domain_rels
    logger.info(
        "Loaded %d relationship types for domain '%s' (schema_version=%s)",
        len(relationships), domain, schema_version,
    )
    return domain_rels


def clear_relationship_cache() -> None:
    """Call after an ontology file is edited (Phase 8), mirrors ner_client's helper."""
    _relationship_cache.clear()


# ---------------------------------------------------------------------------
# Triple shape
# ---------------------------------------------------------------------------
class CandidateEntity(BaseModel):
    """Minimal shape triple_extractor needs from a NER entity for prompting
    and validation. Caller (extractor.py) builds these from ner_client.Entity."""
    text: str
    label: str


class Triple(BaseModel):
    subject: str
    predicate: str
    object: str


# ---------------------------------------------------------------------------
# Prompting
# ---------------------------------------------------------------------------
def _build_prompt(chunk_text: str, entities: list[CandidateEntity], domain_rels: _DomainRelationships) -> str:
    entity_lines = "\n".join(f'  {i+1}. subject/object text: "{e.text}"  |  type: {e.label}' for i, e in enumerate(entities))

    # Build valid combinations explicitly so the LLM doesn't have to infer
    # which subject type is valid for each predicate — this is the main
    # source of label-mismatch drops when the model hallucinates a predicate
    # or swaps subject/object types.
    valid_combo_lines = "\n".join(
        f'  - predicate "{r.predicate}" requires: subject type={r.from_label}, object type={r.to_label}'
        for r in domain_rels.relationships
    )

    # Build a compact lookup the LLM can cross-reference when choosing subject/object
    entity_type_lookup = "\n".join(
        f'  "{e.text}" is type {e.label}' for e in entities
    )

    return f"""You are extracting structured relationships from a text chunk.

TEXT:
{chunk_text}

DETECTED ENTITIES (you may ONLY use these exact texts as subject or object values):
{entity_lines}

Entity type reference (use this to check validity before outputting a triple):
{entity_type_lookup}

VALID RELATIONSHIP COMBINATIONS (predicate with required subject and object types):
{valid_combo_lines}

RULES — read carefully before responding:
1. "subject" and "object" must be copied EXACTLY from the entity texts listed above (e.g. "Neural Networks", NOT "MachineLearningAlgorithm").
2. Do NOT use entity type names (like MachineLearningAlgorithm, TaskType) as subject or object values — those are types, not entity texts.
3. Before outputting each triple, verify: does the subject's type match the required subject type for that predicate? Does the object's type match the required object type? If not, skip that triple.
4. Only extract relationships explicitly stated or strongly implied in the TEXT above.
5. If no valid triple can be formed from the entities and relationships listed, output an empty array.

Respond with ONLY a JSON array, no preamble, no markdown fences, no explanation:
[{{"subject": "<exact entity text>", "predicate": "<predicate name>", "object": "<exact entity text>"}}, ...]

If no valid relationships exist: []
"""


def _parse_llm_response(raw: str) -> list[Triple]:
    """
    Parse the LLM's JSON array response. Tolerant of stray markdown
    fences (some local models wrap JSON in ```json blocks despite
    instructions not to) but otherwise strict — malformed JSON means
    zero triples for this chunk, not a crash for the whole document.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Triple extractor: LLM response was not valid JSON, dropping. Raw: %s", raw[:300])
        return []

    if not isinstance(parsed, list):
        logger.warning("Triple extractor: LLM response was not a JSON array, dropping. Raw: %s", raw[:300])
        return []

    triples: list[Triple] = []
    for item in parsed:
        try:
            triples.append(Triple(**item))
        except Exception as exc:
            logger.warning("Triple extractor: skipping malformed triple %r: %s", item, exc)
    return triples


def _validate_triple(
    triple: Triple,
    entities_by_text: dict[str, CandidateEntity],
    domain_rels: _DomainRelationships,
) -> bool:
    """
    Fail-closed validation per the ontology's "reject any triple whose
    predicate doesn't match one of these" instruction. Checks, in order:
      1. subject/object are both entities NER actually found in this chunk
      2. predicate is in the domain's closed relationship_types set
      3. subject/object NER labels match that predicate's declared from/to
    Logs a warning and returns False on any failure — caller drops the triple.
    """
    subject_entity = entities_by_text.get(triple.subject)
    object_entity = entities_by_text.get(triple.object)

    if subject_entity is None:
        logger.warning(
            "Dropping triple: subject %r is not a NER entity found in this chunk.", triple.subject
        )
        return False
    if object_entity is None:
        logger.warning(
            "Dropping triple: object %r is not a NER entity found in this chunk.", triple.object
        )
        return False

    matching_rel = next(
        (r for r in domain_rels.relationships if r.predicate == triple.predicate), None
    )
    if matching_rel is None:
        logger.warning(
            "Dropping triple: predicate %r is not in this domain's closed relationship_types.",
            triple.predicate,
        )
        return False

    if subject_entity.label != matching_rel.from_label:
        logger.warning(
            "Dropping triple: subject %r has NER label %r, expected %r for predicate %r.",
            triple.subject, subject_entity.label, matching_rel.from_label, triple.predicate,
        )
        return False
    if object_entity.label != matching_rel.to_label:
        logger.warning(
            "Dropping triple: object %r has NER label %r, expected %r for predicate %r.",
            triple.object, object_entity.label, matching_rel.to_label, triple.predicate,
        )
        return False

    return True


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
_llm = LocalLLMService()


async def extract_triples(
    chunk_text: str,
    entities: list[CandidateEntity],
    domain: str,
) -> list[Triple]:
    """
    Extract and validate typed Subject->Predicate->Object triples for one
    chunk, constrained to `domain`'s closed ontology relationship set.

    Returns an empty list (never raises) on:
      - fewer than 2 entities in the chunk (nothing to relate)
      - LLM timeout (logged, treated as "no relationships found this chunk"
        rather than failing the whole document's extraction transaction)
      - malformed/unparseable LLM output
      - every candidate triple failing validation

    Callers should NOT fall back to a generic edge type on empty results —
    an empty list is the correct, honest signal that no ontology-valid
    relationship was found in this chunk.
    """
    if len(entities) < 2:
        return []

    domain_rels = _load_relationship_types(domain)
    prompt = _build_prompt(chunk_text, entities, domain_rels)

    try:
        raw_response = await _llm.generate(prompt)
    except LocalLLMTimeoutError as exc:
        logger.warning("Triple extractor: LLM timed out for domain '%s', skipping chunk. %s", domain, exc)
        return []

    candidate_triples = _parse_llm_response(raw_response)
    if not candidate_triples:
        return []

    entities_by_text = {e.text: e for e in entities}
    valid_triples = [
        t for t in candidate_triples
        if _validate_triple(t, entities_by_text, domain_rels)
    ]

    logger.info(
        "Triple extractor: %d/%d candidate triples passed validation for domain '%s'.",
        len(valid_triples), len(candidate_triples), domain,
    )
    return valid_triples