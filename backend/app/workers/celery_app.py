"""
Celery application configuration.
Three queues: ingestion, evaluation, extraction.

PATCHED — Windows event loop policy fix:
Tasks that use psycopg async (run_entity_extraction -> age_client.py)
call asyncio.run(...) inside the worker process. On Windows, a freshly
spawned process defaults to ProactorEventLoop, which psycopg's async
mode explicitly refuses to run under ("Psycopg cannot use the
'ProactorEventLoop' to run in async mode"). This must be set before
ANY event loop is created in the process — celery_app.py is the first
app-specific module the worker imports, so it's set here, once, for
the whole process, rather than per-task in tasks.py (which would be
too late if anything else in the process touches asyncio first).

Only applies on win32 — Linux/Mac workers (e.g. in Docker/prod) use
the default policy untouched, since this issue is Windows-only.
"""
import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from celery import Celery
from app.core.config import settings
from app.core.logging_config import configure_json_logging

configure_json_logging(service_name=settings.WORKER_SERVICE_NAME)

celery_app = Celery(
    "rag_workers",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.workers.tasks"],
)

# Registers worker_process_init / task_prerun / task_postrun / task_failure
# signal handlers (§6.2: judge queue depth, evaluation latency, structured
# JSON logging). Must be imported — not just defined — for Celery's signal
# dispatch to pick the handlers up.
import app.workers.observability  # noqa: E402,F401

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "app.workers.tasks.process_document": {"queue": "ingestion"},
        "app.workers.tasks.process_web_crawl": {"queue": "ingestion"},
        "app.workers.tasks.run_entity_extraction": {"queue": "extraction"},
        "app.workers.tasks.run_judge_evaluation": {"queue": "evaluation"},
        "app.workers.tasks.run_nightly_regression": {"queue": "evaluation"},
    },
    beat_schedule={
        # Nightly regression against golden dataset (§4.5)
        "nightly-regression": {
            "task": "app.workers.tasks.run_nightly_regression",
            "schedule": 86400.0,  # every 24 hours
        },
    },
)