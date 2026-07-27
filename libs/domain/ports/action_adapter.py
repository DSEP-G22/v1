from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from libs.domain.enums import ExecutionStatus


class ExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: ExecutionStatus
    external_ref: str | None = None
    detail: str | None = None


class ActionAdapterPort(Protocol):
    def execute(self, action_id: str, params: dict[str, Any], idempotency_key: str) -> ExecutionResult: ...
