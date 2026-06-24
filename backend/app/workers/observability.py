"""
backend/app/workers/observability.py

Wires Celery worker signals into Prometheus metrics (§6.2 — judge
evaluation latency, judge LLM queue depth, plus the same for
ingestion/extraction tasks). Must be imported (not just defined) by
celery_app.py so Celery's signal dispatch actually picks up the
@signal.connect handlers below — importing it for side effects is the
whole point.

Worker topology (see infrastructure/docker/docker-compose.yml):
  - `worker`            -Q ingestion,extraction,celery  (port 9090 -> host 9101)
  - `evaluation-worker`  -Q evaluation                    (port 9090 -> host 9102)
Both run with `-P solo --concurrency=1`, i.e. exactly one process per
service — no Celery prefork children, so a single plain
prometheus_client HTTP server per process is correct; there's no need
for prometheus_client's multiprocess mode here.
"""
import logging
import threading
import time

from celery.signals import task_failure, task_postrun, task_prerun, worker_ready

from app.core.config import settings
from app.core.metrics import (
    CELERY_QUEUE_DEPTH,
    CELERY_TASK_DURATION_SECONDS,
    CELERY_TASK_FAILURES_TOTAL,
)

logger = logging.getLogger(__name__)

# Every queue declared in celery_app.py's task_routes, plus the
# default "celery" queue. Polled even if a given worker process isn't
# consuming from all of them — depth on a queue this process doesn't
# touch is still useful signal (e.g. the API-facing worker can see
# the evaluation queue backing up).
_MONITORED_QUEUES = ("ingestion", "extraction", "evaluation", "celery")
_QUEUE_POLL_INTERVAL_SECONDS = 5

_task_start_times: dict[str, float] = {}


@worker_ready.connect
def _on_worker_ready(**kwargs) -> None:
    """
    Fires exactly once when the worker has finished starting up, in
    the main process, regardless of pool type (unlike
    worker_process_init, which is prefork-specific and may not fire
    under the solo pool these workers use).
    """
    _start_metrics_server()
    _start_queue_depth_poller()


def _start_metrics_server() -> None:
    from prometheus_client import start_http_server

    port = settings.PROMETHEUS_WORKER_METRICS_PORT
    try:
        start_http_server(port)
        logger.info("worker metrics server listening on :%s", port)
    except OSError as exc:
        # Already bound — e.g. a dev reload triggering worker_ready twice.
        # Not fatal; the existing server keeps serving fine.
        logger.warning("worker metrics server not started on :%s: %s", port, exc)


def _start_queue_depth_poller() -> None:
    """
    task_prerun/task_postrun only fire once a worker has already
    claimed a message off the queue — they can never reveal how many
    messages are still *waiting*. Direct LLEN against the Redis broker
    is the only way to see true queue depth, so this polls it on a
    background thread rather than trying to derive it from task
    signals.
    """
    try:
        import redis

        client = redis.from_url(settings.CELERY_BROKER_URL)
        client.ping()
    except Exception as exc:
        logger.warning("queue depth poller disabled, broker unreachable: %s", exc)
        return

    def _poll() -> None:
        while True:
            for queue in _MONITORED_QUEUES:
                try:
                    CELERY_QUEUE_DEPTH.labels(queue=queue).set(client.llen(queue))
                except Exception as exc:
                    logger.debug("queue depth poll failed for %s: %s", queue, exc)
            time.sleep(_QUEUE_POLL_INTERVAL_SECONDS)

    threading.Thread(target=_poll, daemon=True, name="queue-depth-poller").start()


@task_prerun.connect
def _record_task_start(task_id=None, **kwargs) -> None:
    _task_start_times[task_id] = time.perf_counter()


@task_postrun.connect
def _record_task_duration(task_id=None, task=None, **kwargs) -> None:
    start = _task_start_times.pop(task_id, None)
    if start is None:
        return
    task_name = getattr(task, "name", "unknown")
    CELERY_TASK_DURATION_SECONDS.labels(task_name=task_name).observe(time.perf_counter() - start)


@task_failure.connect
def _record_task_failure(task_id=None, sender=None, **kwargs) -> None:
    # task_failure doesn't carry a separate "task" kwarg — sender IS
    # the task object that raised. Still pop the start time so it
    # doesn't leak (postrun won't fire for a task that failed before
    # reaching it in some failure modes).
    _task_start_times.pop(task_id, None)
    task_name = getattr(sender, "name", "unknown")
    CELERY_TASK_FAILURES_TOTAL.labels(task_name=task_name).inc()