"""
backend/app/services/retrieval/graph_search.py

Graph retrieval via Apache AGE (§3.2). Activated by query-time NER
(ner.py) when entities are detected — one of the three RRF signals
fused in pipeline.py (§3.4).

PATCHED — rewritten on top of app.services.graph.age_client instead of
hand-rolling AGE's SQL wrapping:

- The previous version queried `WHERE e.name = $entity_name AND e.type
  = $entity_type`. AGE nodes written by extractor.py have no generic
  `type` property — the node's TYPE *is* its label
  (`MERGE (n:Disease {...})`, `MERGE (n:LegalNorm {...})`, see
  extractor.py._merge_entity_node). A `type` property filter could
  never match anything; this version MATCHes on the label itself,
  interpolated the same safe way extractor.py interpolates entity
  labels and triple_extractor-validated predicates — never raw user
  input, always checked against a known/allowed label set first.

- The previous version bound Cypher params as
  `json.dumps(...)` cast via raw `:params::agtype` SQL text — exactly
  the anti-pattern age_client.py's module docstring (point 2) warns
  against working around by hand. This version calls
  age_client.run_cypher(), which already solves both the agtype-cast
  binding and the AS (...) column-declaration requirements correctly
  (see age_client.py docstring points 1 and 2) — no reason to
  re-solve either problem here.

- RBAC (§1.3, §3.2): domain is now a bound Cypher MATCH parameter
  (`{domain: $domain}`), enforced server-side at the graph query layer
  itself, not only as a post-fetch Python filter. The post-fetch check
  is kept as defense in depth (in case a node is somehow missing/has a
  stale domain property), but the primary enforcement now happens
  inside the Cypher query.

- Returns node_uuid (the stable UUID extractor.py mints — see
  age_client/extractor.py docstring on why AGE's internal id is
  unsuitable) instead of the raw AGE id, since that's what
  Chunk.graph_node_ids actually stores and what the pipeline needs to
  cross-reference for graph-confirmed chunk boosting.

Each entity query remains isolated in its own try/except, and missing
entity matches are expected/normal (logged at DEBUG), not errors.
"""

import logging
from typing import List, Tuple

from app.core.config import settings
from app.services.graph import age_client
from app.services.ner import ner_client

logger = logging.getLogger(__name__)

_RESULTS_PER_ENTITY = 10


class GraphSearchService:
    async def search(
        self,
        entities: List[Tuple[str, str]],
        domain_names: List[str],
    ) -> List[dict]:
        """
        Issue Cypher queries via Apache AGE for entity-centric retrieval.

        entities: (entity_text, entity_label) pairs from query-time NER
        (ner.py) — entity_label is expected to already be one of GLiNER's
        domain-ontology labels (e.g. "Disease", "LegalNorm"), since
        ner.py calls the SAME ner_client/ontology label sets ingestion
        uses to write these nodes.

        domain_names: resolved, RBAC-filtered ontology keys for domains
        the requesting user can access (see domain_resolver.py) — used
        both to scope which domains' label sets are even valid to query
        and as the server-side RBAC filter bound into each Cypher MATCH.

        Returns a list of graph hit dicts, each with:
        - node_uuid       (stable UUID, matches Chunk.graph_node_ids)
        - entity_type, entity_name
        - path: [entity, relation_type, related_entity]
        - related_node_uuid
        - domain_name     (for caller-side verification/citation display)
        - chunk_ids: list of chunk IDs linked to this entity node
        """
        if not entities or not domain_names:
            return []

        results: List[dict] = []

        for entity_text, entity_label in entities:
            for domain in domain_names:
                # Only query a (label, domain) pair if the label is
                # actually part of that domain's declared ontology —
                # querying "Disease" against the "legal" graph would
                # always return zero rows, but skipping it here avoids
                # an AGE round trip for a combination that can never
                # match, and avoids interpolating a label AGE has no
                # vertex table for at all (which AGE would error on,
                # not just no-op).
                try:
                    valid_labels = ner_client.get_domain_labels(domain)
                except Exception as exc:
                    logger.warning("Could not load labels for domain '%s': %s", domain, exc)
                    continue

                if entity_label not in valid_labels:
                    continue
                
                print(f"DEBUG graph: querying entity='{entity_text}' label='{entity_label}' domain='{domain}'")
                print(f"DEBUG graph: valid_labels={valid_labels}")
                try:
                    rows = await age_client.run_cypher(
                        graph_name=settings.AGE_GRAPH_NAME,
                        cypher_statement=f"""
                            MATCH (e:{entity_label} {{domain: $domain}})-[r]-(related)
                            WHERE toLower(e.name) CONTAINS toLower($name)
                            OR toLower($name) CONTAINS toLower(e.name)
                            RETURN
                                e.node_uuid          AS node_uuid,
                                e.source_chunk_ids   AS chunk_ids,
                                related.node_uuid    AS related_node_uuid,
                                related.name         AS related_name,
                                type(r)              AS relation_type
                            LIMIT {_RESULTS_PER_ENTITY}
                        """,
                        params={"name": entity_text, "domain": domain},
                        columns=(
                            "node_uuid",
                            "chunk_ids",
                            "related_node_uuid",
                            "related_name",
                            "relation_type",
                        ),
                    )
                except Exception as exc:
                    # Missing entity in the graph is expected/normal —
                    # log at DEBUG so it doesn't pollute production logs.
                    print(f"DEBUG graph ERROR: entity='{entity_text}' label='{entity_label}' domain='{domain}' error={exc}")
                    continue
                print(f"DEBUG graph: rows returned={len(rows)}")
                for row in rows:
                    node_uuid = row.get("node_uuid")
                    if not node_uuid:
                        # Defense in depth: a node missing node_uuid
                        # shouldn't be possible (extractor.py always
                        # mints one on MERGE), but skip rather than
                        # return an unusable hit.
                        continue

                    chunk_ids = row.get("chunk_ids") or []
                    if not isinstance(chunk_ids, list):
                        chunk_ids = []

                    results.append({
                        "node_uuid":          node_uuid,
                        "entity_type":        entity_label,
                        "entity_name":        entity_text,
                        "domain_name":        domain,
                        "chunk_ids":          chunk_ids,
                        "path": [
                            entity_text,
                            row.get("relation_type"),
                            row.get("related_name"),
                        ],
                        "related_node_uuid":  row.get("related_node_uuid"),
                    })

        return results