"""Metric functions for the evaluation harness: department accuracy/macro-F1, priority band
kappa, fault top-k, citation verification rate, draft edit distance, JSON validity, and
per-stage p50/p95 latency (derived from `ticket_state_transition`, which every ticket already
gets for free from `TicketRepo.update_state` — no extra instrumentation needed)."""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, field

from sklearn.metrics import cohen_kappa_score, f1_score


def department_accuracy(y_true: list[str], y_pred: list[str]) -> float:
    if not y_true:
        return float("nan")
    return sum(t == p for t, p in zip(y_true, y_pred)) / len(y_true)


def department_macro_f1(y_true: list[str], y_pred: list[str]) -> float:
    if not y_true:
        return float("nan")
    return float(f1_score(y_true, y_pred, average="macro", zero_division=0))


def priority_band_kappa(y_true: list[str], y_pred: list[str]) -> float:
    if len(set(y_true)) < 2 and len(set(y_pred)) < 2:
        return 1.0 if y_true == y_pred else 0.0
    return float(cohen_kappa_score(y_true, y_pred))


def fault_topk_accuracy(pairs: list[tuple[str | None, list[str]]], k: int = 1) -> float:
    """pairs: list of (expected_fault, [predicted_fault] + alternatives), ranked best-first."""
    scored = [p for p in pairs if p[0] is not None]
    if not scored:
        return float("nan")
    hits = sum(1 for expected, predicted in scored if expected in predicted[:k])
    return hits / len(scored)


def citation_verification_rate(citation_lists: list[list[bool]]) -> float:
    """citation_lists: one list of `verified` booleans per diagnosis that had >=1 citation."""
    nonempty = [c for c in citation_lists if c]
    if not nonempty:
        return float("nan")
    all_flags = [v for c in nonempty for v in c]
    return sum(all_flags) / len(all_flags)


def mean_draft_edit_distance(distances: list[int]) -> float:
    if not distances:
        return float("nan")
    return statistics.mean(distances)


def json_validity_rate(successes: list[bool]) -> float:
    if not successes:
        return float("nan")
    return sum(successes) / len(successes)


@dataclass
class StageLatencies:
    per_stage_ms: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    def add_transitions(self, transitions: list[tuple[str, str, "object"]]) -> None:
        """transitions: chronologically ordered (from_state, to_state, at) for one ticket."""
        ordered = sorted(transitions, key=lambda t: t[2])
        for (from_state, to_state, at), (_, _, prev_at) in zip(ordered[1:], ordered[:-1]):
            stage_name = f"{from_state}->{to_state}"
            duration_ms = (at - prev_at).total_seconds() * 1000
            self.per_stage_ms[stage_name].append(duration_ms)

    def summary(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for stage, values in self.per_stage_ms.items():
            if not values:
                continue
            values_sorted = sorted(values)
            out[stage] = {
                "n": len(values),
                "p50_ms": _percentile(values_sorted, 50),
                "p95_ms": _percentile(values_sorted, 95),
                "mean_ms": statistics.mean(values),
            }
        return out


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return float("nan")
    k = (len(sorted_values) - 1) * (pct / 100)
    f, c = int(k), min(int(k) + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)
