from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel


class TextGeneratorPort(Protocol):
    def generate(
        self,
        prompt: str,
        system: str | None = None,
        json_schema: type[BaseModel] | None = None,
        **opts: Any,
    ) -> str: ...
