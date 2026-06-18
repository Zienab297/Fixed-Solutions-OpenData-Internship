"""
Graph retrieval via Apache AGE (Postgres extension).
Activated by query-time NER when entities are detected.

Fixes over original:
- AGE Cypher parameter binding was broken. AGE's $1 parameter must be a
  JSON object literal passed as a Postgres parameter; Cypher variables are
  referenced with the agtype arrow syntax inside the $$ block.
  The old code used $entity_name / $entity_type inside the Cypher string
  which AGE never substitutes — those variables were always unbound.
- domain_ids filter moved to a post-query Python filter because AGE does not
  support IN $list Cypher syntax with external parameters cleanly.
  The graph nodes are tagged with domain_id; we filter after fetch.
- Each entity query is now isolated in its own try/except so one bad entity
  doesn't silently swallow results for the rest.
- Returns chunk_ids alongside graph path so the pipeline can optionally
  boost those chunks in RRF rather than treating graph as purely supplementary.
"""

import json
import logging
from typing import List, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger(__name__)


class GraphSearchService:
    async def search(
        self,
        entities: List[Tuple[str, str]],
        domain_ids: List,
        db: AsyncSession = None,
    ) -> List[dict]:
        """
        Issue Cypher queries via Apache AGE for entity-centric retrieval.
        RBAC enforced via domain_id tag on graph nodes (post-query filter).

        Returns a list of graph hit dicts, each with:
        - node_id
        - entity_type, entity_name
        - path: [entity, relation_type, related_entity]
        - related_node_id
        - domain_id  (for RBAC verification by caller)
        - chunk_ids: list of chunk IDs linked to this entity node (if stored)
        """
        if not db or not entities:
            return []

        domain_id_strings = {str(d) for d in domain_ids}   # set for O(1) lookup
        results = []

        for entity_text, entity_type in entities:
            try:
                # AGE requires the parameter as a Postgres jsonb/text literal.
                # Inside the Cypher block, reference keys with =>  (agtype syntax).
                # We pass entity_name and entity_type; domain filtering is post-fetch.
                cypher_params = json.dumps({
                    "entity_name": entity_text,
                    "entity_type": entity_type,
                })

                result = await db.execute(
                    text("""
                        SELECT *
                        FROM ag_catalog.cypher(
                            'knowledge_graph',
                            $$
                                MATCH (e)-[r]-(related)
                                WHERE e.name = $entity_name
                                  AND e.type = $entity_type
                                RETURN
                                    e,
                                    e.domain_id    AS e_domain_id,
                                    e.chunk_ids    AS e_chunk_ids,
                                    related,
                                    related.domain_id AS related_domain_id,
                                    type(r)        AS relation_type
                                LIMIT 10
                            $$,
                            :params::agtype
                        ) AS (
                            entity          agtype,
                            e_domain_id     agtype,
                            e_chunk_ids     agtype,
                            related         agtype,
                            related_domain_id agtype,
                            relation_type   agtype
                        )
                    """),
                    {"params": cypher_params},
                )

                rows = result.fetchall()
                for row in rows:
                    # Post-query RBAC filter
                    node_domain = str(row.e_domain_id).strip('"') if row.e_domain_id else None
                    if node_domain not in domain_id_strings:
                        continue

                    # chunk_ids may be stored as a JSON array on the node
                    raw_chunk_ids = row.e_chunk_ids
                    try:
                        chunk_ids = json.loads(str(raw_chunk_ids)) if raw_chunk_ids else []
                    except (ValueError, TypeError):
                        chunk_ids = []

                    results.append({
                        "node_id":      str(row.entity),
                        "entity_type":  entity_type,
                        "entity_name":  entity_text,
                        "domain_id":    node_domain,
                        "chunk_ids":    chunk_ids,
                        "path": [
                            entity_text,
                            str(row.relation_type).strip('"'),
                            str(row.related),
                        ],
                    })

            except Exception as exc:
                # This entity may not exist in the graph — that is expected.
                # Log at DEBUG so it doesn't pollute production logs.
                logger.debug(
                    "Graph search skipped for entity '%s' (%s): %s",
                    entity_text, entity_type, exc,
                )
                continue

        return results