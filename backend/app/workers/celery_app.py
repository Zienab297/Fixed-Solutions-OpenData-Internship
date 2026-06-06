"""
Celery application configuration.
Three queues: ingestion, evaluation, extraction.
"""
from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "rag_workers",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.workers.tasks"],
)

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
