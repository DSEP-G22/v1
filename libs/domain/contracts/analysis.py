"""Analysis-stage contracts — SAD §5.2.1 Figure 4 (TriageResult through ActionRecommendation)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from libs.domain.enums import Department, PriorityBand, Sentiment


class UrgencySignal(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    weight: int
    matched: bool


class TriageResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticket_id: str
    department: Department
    department_confidence: float
    alternatives: list[Department] = Field(default_factory=list)
    sentiment: Sentiment
    signals: list[UrgencySignal] = Field(default_factory=list)
    priority_score: int
    band: PriorityBand

    def explain(self) -> str:
        matched = ", ".join(s.name for s in self.signals if s.matched)
        return f"score={self.priority_score} band={self.band.value} signals=[{matched}]"


class Citation(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: str
    chunk_version: int
    relevance: float
    verified: bool


class Diagnosis(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticket_id: str
    intent: str
    fault: str | None
    confidence: float
    alternatives: list[str] = Field(default_factory=list)
    rationale: str
    citations: list[Citation] = Field(default_factory=list)
    needs_human_diagnosis: bool = False


class PolicyFinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_id: str
    severity: str
    message: str
    span: tuple[int, int] | None = None


class DraftResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticket_id: str
    ai_text: str
    current_text: str
    revision: int = 1
    findings: list[PolicyFinding] = Field(default_factory=list)
    ai_generated: bool = True

    def diff(self) -> int:
        """Levenshtein edit distance between ai_text and current_text (agent-edit metric)."""
        a, b = self.ai_text, self.current_text
        if a == b:
            return 0
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, start=1):
            curr = [i] + [0] * len(b)
            for j, cb in enumerate(b, start=1):
                cost = 0 if ca == cb else 1
                curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
            prev = curr
        return prev[-1]


class RecommendationStatus:
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"


class ActionRecommendation(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticket_id: str
    action_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    requires_supervisor: bool = False
    status: str = RecommendationStatus.PROPOSED
