"""Kafka broker port implementation (SAD deviation table: used only when BROKER=kafka).
Requires the optional `[kafka]` dependency group (`confluent-kafka`); imported lazily so the
base install never needs the wheel."""

from __future__ import annotations

import json
import logging
import threading

from libs.domain.contracts.events import EventEnvelope
from libs.domain.ports.event_broker import EventHandler

logger = logging.getLogger(__name__)


class KafkaBroker:
    def __init__(self, bootstrap_servers: str) -> None:
        try:
            import confluent_kafka  # noqa: F401
        except ImportError as exc:  # pragma: no cover - exercised only with [kafka] extra
            raise RuntimeError(
                "confluent-kafka is not installed; install the '[kafka]' extra or set BROKER=inprocess"
            ) from exc

        self._bootstrap_servers = bootstrap_servers
        self._producer = None
        self._consumers: list[tuple[str, str, EventHandler]] = []
        self._threads: list[threading.Thread] = []
        self._running = False

    def _get_producer(self):
        from confluent_kafka import Producer

        if self._producer is None:
            self._producer = Producer({"bootstrap.servers": self._bootstrap_servers})
        return self._producer

    def produce(self, topic: str, key: str, envelope: EventEnvelope) -> None:
        producer = self._get_producer()
        producer.produce(topic, key=key.encode("utf-8"), value=envelope.model_dump_json().encode("utf-8"))
        producer.poll(0)

    def subscribe(self, topic: str, group: str, handler: EventHandler) -> None:
        self._consumers.append((topic, group, handler))

    def start(self) -> None:
        from confluent_kafka import Consumer

        self._running = True
        for topic, group, handler in self._consumers:
            consumer = Consumer(
                {
                    "bootstrap.servers": self._bootstrap_servers,
                    "group.id": group,
                    "auto.offset.reset": "earliest",
                    "enable.auto.commit": False,
                }
            )
            consumer.subscribe([topic])
            t = threading.Thread(
                target=self._consume_loop, args=(consumer, handler, topic, group), daemon=True
            )
            self._threads.append(t)
            t.start()

    def _consume_loop(self, consumer, handler: EventHandler, topic: str, group: str) -> None:
        while self._running:
            msg = consumer.poll(timeout=0.5)
            if msg is None or msg.error():
                continue
            try:
                envelope = EventEnvelope.model_validate(json.loads(msg.value()))
                handler(envelope)
                # Commit only after the handler returns successfully (SAD §6.4).
                consumer.commit(msg, asynchronous=False)
            except Exception:
                logger.exception("kafka handler failed topic=%s group=%s", topic, group)

    def stop(self) -> None:
        self._running = False
        for t in self._threads:
            t.join(timeout=5)
        if self._producer is not None:
            self._producer.flush(5)
