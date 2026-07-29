from __future__ import annotations

from libs.domain.ports.event_broker import EventBrokerPort
from libs.platform.config import Settings


def build_broker(settings: Settings) -> EventBrokerPort:
    if settings.broker == "kafka":
        from libs.platform.broker.kafka import KafkaBroker

        return KafkaBroker(bootstrap_servers=settings.kafka_bootstrap)

    from libs.platform.broker.inprocess import InProcessBroker

    return InProcessBroker(max_retries=settings.max_retries)
