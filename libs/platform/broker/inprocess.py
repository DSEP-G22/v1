"""In-process broker port implementation. Dict of topic -> list of (group, handler); one
queue.Queue per (topic, group) lane, worker threads, at-least-once redelivery on handler
exception up to max_retries, then a `tickets.dlq` event with the error context.

Per-ticket ordering is preserved by hashing the produce key onto one of N worker lanes per
(topic, group) so all events for the same ticket_id are handled by the same worker thread in
order.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field

from libs.domain.contracts.events import EventEnvelope, Topics
from libs.domain.ports.event_broker import EventHandler

logger = logging.getLogger(__name__)

_NUM_LANES = 4


@dataclass
class _Subscription:
    group: str
    handler: EventHandler
    lanes: list["queue.Queue[tuple[str, EventEnvelope, int]]"] = field(default_factory=list)
    threads: list[threading.Thread] = field(default_factory=list)


class InProcessBroker:
    def __init__(self, max_retries: int = 3, num_lanes: int = _NUM_LANES) -> None:
        self._max_retries = max_retries
        self._num_lanes = num_lanes
        self._subscriptions: dict[str, list[_Subscription]] = {}
        self._running = False

    def subscribe(self, topic: str, group: str, handler: EventHandler) -> None:
        sub = _Subscription(group=group, handler=handler)
        sub.lanes = [queue.Queue() for _ in range(self._num_lanes)]
        self._subscriptions.setdefault(topic, []).append(sub)

    def produce(self, topic: str, key: str, envelope: EventEnvelope) -> None:
        lane_index = hash(key) % self._num_lanes
        for sub in self._subscriptions.get(topic, []):
            sub.lanes[lane_index].put((key, envelope, 0))

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        for topic, subs in self._subscriptions.items():
            for sub in subs:
                for lane_index in range(self._num_lanes):
                    t = threading.Thread(
                        target=self._worker,
                        args=(topic, sub, lane_index),
                        daemon=True,
                        name=f"broker-{topic}-{sub.group}-{lane_index}",
                    )
                    sub.threads.append(t)
                    t.start()

    def stop(self) -> None:
        self._running = False
        for subs in self._subscriptions.values():
            for sub in subs:
                for lane in sub.lanes:
                    lane.put(None)  # type: ignore[arg-type]
                for t in sub.threads:
                    t.join(timeout=5)
                sub.threads.clear()

    def _worker(self, topic: str, sub: _Subscription, lane_index: int) -> None:
        lane = sub.lanes[lane_index]
        while self._running:
            try:
                item = lane.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is None:
                break
            key, envelope, attempt = item
            try:
                sub.handler(envelope)
            except Exception as exc:  # noqa: BLE001 - broker must not crash the worker
                logger.exception(
                    "handler failed topic=%s group=%s ticket_id=%s attempt=%d",
                    topic,
                    sub.group,
                    envelope.ticket_id,
                    attempt,
                )
                if attempt + 1 < self._max_retries:
                    time.sleep(min(2**attempt * 0.05, 1.0))
                    lane.put((key, envelope, attempt + 1))
                else:
                    self.produce(
                        Topics.TICKETS_DLQ,
                        key,
                        EventEnvelope(
                            event_id=f"dlq-{envelope.event_id}",
                            ticket_id=envelope.ticket_id,
                            stage=f"dlq:{topic}:{sub.group}",
                            body={
                                "error": str(exc),
                                "attempts": attempt + 1,
                                "original_topic": topic,
                                "original_group": sub.group,
                                "original_key": key,
                                "original_envelope": envelope.model_dump(mode="json"),
                            },
                        ),
                    )
