"""
backend/app/services/graph/age_client.py

Single reusable async client for Apache AGE (Postgres graph extension).
Both ingestion (extractor.py, Phase 5) and retrieval (graph_search.py,
Phase 7) import this instead of reimplementing AGE's connection/session
boilerplate.

Mirrors the connection logic already proven in scripts/seed_graph.py
(LOAD 'age', search_path setup, search_path-reset-after-rollback), but:
  - async, via psycopg (v3) + psycopg_pool.AsyncConnectionPool, to match
    the project's async-FastAPI / asyncio.run-in-Celery convention
    (see app.workers.tasks.run_entity_extraction).
  - returns parsed Python dicts instead of raw agtype strings, since
    that's the shape extractor.py and graph_search.py actually need.

Settings consumed (backend/app/core/config.py):
    AGE_HOST, AGE_PORT, AGE_DB, AGE_USER, AGE_PASSWORD, AGE_GRAPH_NAME,
    AGE_POOL_MIN_SIZE, AGE_POOL_MAX_SIZE
"""
from __future__ import annotations

import json
import logging
import re
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

from psycopg import AsyncConnection, AsyncCursor
from psycopg_pool import AsyncConnectionPool

from app.core.config import settings

logger = logging.getLogger("age_client")

# Matches an AGE vertex/edge agtype string, e.g.:
#   {"id": 1125899906842625, "label": "Disease", "properties": {...}}::vertex
_AGTYPE_SUFFIX_RE = re.compile(r"::(vertex|edge|path)$")


def _conninfo() -> str:
    return (
        f"host={settings.AGE_HOST} "
        f"port={settings.AGE_PORT} "
        f"dbname={settings.AGE_DB} "
        f"user={settings.AGE_USER} "
        f"password={settings.AGE_PASSWORD}"
    )


async def _configure_connection(conn: AsyncConnection) -> None:
    """
    Required AGE bootstrap per connection: load extension, fix search_path.

    Registered as the pool's `configure` callback so every connection
    (including ones recycled by the pool) gets this applied once on
    checkout-readiness, not just on first use.
    """
    async with conn.cursor() as cur:
        await cur.execute("LOAD 'age';")
        await cur.execute('SET search_path = ag_catalog, "$user", public;')
    await conn.commit()


# Module-level pool. Opened lazily on first use (or explicitly via
# startup_pool() from a FastAPI lifespan handler) so importing this
# module never tries to open a DB connection.
_pool: Optional[AsyncConnectionPool] = None


async def get_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            conninfo=_conninfo(),
            min_size=settings.AGE_POOL_MIN_SIZE,
            max_size=settings.AGE_POOL_MAX_SIZE,
            configure=_configure_connection,
            open=False,
        )
        await _pool.open(wait=True)
        logger.info(
            "AGE connection pool opened (min=%d, max=%d, host=%s:%s)",
            settings.AGE_POOL_MIN_SIZE,
            settings.AGE_POOL_MAX_SIZE,
            settings.AGE_HOST,
            settings.AGE_PORT,
        )
    return _pool


async def close_pool() -> None:
    """Call from FastAPI shutdown / worker teardown to close cleanly."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("AGE connection pool closed.")


_GRAPH_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _wrap_for_age(graph_name: str, cypher_statement: str, params: Optional[dict] = None) -> tuple[str, Optional[dict]]:
    """
    Wrap a raw Cypher statement in the SQL form AGE requires.

    IMPORTANT: AGE's cypher() function requires its first argument (the
    graph name) to be a literal `name` constant — Postgres parses it
    specially at plan time, so it CANNOT be a bound parameter ($1 /
    %(graph_name)s). This matches what seed_graph.py already does via
    f-string interpolation. We validate graph_name against a strict
    identifier pattern first since it's going in via string formatting,
    not parameter binding — this keeps it safe despite not being a bind
    param (graph_name is only ever caller-supplied from settings/config,
    never raw user input, but we validate anyway as defense in depth).

    The Cypher body and optional params map (third arg to cypher()) are
    NOT subject to this restriction and are passed as a normal bound
    parameter.
    """
    if not _GRAPH_NAME_RE.match(graph_name):
        raise ValueError(f"Invalid graph_name: {graph_name!r}")

    if params:
        sql = (
            f"SELECT * FROM cypher('{graph_name}', $$ {cypher_statement} $$, %(params)s) "
            f"AS (v agtype);"
        )
        query_params = {"params": json.dumps(params)}
    else:
        sql = f"SELECT * FROM cypher('{graph_name}', $$ {cypher_statement} $$) AS (v agtype);"
        query_params = None
    return sql, query_params


def _parse_agtype(value: Any) -> Any:
    """
    Parse a single agtype column value into a plain Python object.

    agtype values come back from psycopg as strings like:
        '{"id": 123, "label": "Disease", "properties": {...}}::vertex'
        '"Amoxicillin"'
        '42'
        'true'
    Strip the trailing ::vertex/::edge/::path type suffix if present,
    then json.loads the remainder. Falls back to the raw string if it's
    not valid JSON (e.g. bare identifiers AGE occasionally returns).
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return value

    text = _AGTYPE_SUFFIX_RE.sub("", value)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return value


async def _rows_to_dicts(cur: AsyncCursor) -> list[dict]:
    """
    Convert raw cursor rows (each a 1-tuple containing one agtype column,
    per the `AS (v agtype)` projection) into a list of parsed dicts.

    AGE's cypher() always projects through a single-or-multi-column
    (v agtype) shape; for the common case of `RETURN n` or `RETURN n, r`
    each row maps to {"v": ...} or {"col0": ..., "col1": ...} keyed by
    the cursor's declared column names.
    """
    if cur.description is None:
        return []
    col_names = [desc.name for desc in cur.description]
    rows = await cur.fetchall()
    result = []
    for row in rows:
        parsed = {col: _parse_agtype(val) for col, val in zip(col_names, row)}
        result.append(parsed)
    return result


async def run_cypher(
    graph_name: str,
    cypher_statement: str,
    params: Optional[dict] = None,
) -> list[dict]:
    """
    Execute a single Cypher statement against the given AGE graph and
    return parsed Python dicts (one per result row).

    Each call checks out its own pooled connection, runs in autocommit-off
    mode, and commits on success / rolls back + re-applies search_path on
    failure (the AGE quirk documented in seed_graph.py: a failed statement's
    rollback also clears search_path for the rest of that session).

    For multi-statement transactions (e.g. Phase 5's "one transaction per
    document" requirement), use `transaction()` below instead and call
    `run_cypher_in(cur, ...)` for each statement.
    """
    pool = await get_pool()
    sql, query_params = _wrap_for_age(graph_name, cypher_statement, params)

    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            try:
                await cur.execute(sql, query_params)
                rows = await _rows_to_dicts(cur)
                await conn.commit()
                return rows
            except Exception:
                logger.exception("Cypher statement failed: %s", cypher_statement[:200])
                await conn.rollback()
                # Rollback clears search_path on this connection; restore
                # it before the connection goes back to the pool, so the
                # next checkout doesn't silently fail on a missing path.
                await _configure_connection(conn)
                raise


@asynccontextmanager
async def transaction(graph_name: str) -> AsyncIterator["GraphTransaction"]:
    """
    Context manager for running multiple Cypher statements as one
    all-or-nothing transaction (Phase 5 requirement: a failure partway
    through a document's extraction shouldn't leave half its graph
    data committed).

    Usage:
        async with age_client.transaction(settings.AGE_GRAPH_NAME) as tx:
            await tx.run("MERGE (d:Disease {name: 'X'}) ...")
            await tx.run("MERGE (dr:Drug {name: 'Y'}) ...")
        # commits here on clean exit; rolls back automatically on exception
    """
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            tx = GraphTransaction(conn=conn, cur=cur, graph_name=graph_name)
            try:
                yield tx
                await conn.commit()
            except Exception:
                logger.exception("Transaction failed for graph '%s', rolling back.", graph_name)
                await conn.rollback()
                await _configure_connection(conn)
                raise


class GraphTransaction:
    """Thin handle passed into the `transaction()` context manager."""

    def __init__(self, conn: AsyncConnection, cur: AsyncCursor, graph_name: str):
        self._conn = conn
        self._cur = cur
        self._graph_name = graph_name

    async def run(self, cypher_statement: str, params: Optional[dict] = None) -> list[dict]:
        sql, query_params = _wrap_for_age(self._graph_name, cypher_statement, params)
        await self._cur.execute(sql, query_params)
        return await _rows_to_dicts(self._cur)