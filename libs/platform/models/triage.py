"""Adapters implementing `TriageModelPort`.

Two real implementations and one stub:

*   `LlmTriageModel` calls the teacher LLM through Ollama. Accurate and explains itself, but
    costs seconds per ticket on CPU, so it suits offline labelling and low-volume deployments.
*   `DistilledTriageModel` runs the DistilBERT student trained on that teacher's labels. Answers
    in milliseconds, needs no model server, and is the intended production path.
*   `StubTriageModel` returns a fixed judgement for CI.

Both real adapters degrade to a rule-based judgement rather than raising, because a triage
failure must never strand a ticket: the SRS requires it to reach the agent flagged, not to
disappear.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from libs.domain.enums import Department, PriorityBand, Sentiment
from libs.domain.ports.triage_model import TriageJudgement
from libs.observability.logging import get_logger

logger = get_logger(__name__)

_BAND_FOR_SCORE = ((80, PriorityBand.critical), (60, PriorityBand.high), (35, PriorityBand.normal))


def _band_from_score(score: int) -> PriorityBand:
    for threshold, band in _BAND_FOR_SCORE:
        if score >= threshold:
            return band
    return PriorityBand.low


def _coerce_department(value: str | None) -> Department:
    try:
        return Department(value)
    except (ValueError, TypeError):
        return Department.general


def _coerce_band(value: str | None, score: int) -> PriorityBand:
    try:
        return PriorityBand(value)
    except (ValueError, TypeError):
        return _band_from_score(score)


def _coerce_sentiment(value: str | None) -> Sentiment:
    try:
        return Sentiment(value)
    except (ValueError, TypeError):
        return Sentiment.neutral


def _extract_json(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None


def _rule_fallback(fused_text: str, reason: str) -> TriageJudgement:
    """Keyword triage, used when a model is unavailable or returns something unusable."""
    lowered = fused_text.lower()
    table = [
        (Department.network_operations, ("outage", "no internet", "down", "line sync", "dsl", "area", "slow")),
        (Department.field_service, ("technician", "engineer", "site visit", "cable", "installation", "drop wire")),
        (Department.billing, ("bill", "charge", "invoice", "refund", "payment", "overcharge")),
        (Department.retention, ("cancel", "terminate", "leave", "switch provider")),
        (Department.technical_support, ("router", "wifi", "password", "reset", "light", "led", "modem")),
        (Department.sales, ("upgrade", "new plan", "package", "subscribe")),
    ]
    department = Department.general
    for candidate, keywords in table:
        if any(word in lowered for word in keywords):
            department = candidate
            break

    score = 20
    if any(word in lowered for word in ("urgent", "immediately", "business", "whole street", "no service")):
        score = 75

    return TriageJudgement(
        department=department,
        department_confidence=0.30,  # deliberately low: this is a guess, not a model output
        priority_band=_band_from_score(score),
        priority_score=score,
        sentiment=Sentiment.neutral,
        rationale=f"Rule-based fallback ({reason}). No model judgement was available.",
        model_version="rules",
    )


class LlmTriageModel:
    """Teacher path: a local instruction model reads the fused payload and returns JSON."""

    def __init__(self, base_url: str, model: str, prompt_path: Path, timeout: float = 60.0,
                 num_ctx: int = 4096) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._prompt = Path(prompt_path).read_text(encoding="utf-8")
        self._timeout = timeout
        self._num_ctx = num_ctx

    def triage(self, fused_text: str) -> TriageJudgement:
        import httpx

        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    f"{self._base_url}/api/chat",
                    json={
                        "model": self._model,
                        "messages": [
                            {"role": "system", "content": self._prompt},
                            {"role": "user", "content": fused_text},
                        ],
                        "stream": False,
                        "format": "json",
                        "options": {"temperature": 0.1, "num_ctx": self._num_ctx},
                    },
                )
                response.raise_for_status()
                label = _extract_json(response.json()["message"]["content"])
        except Exception as exc:  # noqa: BLE001 - any transport failure degrades, never raises
            logger.warning(f"LLM triage failed ({type(exc).__name__}); using rules",
                           extra={"stage": "triage"})
            return _rule_fallback(fused_text, f"{type(exc).__name__}")

        if label is None:
            return _rule_fallback(fused_text, "unparseable model output")

        score = int(label.get("priority_score", 20) or 20)
        score = max(0, min(100, score))
        return TriageJudgement(
            department=_coerce_department(label.get("department")),
            department_confidence=float(label.get("department_confidence", 0.5) or 0.5),
            priority_band=_coerce_band(label.get("priority_band"), score),
            priority_score=score,
            sentiment=_coerce_sentiment(label.get("sentiment")),
            intent=label.get("intent"),
            fault=label.get("fault"),
            urgency_signals=list(label.get("urgency_signals") or []),
            rationale=str(label.get("rationale", "")),
            model_version=self._model,
        )


class DistilledTriageModel:
    """Student path: the DistilBERT encoder trained on teacher labels.

    Loaded lazily so importing this module costs nothing when the student is not configured, and
    so a missing artefact degrades at first use rather than at start-up.
    """

    def __init__(self, artifact_dir: Path, device: str = "cpu") -> None:
        self._dir = Path(artifact_dir)
        self._device = device
        self._model = None
        self._tokenizer = None
        self._config: dict = {}
        self._failed = False

    def _load(self) -> bool:
        if self._model is not None:
            return True
        if self._failed:
            return False

        try:
            import torch
            from transformers import AutoTokenizer

            from mlops.train_distilled_triage import build_model

            self._config = json.loads((self._dir / "config.json").read_text(encoding="utf-8"))
            self._tokenizer = AutoTokenizer.from_pretrained(str(self._dir))
            model = build_model()
            model.load_state_dict(torch.load(self._dir / "model.pt", map_location=self._device))
            model.eval()
            self._model = model
            logger.info(f"distilled triage student loaded from {self._dir}", extra={"stage": "triage"})
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"distilled student unavailable ({type(exc).__name__}: {exc}); using rules",
                           extra={"stage": "triage"})
            self._failed = True
            return False

    def triage(self, fused_text: str) -> TriageJudgement:
        if not self._load():
            return _rule_fallback(fused_text, "student artefact unavailable")

        import torch

        departments = self._config.get("departments", [d.value for d in Department])
        bands = self._config.get("bands", [b.value for b in PriorityBand])
        sentiments = self._config.get("sentiments", [s.value for s in Sentiment])

        encoded = self._tokenizer(
            fused_text,
            truncation=True,
            max_length=self._config.get("max_length", 256),
            padding="max_length",
            return_tensors="pt",
        )

        with torch.no_grad():
            dept_logits, band_logits, sent_logits = self._model(
                encoded["input_ids"], encoded["attention_mask"]
            )

        dept_probs = torch.softmax(dept_logits, dim=1)[0]
        top = int(dept_probs.argmax())
        ranked = torch.argsort(dept_probs, descending=True)[1:3]

        band = bands[int(band_logits.argmax())]
        score = {"critical": 90, "high": 70, "normal": 45, "low": 20}.get(band, 20)

        return TriageJudgement(
            department=_coerce_department(departments[top]),
            department_confidence=float(dept_probs[top]),
            priority_band=_coerce_band(band, score),
            priority_score=score,
            sentiment=_coerce_sentiment(sentiments[int(sent_logits.argmax())]),
            alternatives=[(_coerce_department(departments[int(i)]), float(dept_probs[int(i)])) for i in ranked],
            # The student classifies; it cannot explain. Saying so is more useful than an empty
            # string the workspace would render as a blank rationale panel.
            rationale="Distilled classifier: no rationale is generated. "
                      f"Distilled from {self._config.get('teacher_model', 'the teacher LLM')}.",
            model_version=f"distilled-triage/{self._config.get('encoder', 'distilbert')}",
        )


class StubTriageModel:
    """Deterministic judgement for CI."""

    def triage(self, fused_text: str) -> TriageJudgement:
        return TriageJudgement(
            department=Department.technical_support,
            department_confidence=0.88,
            priority_band=PriorityBand.normal,
            priority_score=45,
            sentiment=Sentiment.frustrated,
            intent="report_fault",
            fault="fault_power_supply",
            urgency_signals=["stub signal"],
            rationale="Stub triage model.",
            model_version="stub",
        )
