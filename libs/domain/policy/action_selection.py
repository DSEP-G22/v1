"""Action recommendation selection against the action registry (SAD Figure 4:
`ActionRegistryEntry.permits(params)`)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from libs.domain.contracts.analysis import ActionRecommendation


class ActionRegistryEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_id: str
    mapped_faults: list[str] = Field(default_factory=list)
    requires_supervisor: bool = False
    enabled: bool = True
    requires_fields: list[str] = Field(default_factory=list)
    impact_limits: dict[str, float] = Field(default_factory=dict)

    def permits(self, params: dict[str, Any]) -> bool:
        if not self.enabled:
            return False
        if any(field not in params for field in self.requires_fields):
            return False
        for limit_key, limit_value in self.impact_limits.items():
            # limit_key names a params field whose numeric value must not exceed the limit.
            field_name = limit_key.removeprefix("max_")
            if field_name in params and params[field_name] > limit_value:
                return False
        return True


def select(
    fault: str, registry_entries: list[ActionRegistryEntry], params: dict[str, Any]
) -> ActionRecommendation | None:
    for entry in registry_entries:
        if fault not in entry.mapped_faults:
            continue
        if not entry.permits(params):
            continue
        return ActionRecommendation(
            ticket_id=str(params.get("ticket_id", "")),
            action_id=entry.action_id,
            parameters=params,
            requires_supervisor=entry.requires_supervisor,
        )
    return None
