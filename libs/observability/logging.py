"""JSON structured logging with ticket_id / stage / duration_ms / model_version fields."""

from __future__ import annotations

import json
import logging
import sys
import time
from contextlib import contextmanager
from typing import Any, Iterator


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
        }
        for key in ("ticket_id", "stage", "duration_ms", "model_version"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


@contextmanager
def log_stage(logger: logging.Logger, stage: str, ticket_id: str, model_version: str | None = None) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "stage complete",
            extra={"ticket_id": ticket_id, "stage": stage, "duration_ms": round(duration_ms, 2), "model_version": model_version},
        )
