"""
scripts/index_node_uuid.py

ROOT-CAUSE FIX for: _merge_typed_relationships in extractor.py does
`MATCH (a {node_uuid: $x})` with NO label (node_uuid is meant to be
globally unique across every label/domain), which means Postgres has
to check every per-label vertex table with no index to narrow the scan.
Fine at ontology-seed scale (142 nodes); will not hold up anywhere near
the ~50M node MVP target in the requirements doc (§3.2 / §6.3).

--------------------------------------------------------------------------
THIS SCRIPT WENT THROUGH TWO WRONG VERSIONS BEFORE THIS ONE. Both
failures are documented here so nobody reintroduces them:

WRONG VERSION 1: `(properties->>'node_uuid')`
    Fails outright: `properties` is typed `agtype`, not `jsonb`. The
    plain `->>` operator does not exist for agtype at all. Confirmed
    against a real run:
        ERROR: operator does not exist: ag_catalog.agtype ->> unknown

WRONG VERSION 2: btree on `agtype_access_operator(properties, '"node_uuid"'::agtype)`
    Runs without error, but doesn't speed up the actual query.
    `agtype_access_operator` via btree is what AGE uses for a Cypher
    WHERE-clause filter (`WHERE n.node_uuid = $x`). extractor.py's real
    query is a MATCH-PATTERN filter — `MATCH (a {node_uuid: $x})` — and
    AGE compiles that shape into a `properties @> agtype_build_map(...)`
    CONTAINMENT check, not an `agtype_access_operator` equality check.
    A containment check is satisfied by a GIN index on the whole
    `properties` column, not a btree on one extracted key. Confirmed
    against AGE's own documented query plans: a GIN index on properties
    produces `Bitmap Heap Scan ... Recheck Cond: (properties @> '{...}'
    ::agtype)`, used by exactly this MATCH-pattern shape; the btree/
    agtype_access_operator path only lights up for WHERE-clause filters.

    (If extractor.py or graph_search.py ever switches this specific
    lookup to a WHERE-clause form instead of a MATCH pattern, THAT would
    need the btree/agtype_access_operator index instead — the two index
    types serve two different Cypher syntaxes, not two ways of writing
    the same query. Check the actual query shape before reusing either
    approach elsewhere.)

THIS VERSION: GIN index on the whole `properties` column, per label.
    Matches the query shape actually in extractor.py today.
--------------------------------------------------------------------------

WHY THIS IS A SEPARATE SCRIPT, NOT A SINGLE CREATE INDEX STATEMENT:
AGE does not store all vertices in one physical table. Per AGE's own
docs: creating a graph creates two PARENT tables, `_ag_label_vertex` and
`_ag_label_edge`; every vertex LABEL you actually use (Disease, Drug,
LegalNorm, ...) gets its own CHILD table under the graph's Postgres
schema, e.g. `rag_ontology."Disease"`, `rag_ontology."Drug"`, etc.
These child tables do not automatically inherit an index you put on the
shared parent — an index has to be created on each child table that
exists, or the unlabeled MATCH above still falls through to an
unindexed scan on whichever label happens to hold the matching node.

This script therefore:
  1. Discovers every vertex label that currently exists for the target
     graph (from ag_catalog.ag_label — kind = 'v'), instead of a
     hardcoded list. Correct today (17 labels per the real seeded
     graph) AND correct after Phase 8 adds new labels, with no edits
     needed.
  2. Creates a GIN index on the whole `properties` column for each
     label, IF NOT EXISTS, so it's safe to re-run after every ontology
     change (new labels just get indexed on the next run; existing
     indexes are untouched).
  3. Skips the two internal parent tables themselves — they hold no
     vertices directly (AGE only ever inserts into the per-label child
     tables), so indexing them is a no-op that just adds confusion.

NOTE ON SPECIFICITY: a GIN index on the whole `properties` column
speeds up containment checks on ANY property, not just node_uuid —
which is strictly fine (it's a superset of what's needed) but means
this index also accelerates other MATCH-pattern filters (e.g. `MATCH
(d:Disease {name: "X"})`) "for free". There is no narrower GIN-style
index limited to a single key in AGE today; if that ever becomes a
real cost concern (GIN indexes are larger and slower to update than
btree), revisit — but for the ontology's current per-label row counts
this is not a concern.

WHEN TO RUN: once after scripts/seed_graph.py, and again any time a
new vertex label is introduced (e.g. a Phase 8 ontology update) BEFORE
real extraction traffic starts writing nodes under that label — an
index created after the fact still works, it's just a slower CREATE
INDEX (full table scan) instead of an instant one on an empty table.
This is schema-maintenance DDL, not per-document data — it belongs in
your deploy/migration step, not in the Celery extraction task itself.

Run with (matches the AGE service in
infrastructure/docker/docker-compose.dev.yml):
    python -m scripts.index_node_uuid

Requires the same env vars as scripts/seed_graph.py:
    AGE_HOST       (default: localhost)
    AGE_PORT       (default: 5455)
    AGE_DB         (default: agedb)
    AGE_USER       (default: ageuser)
    AGE_PASSWORD   (default: agepassword)
    AGE_GRAPH_NAME (default: rag_ontology)
"""
import os
import sys
import logging

import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("index_node_uuid")

AGE_HOST = os.environ.get("AGE_HOST", "localhost")
AGE_PORT = os.environ.get("AGE_PORT", "5455")
AGE_DB = os.environ.get("AGE_DB", "agedb")
AGE_USER = os.environ.get("AGE_USER", "ageuser")
AGE_PASSWORD = os.environ.get("AGE_PASSWORD", "agepassword")
AGE_GRAPH_NAME = os.environ.get("AGE_GRAPH_NAME", "rag_ontology")

# AGE's own internal parent tables — never hold vertices directly,
# always skip these even though they show up in ag_label.
_INTERNAL_PARENT_TABLES = {"_ag_label_vertex", "_ag_label_edge"}


def get_connection():
    return psycopg2.connect(
        host=AGE_HOST, port=AGE_PORT, dbname=AGE_DB, user=AGE_USER, password=AGE_PASSWORD,
    )


def setup_session(cur):
    cur.execute("LOAD 'age';")
    cur.execute('SET search_path = ag_catalog, "$user", public;')


def discover_vertex_labels(cur, graph_name: str) -> list[str]:
    """
    Return every vertex label name AGE currently has registered for
    this graph, excluding the two internal parent tables. This is the
    live source of truth — it reflects exactly what ontology_seed.cypher
    (and any later extraction/admin-driven label creation) has actually
    created, not a hardcoded guess that can drift from reality.
    """
    cur.execute(
        """
        SELECT label.name
        FROM ag_catalog.ag_label AS label
        JOIN ag_catalog.ag_graph AS graph ON label.graph = graph.graphid
        WHERE graph.name = %s AND label.kind = 'v';
        """,
        (graph_name,),
    )
    rows = cur.fetchall()
    return [r[0] for r in rows if r[0] not in _INTERNAL_PARENT_TABLES]


def ensure_properties_gin_index(cur, graph_name: str, label: str) -> bool:
    """
    Create a GIN index on this label's entire `properties` column, if
    one doesn't already exist. Returns True if created, False if it
    already existed.

    WHY GIN ON THE WHOLE COLUMN, NOT A FUNCTIONAL INDEX ON ONE KEY:
    extractor.py's actual query is a MATCH-pattern property filter
    (`MATCH (a {node_uuid: $x})`), which AGE compiles to a `properties
    @> agtype_build_map(...)` containment check — and a containment
    check on a jsonb/agtype-like column is satisfied by GIN, not by a
    btree on one extracted key (that combination only helps WHERE-
    clause equality filters, a different Cypher syntax entirely). See
    module docstring for the two wrong approaches already ruled out.

    Index name is deterministic and namespaced by label so re-running
    this script is always idempotent and never collides across labels.
    """
    index_name = f"idx_{label.lower()}_properties_gin"
    cur.execute(
        """
        SELECT 1 FROM pg_indexes
        WHERE schemaname = %s AND indexname = %s;
        """,
        (graph_name, index_name),
    )
    if cur.fetchone() is not None:
        return False

    # Label/graph names come from AGE's own catalog (ag_label), not
    # from caller input, so they're trusted here the same way
    # age_client.py trusts graph_name from settings — but identifiers
    # are still quoted properly rather than bare string formatting.
    cur.execute(
        f'CREATE INDEX IF NOT EXISTS "{index_name}" '
        f'ON {graph_name}."{label}" USING GIN (properties);'
    )
    return True


def run():
    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()
    try:
        setup_session(cur)
        conn.commit()

        labels = discover_vertex_labels(cur, AGE_GRAPH_NAME)
        if not labels:
            logger.warning(
                "No vertex labels found for graph '%s'. Has scripts/seed_graph.py "
                "been run yet? Nothing to index.", AGE_GRAPH_NAME,
            )
            return

        logger.info("Found %d vertex label(s) for graph '%s': %s", len(labels), AGE_GRAPH_NAME, labels)

        created, skipped = 0, 0
        for label in labels:
            try:
                if ensure_properties_gin_index(cur, AGE_GRAPH_NAME, label):
                    logger.info('Created properties GIN index on %s."%s"', AGE_GRAPH_NAME, label)
                    created += 1
                else:
                    logger.info('properties GIN index already exists on %s."%s", skipping.', AGE_GRAPH_NAME, label)
                    skipped += 1
                conn.commit()
            except Exception as exc:
                logger.error("Failed to index label '%s': %s", label, exc)
                conn.rollback()
                setup_session(cur)

        logger.info("Done. %d index(es) created, %d already present.", created, skipped)

        if created or skipped:
            logger.info(
                "Verify with EXPLAIN before trusting this in production, e.g.:\n"
                "    SELECT * FROM cypher('%s', $$ EXPLAIN MATCH (a {node_uuid: 'some-uuid'}) "
                "RETURN a $$) AS (plan agtype);\n"
                "and confirm the plan shows a Bitmap Index Scan on one of the indexes "
                "just created, not a Seq Scan.",
                AGE_GRAPH_NAME,
            )

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run()