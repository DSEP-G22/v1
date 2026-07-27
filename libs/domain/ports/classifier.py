from __future__ import annotations

from typing import Protocol

from libs.domain.enums import Department


class ClassifierPort(Protocol):
    def classify(self, text: str) -> tuple[Department, float, list[tuple[Department, float]]]: ...
