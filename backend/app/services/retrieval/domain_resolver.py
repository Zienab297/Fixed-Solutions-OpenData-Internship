"""
backend/app/services/retrieval/domain_resolver.py

Query-time counterpart to GraphExtractor._resolve_domain_name (extractor.py).
Ingestion resolves ONE domain_id per document, synchronously, via
SessionLocal. Retrieval resolves MULTIPLE domain_ids per query, async,
via the already-open AsyncSession request scope (domain_service.get_domain).

Why this is its own module instead of living in ner.py or pipeline.py:
- Both ner.py (label selection) and pipeline.py (RBAC + graph domain
  filter) need the exact same UUID -> ontology-key mapping for the same
  query. Resolving it twice would mean two DB round trips and, worse,
  a chance for the two call sites to disagree if the Domain table
  changes between calls.
- Same validation contract as extractor.py: guessing domain.name.lower()
  against ner_client.get_known_domains() and failing loudly (not
  silently swallowing an unknown domain into an empty label set) if it
  doesn't match a real ontology key. See extractor.py's
  _resolve_domain_name docstring for the full rationale — this mirrors
  it exactly, just async and N-domains-at-once instead of sync/single.
"""
from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import domain_service
from app.services.ner import ner_client

logger = logging.getLogger("domain_resolver")


async def resolve_domain_names(
    db: AsyncSession,
    domain_ids: list[UUID],
) -> dict[UUID, str]:
    """
    Resolve each domain_id to its ontology key ("medical" / "legal"),
    validated against ner_client.get_known_domains() — the same
    authoritative set extractor.py validates against at ingestion time.

    Returns {domain_id: ontology_key} only for domains that resolved
    cleanly. A domain_id that doesn't match a known ontology key is
    logged and DROPPED, not raised — at query time, one unrecognized
    domain among several requested should degrade that domain's signal
    gracefully (pipeline.py already isolates signal failures elsewhere;
    this keeps that same philosophy), rather than failing the whole
    query the way extractor.py's single-document ingestion correctly
    fails loudly. If you need this to be a hard error instead (e.g. you
    want misconfigured domains caught immediately rather than silently
    skipped at query time), raise here instead of `continue`.

    Domains are fetched concurrently — this runs once per query (not
    once per chunk like ingestion), so the extra round trips are cheap
    and worth parallelizing.
    """
    if not domain_ids:
        return {}

    known = ner_client.get_known_domains()

    async def _resolve_one(domain_id: UUID) -> tuple[UUID, str] | None:
        try:
            domain = await domain_service.get_domain(db, domain_id)
        except Exception as exc:
            logger.warning("domain_id=%s: could not load domain (%s)", domain_id, exc)
            return None

        guessed_key = domain.name.strip().lower()
        if guessed_key not in known:
            logger.warning(
                "domain_id=%s (name=%r): resolved key %r not in known ontology "
                "domains %s — skipping this domain for query-time NER/graph.",
                domain_id, domain.name, guessed_key, sorted(known),
            )
            return None
        return domain_id, guessed_key

    resolved = await asyncio.gather(*(_resolve_one(d) for d in domain_ids))
    return {d_id: key for pair in resolved if pair for d_id, key in [pair]}


async def get_accessible_domain_names(
    db: AsyncSession,
    user_id: UUID,
    requested_domain_ids: list[UUID],
) -> dict[UUID, str]:
    """
    Intersects the domains a query asked for with the domains the user
    actually holds a role in (domain_service.get_user_domains), THEN
    resolves the surviving set to ontology keys.

    This is the RBAC gate for query-time NER/graph label selection:
    "combine domains if the user can access more than one, otherwise
    restrict to whatever they do have" — i.e. we never select GLiNER
    labels or run graph Cypher against a domain the user doesn't hold
    a role in, even if they passed its UUID in the request.

    Note: this is a defense-in-depth check for label/graph SCOPING, not
    a replacement for the server-side query-time RBAC enforcement
    already required elsewhere (§1.2/§1.3 — permissions checked at
    query time, not only in the UI). Vector/BM25/graph result filtering
    still needs its own authoritative RBAC check; this function only
    decides which domains' ontologies are eligible to drive NER label
    selection and graph traversal scope for this request.
    """
    user_roles = await domain_service.get_user_domains(db, user_id)
    accessible_ids = {role.domain_id for role in user_roles}

    allowed_ids = [d for d in requested_domain_ids if d in accessible_ids]
    dropped = set(requested_domain_ids) - accessible_ids
    if dropped:
        logger.info(
            "user_id=%s: dropped domain_ids %s from query scope — user has no role there.",
            user_id, sorted(str(d) for d in dropped),
        )

    return await resolve_domain_names(db, allowed_ids)
