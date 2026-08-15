"""ClassifierPort implementations. Selection order at runtime (sklearn artifact if present ->
LLM -> rules) is decided in libs/platform/registry.py, not here."""

from __future__ import annotations

import json
from pathlib import Path

from libs.domain.enums import Department
from libs.domain.ports.text_generator import TextGeneratorPort

_KEYWORD_TABLE: dict[Department, list[str]] = {
    Department.network_operations: ["no internet", "no signal", "outage", "no dial tone", "router"],
    Department.billing: ["invoice", "overcharged", "refund", "payment", "billing"],
    Department.retention: ["cancel", "close my account", "switch provider"],
    Department.field_service: ["technician", "site visit", "installation"],
    Department.sales: ["upgrade my plan", "new connection", "pricing", "quote"],
    Department.technical_support: ["account", "subscription", "login", "password"],
}


class RuleOnlyClassifier:
    """Keyword-table fallback classifier, used when no sklearn artifact and no LLM are available."""

    def classify(self, text: str) -> tuple[Department, float, list[tuple[Department, float]]]:
        lowered = text.lower()
        scores: dict[Department, float] = {}
        for dept, keywords in _KEYWORD_TABLE.items():
            hits = sum(1 for kw in keywords if kw in lowered)
            if hits:
                scores[dept] = hits / len(keywords)

        if not scores:
            return Department.general, 0.3, []

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        top_dept, top_score = ranked[0]
        confidence = min(0.5 + top_score, 0.95)
        alternatives = [(d, s) for d, s in ranked[1:3]]
        return top_dept, confidence, alternatives


class SklearnClassifier:
    def __init__(self, artifact_path: Path) -> None:
        import joblib

        bundle = joblib.load(artifact_path)
        self._pipeline = bundle["pipeline"] if isinstance(bundle, dict) else bundle
        self._classes: list[str] = list(getattr(self._pipeline, "classes_", []))

    def classify(self, text: str) -> tuple[Department, float, list[tuple[Department, float]]]:
        proba = self._pipeline.predict_proba([text])[0]
        ranked = sorted(zip(self._classes, proba), key=lambda kv: kv[1], reverse=True)
        top_label, top_score = ranked[0]
        alternatives = [(Department(label), float(p)) for label, p in ranked[1:3]]
        return Department(top_label), float(top_score), alternatives


_CLASSIFY_PROMPT = """Classify the following customer support ticket into exactly one department.
Departments: technical_support, billing, network_operations, field_service, sales, retention, general.

Ticket:
{text}

Respond as JSON: {{"department": str, "confidence": float, "alternatives": [[str, float]]}}"""


class LlmClassifier:
    def __init__(self, generator: TextGeneratorPort) -> None:
        self._generator = generator

    def classify(self, text: str) -> tuple[Department, float, list[tuple[Department, float]]]:
        raw = self._generator.generate(_CLASSIFY_PROMPT.format(text=text), prompt_kind="classify")
        try:
            parsed = json.loads(raw)
            department = Department(parsed["department"])
            confidence = float(parsed["confidence"])
            alternatives = [(Department(d), float(p)) for d, p in parsed.get("alternatives", [])]
            return department, confidence, alternatives
        except (json.JSONDecodeError, KeyError, ValueError):
            return Department.general, 0.3, []
