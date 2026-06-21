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

--------------------------------------------------------------------------
Two things this module gets right that are easy to get wrong with AGE,
documented here so nobody "fixes" them back to the broken version later:

1. OUTPUT COLUMNS ARE NOT FREE-FORM.
   AGE requires `SELECT * FROM cypher(...) AS (col1 agtype, col2 agtype, ...)`
   to declare its column list at SQL-parse time. Postgres has no way to
   infer this from the Cypher body, so the caller MUST tell us how many
   columns the RETURN clause produces and (if it wants dict access by
   name) what to call them. scripts/seed_graph.py never hits this
   because every statement there is a bare MERGE/SET with no RETURN, so
   its single dummy `(v agtype)` column is never read. The moment a
   caller issues `RETURN n.foo AS foo` and expects `rows[0]["foo"]`,
   the column declaration MUST say `(foo agtype)` or the dict comes
   back keyed by whatever dummy name was declared instead — not a
   missing-key error you can intuit from the Cypher text itself.

   -> Every call that returns data MUST pass `columns=(...)` naming
      each RETURN'd value, in order. Calls that write with no RETURN
      can omit it (defaults to a single unread "v" column).

2. PARAMETERS MUST BE BOUND AS agtype, NOT AS A JSON STRING.
   Per AGE's own docs (Prepared Statements): the third argument to
   cypher() must be an agtype map, "or an error will be thrown" if it
   isn't. Binding json.dumps(params) as a plain SQL text parameter
   gives Postgres a TEXT value sitting where AGE expects an AGTYPE
   value — it does not get implicitly cast. The fix is to bind the
   JSON text as a normal parameter AND cast it explicitly in the SQL:
   `%(params)s::agtype`. agtype is a strict superset of JSON for plain
   maps of strings/numbers/bools/nulls/lists (see AGE's agtype docs),
   so json.dumps() output is valid agtype literal syntax once cast.

   No existing code in this repo exercised this path before (the seed
   script only ever uses literal-string Cypher, never bound params),
   so there was no prior convention to preserve here — this is the
   first real implementation of it.
--------------------------------------------------------------------------

Settings consumed (backend/app/core/config.py):
    AGE_HOST, AGE_PORT, AGE_DB, AGE_USER, AGE_PASSWORD, AGE_GRAPH_NAME,
    AGE_POOL_MIN_SIZE, AGE_POOL_MAX_SIZE
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional, Sequence

from psycopg import AsyncConnection, AsyncCursor
from psycopg import errors as pg_errors
from psycopg_pool import AsyncConnectionPool

from app.core.config import settings

logger = logging.getLogger("age_client")

# Matches an AGE vertex/edge/path agtype string suffix, e.g.:
#   {"id": 1125899906842625, "label": "Disease", "properties": {...}}::vertex
_AGTYPE_SUFFIX_RE = re.compile(r"::(vertex|edge|path)$")

_GRAPH_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# A bare default column name, used only for statements that issue no
# RETURN and whose result is never read (matches seed_graph.py's
# pattern: write-only statements don't care about the projection shape).
_DEFAULT_COLUMNS: tuple[str, ...] = ("v",)

# Errors worth a bounded retry: connection-level failures that a fresh
# connection from the pool is likely to recover from. Explicitly does
# NOT include data errors (constraint violations, AGE type errors,
# syntax errors) — retrying those just re-runs the same failure.
_TRANSIENT_EXCEPTIONS = (
    pg_errors.OperationalError,
    pg_errors.AdminShutdown,
    pg_errors.CannotConnectNow,
    ConnectionError,
    asyncio.TimeoutError,
)
_MAX_TRANSIENT_RETRIES = 2
_RETRY_BACKOFF_SECONDS = 0.5


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
    checkout-readiness, not just on first use. Commits immediately so
    this setup is durable on the connection independent of whatever
    transaction a caller later opens and possibly rolls back — per
    AGE's own docs, catalog/session state set here would otherwise be
    at risk of being undone by an unrelated rollback if it shared a
    transaction boundary with caller code.
    """
    async with conn.cursor() as cur:
        await cur.execute("LOAD 'age';")
        await cur.execute('SET search_path = ag_catalog, "$user", public;')
    await conn.commit()


# Module-level pool. Opened lazily on first use (or explicitly via
# startup_pool() from a FastAPI lifespan handler) so importing this
# module never tries to open a DB connection.
_pool: Optional[AsyncConnectionPool] = None
_pool_lock = asyncio.Lock()


async def get_pool() -> AsyncConnectionPool:
    """
    Lazily open the module-level pool. Lock-guarded so concurrent first
    callers (e.g. several asyncio tasks starting up at once) can't each
    open a separate pool — without the lock, two coroutines could both
    see `_pool is None` and both call AsyncConnectionPool(...), leaking
    one pool's connections with nothing left holding a reference to it.
    """
    global _pool
    if _pool is not None:
        return _pool
    async with _pool_lock:
        if _pool is None:
            pool = AsyncConnectionPool(
                conninfo=_conninfo(),
                min_size=settings.AGE_POOL_MIN_SIZE,
                max_size=settings.AGE_POOL_MAX_SIZE,
                configure=_configure_connection,
                open=False,
            )
            await pool.open(wait=True)
            logger.info(
                "AGE connection pool opened (min=%d, max=%d, host=%s:%s)",
                settings.AGE_POOL_MIN_SIZE,
                settings.AGE_POOL_MAX_SIZE,
                settings.AGE_HOST,
                settings.AGE_PORT,
            )
            _pool = pool
    return _pool


async def close_pool() -> None:
    """Call from FastAPI shutdown / worker teardown to close cleanly."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("AGE connection pool closed.")


def _wrap_for_age(
    graph_name: str,
    cypher_statement: str,
    params: Optional[dict] = None,
    columns: Sequence[str] = _DEFAULT_COLUMNS,
) -> tuple[str, Optional[dict]]:
    """
    Wrap a raw Cypher statement in the SQL form AGE requires.

    IMPORTANT: AGE's cypher() function requires its first argument (the
    graph name) to be a literal `name` constant — Postgres parses it
    specially at plan time, so it CANNOT be a bound parameter ($1 /
    %(graph_name)s). We validate graph_name against a strict identifier
    pattern first since it's going in via string formatting, not
    parameter binding — this keeps it safe despite not being a bind
    param (graph_name is only ever caller-supplied from settings/config,
    never raw user input, but we validate anyway as defense in depth).

    `columns` declares the AS (...) projection — see module docstring
    point 1. Each name is validated the same way graph_name is, since
    these are also going in via string formatting, not binding.

    `params`, if given, is bound as a real SQL parameter (safe from
    injection) but must be cast to ::agtype in the SQL text — see
    module docstring point 2 for why a plain text bind is not enough.
    """
    if not _GRAPH_NAME_RE.match(graph_name):
        raise ValueError(f"Invalid graph_name: {graph_name!r}")
    if not columns:
        raise ValueError("columns must declare at least one output column")
    for col in columns:
        if not _GRAPH_NAME_RE.match(col):
            raise ValueError(f"Invalid output column name: {col!r}")

    col_decl = ", ".join(f"{c} agtype" for c in columns)

    if params:
        sql = (
            f"SELECT * FROM cypher('{graph_name}', $$ {cypher_statement} $$, "
            f"%(params)s::agtype) AS ({col_decl});"
        )
        query_params = {"params": json.dumps(params)}
    else:
        sql = f"SELECT * FROM cypher('{graph_name}', $$ {cypher_statement} $$) AS ({col_decl});"
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
    Convert raw cursor rows into a list of parsed dicts, keyed by the
    column names actually declared in the SQL's AS (...) clause for
    this statement (i.e. whatever `columns` was passed to _wrap_for_age
    for this call) — NOT inferred from the Cypher RETURN text.
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
    columns: Sequence[str] = _DEFAULT_COLUMNS,
) -> list[dict]:
    """
    Execute a single Cypher statement against the given AGE graph and
    return parsed Python dicts (one per result row), keyed by `columns`.

    For a write-only statement with no RETURN, omit `columns` — the
    result is a list of empty/unread dicts and nothing inspects it.
    For a statement with `RETURN x AS foo, y AS bar`, pass
    `columns=("foo", "bar")` so rows[i]["foo"] / rows[i]["bar"] resolve.

    Retries a bounded number of times on transient connection-level
    failures (pool exhaustion blips, dropped connections) — NOT on
    data-level errors (bad Cypher, constraint violations, AGE type
    errors), which are raised immediately since retrying would just
    reproduce the same failure.

    For multi-statement transactions (e.g. Phase 5's "one transaction
    per document" requirement), use `transaction()` below instead and
    call `tx.run(...)` for each statement.
    """
    sql, query_params = _wrap_for_age(graph_name, cypher_statement, params, columns)

    last_exc: Optional[Exception] = None
    for attempt in range(1, _MAX_TRANSIENT_RETRIES + 2):
        pool = await get_pool()
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(sql, query_params)
                    rows = await _rows_to_dicts(cur)
                    await conn.commit()
                    return rows
        except _TRANSIENT_EXCEPTIONS as exc:
            last_exc = exc
            logger.warning(
                "Transient AGE connection error (attempt %d/%d): %s",
                attempt, _MAX_TRANSIENT_RETRIES + 1, exc,
            )
            if attempt <= _MAX_TRANSIENT_RETRIES:
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS * attempt)
                continue
            raise
        except Exception:
            logger.exception("Cypher statement failed: %s", cypher_statement[:200])
            raise

    raise last_exc  # type: ignore[misc]  # unreachable: loop always returns or raises


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
            rows = await tx.run(
                "MATCH (n {name: 'X'}) RETURN n.foo AS foo",
                columns=("foo",),
            )
        # commits here on clean exit; rolls back automatically on exception

    No retry logic here by design: a transaction is a sequence of
    statements that must all apply against the same connection/snapshot.
    Retrying a transient failure mid-transaction would mean re-running
    only the statements after the failure point against a connection
    that doesn't have the earlier statements applied — silently wrong.
    If a transient error occurs, the whole transaction is rolled back
    and raised; the caller (extractor.py, one transaction per document)
    decides whether to retry the entire document from scratch.
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

    async def run(
        self,
        cypher_statement: str,
        params: Optional[dict] = None,
        columns: Sequence[str] = _DEFAULT_COLUMNS,
    ) -> list[dict]:
        sql, query_params = _wrap_for_age(self._graph_name, cypher_statement, params, columns)
        await self._cur.execute(sql, query_params)
        return await _rows_to_dicts(self._cur)