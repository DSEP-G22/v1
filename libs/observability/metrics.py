"""In-process counters/histograms with an optional Prometheus exporter."""

from __future__ import annotations

import functools
import threading
import time
from collections import defaultdict
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, float] = defaultdict(float)
        self._histograms: dict[str, list[float]] = defaultdict(list)

    def increment(self, name: str, value: float = 1.0, **labels: str) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] += value

    def observe(self, name: str, value: float, **labels: str) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._histograms[key].append(value)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "counters": dict(self._counters),
                "histograms": {k: list(v) for k, v in self._histograms.items()},
            }

    @staticmethod
    def _key(name: str, labels: dict[str, str]) -> str:
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def to_prometheus_text(self) -> str:
        lines: list[str] = []
        with self._lock:
            for key, value in self._counters.items():
                lines.append(f"{key} {value}")
            for key, values in self._histograms.items():
                if not values:
                    continue
                lines.append(f"{key}_count {len(values)}")
                lines.append(f"{key}_sum {sum(values)}")
        return "\n".join(lines)


_REGISTRY = MetricsRegistry()


def get_registry() -> MetricsRegistry:
    return _REGISTRY


def timed(stage: str) -> Callable[[F], F]:
    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                _REGISTRY.observe(f"{stage}_duration_ms", duration_ms)

        return wrapper  # type: ignore[return-value]

    return decorator
