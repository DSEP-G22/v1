"""Port for a model that triages a whole unified payload in one pass.

`ClassifierPort` returns a department and nothing else, which suited a TF-IDF classifier trained
on text alone. A triage LLM, and the student distilled from it, read the fused multimodal payload
and produce the department, the priority band, the sentiment and a rationale together, because
those judgements come from the same evidence and separating them into four models would mean
four passes over the same text.

This port exists alongside `ClassifierPort` rather than replacing it. `triage_svc` prefers a
`TriageModelPort` when one is configured and falls back to the classifier otherwise, so the
rule-based and scikit-learn paths keep working and the degradation tests keep passing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from libs.domain.enums import Department, PriorityBand, Sentiment


@dataclass(frozen=True)
class TriageJudgement:
    """One model's complete triage of a payload.

    `rationale` and `urgency_signals` are shown to the agent in the workspace, so a judgement is
    reviewable rather than an unexplained label. A distilled encoder cannot generate prose and
    leaves them empty; that absence is itself informative, and the workspace renders it as such.
    """

    department: Department
    department_confidence: float
    priority_band: PriorityBand
    priority_score: int
    sentiment: Sentiment
    intent: str | None = None
    fault: str | None = None
    urgency_signals: list[str] = field(default_factory=list)
    rationale: str = ""
    alternatives: list[tuple[Department, float]] = field(default_factory=list)
    model_version: str = "unknown"


class TriageModelPort(Protocol):
    def triage(self, fused_text: str) -> TriageJudgement: ...
