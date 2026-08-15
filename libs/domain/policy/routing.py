"""Department routing, first matching rule wins, else the classifier's department."""

from __future__ import annotations

from typing import Any, TypedDict

from libs.domain.enums import Department


class RoutingInput(TypedDict):
    text: str
    classifier_department: Department


def _rule_matches(rule: dict[str, Any], routing_input: RoutingInput) -> bool:
    when = rule.get("when", {})
    text_lower = routing_input["text"].lower()

    keywords_any = when.get("keywords_any")
    if keywords_any is not None:
        if not any(kw.lower() in text_lower for kw in keywords_any):
            return False

    return True


def evaluate(rules: list[dict[str, Any]], routing_input: RoutingInput) -> Department:
    for rule in rules:
        if _rule_matches(rule, routing_input):
            return Department(rule["department"])
    return routing_input["classifier_department"]
