from __future__ import annotations

from typing import Callable, Protocol

from libs.domain.contracts.events import EventEnvelope

EventHandler = Callable[[EventEnvelope], None]


class EventBrokerPort(Protocol):
    def produce(self, topic: str, key: str, envelope: EventEnvelope) -> None: ...

    def subscribe(self, topic: str, group: str, handler: EventHandler) -> None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...
