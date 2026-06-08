"""
Graph retrieval via Apache AGE (Postgres extension).
Activated by query-time NER when entities are detected.
"""
from typing import List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


class GraphSearchService:
    async def search(
        self,
        entities: List[Tuple[str, str]],
        domain_ids: List,
        db: AsyncSession = None,
    ) -> List[dict]:
        """
        Issue Cypher queries via Apache AGE for entity-centric retrieval.
        RBAC enforced via domain-tagged nodes.
        """
        if not db or not entities:
            return []

        results = []
        domain_id_strings = [str(d) for d in domain_ids]

        for entity_text, entity_type in entities:
            try:
                # Cypher query via AGE — find entity and its relationships
                result = await db.execute(
                    text("""
                        SELECT * FROM ag_catalog.cypher('knowledge_graph', $$
                            MATCH (e {name: $entity_name, type: $entity_type})-[r]-(related)
                            WHERE e.domain_id IN $domain_ids
                            RETURN e, r, related, type(r) as relation_type
                            LIMIT 10
                        $$, $1) AS (entity agtype, relation agtype, related agtype, relation_type agtype)
                    """),
                    {
                        "1": {
                            "entity_name": entity_text,
                            "entity_type": entity_type,
                            "domain_ids": domain_id_strings,
                        }
                    },
                )
                rows = result.fetchall()
                for row in rows:
                    results.append({
                        "node_id": str(row.entity),
                        "entity_type": entity_type,
                        "entity_name": entity_text,
                        "path": [entity_text, str(row.relation_type), str(row.related)],
                    })
            except Exception:
                # Graph may not have this entity — graceful fallback
                continue

        return results
