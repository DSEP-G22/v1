"""Priority scoring — pure function over triage inputs. Weights are passed in, never read from
config inside the domain (ADR-010: only the weights are data, the policy stays code)."""

from __future__ import annotations

from typing import TypedDict

from libs.domain.contracts.analysis import UrgencySignal
from libs.domain.enums import PriorityBand

DEFAULT_WEIGHTS: dict[str, int] = {
    "sentiment": 25,
    "urgency_keywords": 20,
    "customer_segment": 15,
    "outage_scope": 20,
    "prior_contacts": 10,
    "sla_age": 10,
}


class TriageInputs(TypedDict, total=False):
    sentiment_score: float  # 0..1, higher = angrier
    urgency_keyword_hit: bool
    customer_segment_score: float  # 0..1, higher = higher-value segment
    outage_scope_score: float  # 0..1, higher = wider-scope outage
    prior_contacts_score: float  # 0..1, higher = more repeat contacts
    sla_age_score: float  # 0..1, higher = closer to/over SLA breach


def _band(score: int) -> PriorityBand:
    if score >= 80:
        return PriorityBand.critical
    if score >= 60:
        return PriorityBand.high
    if score >= 35:
        return PriorityBand.normal
    return PriorityBand.low


def score(
    triage_inputs: TriageInputs, weights: dict[str, int] = DEFAULT_WEIGHTS
) -> tuple[int, PriorityBand, list[UrgencySignal]]:
    signals: list[UrgencySignal] = []
    total = 0.0

    sentiment_val = triage_inputs.get("sentiment_score", 0.0)
    total += weights["sentiment"] * sentiment_val
    signals.append(
        UrgencySignal(name="sentiment", weight=weights["sentiment"], matched=sentiment_val > 0)
    )

    urgency_hit = bool(triage_inputs.get("urgency_keyword_hit", False))
    total += weights["urgency_keywords"] * (1.0 if urgency_hit else 0.0)
    signals.append(
        UrgencySignal(name="urgency_keywords", weight=weights["urgency_keywords"], matched=urgency_hit)
    )

    segment_val = triage_inputs.get("customer_segment_score", 0.0)
    total += weights["customer_segment"] * segment_val
    signals.append(
        UrgencySignal(
            name="customer_segment", weight=weights["customer_segment"], matched=segment_val > 0
        )
    )

    outage_val = triage_inputs.get("outage_scope_score", 0.0)
    total += weights["outage_scope"] * outage_val
    signals.append(
        UrgencySignal(name="outage_scope", weight=weights["outage_scope"], matched=outage_val > 0)
    )

    contacts_val = triage_inputs.get("prior_contacts_score", 0.0)
    total += weights["prior_contacts"] * contacts_val
    signals.append(
        UrgencySignal(
            name="prior_contacts", weight=weights["prior_contacts"], matched=contacts_val > 0
        )
    )

    sla_val = triage_inputs.get("sla_age_score", 0.0)
    total += weights["sla_age"] * sla_val
    signals.append(UrgencySignal(name="sla_age", weight=weights["sla_age"], matched=sla_val > 0))

    clamped = max(0, min(100, round(total)))
    return clamped, _band(clamped), signals
