"""
backend/app/core/metrics.py

Centralized Prometheus metric definitions for system observability
(MVP requirements §6.2 — query latency, retrieval hit rate, graph
query latency, model routing distribution; judge LLM queue depth and
evaluation latency are covered separately via a Celery/Redis exporter,
not custom code here, since they don't depend on judge.py's internals
being finished).

Import this module ONCE, early, from main.py — that's what registers
these Counter/Histogram objects with prometheus_client's default
collector registry before /metrics is exposed. Every other module
that needs to record a metric imports the specific object it needs
from here (e.g. `from app.core.metrics import LLM_ROUTE_TOTAL`)
rather than redefining it, since prometheus_client raises a
ValueError on duplicate metric names registered twice.
"""
from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Retrieval signal latency + hit rate (§6.2) — per-signal (vector/
# bm25/graph) timing and hit/miss outcome, recorded by
# RetrievalPipeline._timed() in pipeline.py around each signal
# coroutine. RETRIEVAL_HIT_RATE{signal="vector",outcome="hit"} divided
# by the sum across outcomes for that signal gives per-signal hit rate
# in Grafana.
# ---------------------------------------------------------------------------
RETRIEVAL_SIGNAL_LATENCY = Histogram(
    "rag_retrieval_signal_latency_seconds",
    "Latency of an individual retrieval signal (vector/bm25/graph) coroutine",
    ["signal"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

RETRIEVAL_HIT_RATE = Counter(
    "rag_retrieval_hit_rate_total",
    "Count of retrieval signal invocations by hit/miss outcome",
    ["signal", "outcome"],
)

# ---------------------------------------------------------------------------
# Graph query latency (§6.2) — the "graph" signal's timing, observed
# separately/in addition to RETRIEVAL_SIGNAL_LATENCY above so AGE
# latency can be graphed on its own panel without filtering. Unlabeled
# (no graph_name) since pipeline.py's _timed() only fires this for a
# single signal name == "graph" call per query, not per-ontology.
# ---------------------------------------------------------------------------
GRAPH_QUERY_LATENCY = Histogram(
    "rag_graph_query_latency_seconds",
    "Latency of the graph (Apache AGE) retrieval signal specifically",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

# ---------------------------------------------------------------------------
# End-to-end query latency (§6.2) — full /query request duration
# (retrieval + generation + response assembly), labeled by which LLM
# tier actually served it. Distinct from http_request_duration_seconds
# (generic per-route HTTP timing from Instrumentator in main.py) since
# this is specifically the RAG pipeline's own latency, recorded in
# query.py's try/finally regardless of which return path was hit.
# ---------------------------------------------------------------------------
RAG_QUERY_LATENCY = Histogram(
    "rag_query_latency_seconds",
    "End-to-end /query request latency (retrieval + generation), labeled by LLM route",
    ["llm_route"],
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)

# ---------------------------------------------------------------------------
# Model routing distribution (§3.5 / §6.2) — local vs. api per query.
# Label is `llm_route` (not `route`) to match the call site in
# query.py and the `llm_route` variable used throughout that module.
# ---------------------------------------------------------------------------
LLM_ROUTE_TOTAL = Counter(
    "rag_llm_route_total",
    "Count of generation requests routed to each LLM tier",
    ["llm_route"],
)

# ---------------------------------------------------------------------------
# Celery worker observability (§6.2) — covers judge evaluation latency
# (rag_celery_task_duration_seconds with task_name="...run_judge_evaluation")
# and judge LLM queue depth (rag_celery_queue_depth{queue="evaluation"}),
# plus the same for ingestion/extraction tasks for free. Populated by
# app/workers/observability.py, which must be imported by celery_app.py
# for the signal handlers to actually fire.
# ---------------------------------------------------------------------------
CELERY_TASK_DURATION_SECONDS = Histogram(
    "rag_celery_task_duration_seconds",
    "Wall-clock duration of a Celery task from prerun to postrun",
    ["task_name"],
    buckets=(0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)

CELERY_TASK_FAILURES_TOTAL = Counter(
    "rag_celery_task_failures_total",
    "Count of Celery tasks that raised an unhandled exception",
    ["task_name"],
)

CELERY_QUEUE_DEPTH = Gauge(
    "rag_celery_queue_depth",
    "Number of messages currently waiting (not yet claimed) on a Celery queue, sampled from the broker",
    ["queue"],
)