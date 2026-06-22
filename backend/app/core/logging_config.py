"""
backend/app/core/logging_config.py

Structured JSON logging (§6.2: "Structured JSON logs from all services").
Plain stdlib logging, no extra dependency — a custom Formatter that
serializes each LogRecord into a single JSON line, which is what log
aggregation tools (Loki/ELK/CloudWatch/etc.) expect for field-based
querying instead of regex-parsing free text.

Both the API process (main.py) and each Celery worker process
(celery_app.py) call configure_json_logging() once at startup, each
with their own service_name, so entries from rag-api vs.
rag-worker-ingestion vs. rag-worker-evaluation can be told apart once
aggregated.
"""
import json
import logging
import sys
from datetime import datetime, timezone

# Attributes every LogRecord carries by default — anything else found
# on a record (e.g. passed via logger.info(msg, extra={...})) is
# treated as a caller-supplied structured field and included as-is.
_STANDARD_LOGRECORD_ATTRS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName",
}


class _JsonFormatter(logging.Formatter):
    def __init__(self, service_name: str):
        super().__init__()
        self._service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "service": self._service_name,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key in payload or key in _STANDARD_LOGRECORD_ATTRS:
                continue
            payload[key] = value
        return json.dumps(payload, default=str)


def configure_json_logging(service_name: str, level: int = logging.INFO) -> None:
    """
    Replaces the root logger's handlers with a single stdout handler
    emitting JSON lines. Call once, at process startup, before any
    other logging happens.
    """
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(_JsonFormatter(service_name))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)