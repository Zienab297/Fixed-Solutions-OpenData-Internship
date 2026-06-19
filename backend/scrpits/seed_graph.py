"""
scripts/seed_graph.py

Seeds the Apache AGE graph database with the medical + legal domain
ontologies. Safe to re-run (idempotent) because ontology_seed_age.cypher
uses MERGE, not CREATE, for every node/edge.

Run with:
    python -m scripts.seed_graph

Requires these env vars (matches the `age` service in
infrastructure/docker/docker-compose.dev.yml):
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
from pathlib import Path

import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_graph")

AGE_HOST = os.environ.get("AGE_HOST", "localhost")
AGE_PORT = os.environ.get("AGE_PORT", "5455")
AGE_DB = os.environ.get("AGE_DB", "agedb")
AGE_USER = os.environ.get("AGE_USER", "ageuser")
AGE_PASSWORD = os.environ.get("AGE_PASSWORD", "agepassword")
AGE_GRAPH_NAME = os.environ.get("AGE_GRAPH_NAME", "rag_ontology")

SEED_FILE = Path(__file__).parent / "ontology_seed.cypher"

# Commit every N statements rather than one giant transaction, so a
# failure midway tells you exactly which statement broke and earlier
# work isn't lost.
BATCH_SIZE = 20


def get_connection():
    conn = psycopg2.connect(
        host=AGE_HOST,
        port=AGE_PORT,
        dbname=AGE_DB,
        user=AGE_USER,
        password=AGE_PASSWORD,
    )
    return conn


def setup_session(cur):
    """Required AGE bootstrap per session: load extension, fix search_path."""
    cur.execute("LOAD 'age';")
    cur.execute('SET search_path = ag_catalog, "$user", public;')


def ensure_graph_exists(cur, graph_name: str):
    """Create the named graph if it doesn't already exist. Idempotent."""
    cur.execute(
        "SELECT count(*) FROM ag_graph WHERE name = %s;",
        (graph_name,),
    )
    exists = cur.fetchone()[0] > 0
    if exists:
        logger.info("Graph '%s' already exists, skipping creation.", graph_name)
    else:
        logger.info("Graph '%s' does not exist, creating it now.", graph_name)
        cur.execute("SELECT create_graph(%s);", (graph_name,))


def load_statements(seed_file: Path):
    """
    Parse the .cypher file into individual statements.

    Strips full-line comments (// ...) and blank lines, then splits on
    statement boundaries (each non-comment line in this seed file is
    exactly one statement, by construction).
    """
    statements = []
    with open(seed_file, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            statements.append(stripped)
    return statements


def wrap_for_age(graph_name: str, cypher_statement: str) -> str:
    """
    Wrap a raw Cypher statement in the SQL form AGE requires.

    AGE's cypher() function returns rows of agtype; for write statements
    (MERGE/MATCH..MERGE with no RETURN) we don't care about the return
    shape, so we use a generic (v agtype) result column.
    """
    # Escape single quotes inside the cypher body since the whole thing
    # is wrapped in $$ ... $$ dollar-quoting, which avoids most escaping
    # issues — this is exactly why $$ is used instead of '...'.
    return (
        f"SELECT * FROM cypher('{graph_name}', $$ {cypher_statement} $$) "
        f"AS (v agtype);"
    )


def run_seed():
    if not SEED_FILE.exists():
        logger.error("Seed file not found at %s", SEED_FILE)
        sys.exit(1)

    statements = load_statements(SEED_FILE)
    logger.info("Loaded %d statements from %s", len(statements), SEED_FILE.name)

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    try:
        setup_session(cur)
        ensure_graph_exists(cur, AGE_GRAPH_NAME)
        conn.commit()

        failed_statements = []
        for i, stmt in enumerate(statements, start=1):
            wrapped = wrap_for_age(AGE_GRAPH_NAME, stmt)
            try:
                cur.execute(wrapped)
            except Exception as exc:
                logger.error("Statement %d failed: %s", i, stmt[:80])
                logger.error("  -> %s", exc)
                failed_statements.append((i, stmt, str(exc)))
                conn.rollback()
                # Re-run session setup after rollback since it clears
                # search_path along with the failed statement.
                setup_session(cur)
                continue

            if i % BATCH_SIZE == 0:
                conn.commit()
                logger.info("Committed through statement %d/%d", i, len(statements))

        conn.commit()
        logger.info("Final commit done.")

        if failed_statements:
            logger.warning(
                "%d/%d statements failed. Review them before trusting the graph state:",
                len(failed_statements),
                len(statements),
            )
            for i, stmt, err in failed_statements:
                logger.warning("  [%d] %s | error: %s", i, stmt[:100], err)
        else:
            logger.info("All %d statements executed successfully.", len(statements))

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run_seed()
