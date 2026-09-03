"""TextGeneratorPort implementations."""

from __future__ import annotations

import json
import random
import threading
import time
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

_PROMPT_DIR = Path(__file__).resolve().parents[3] / "models" / "prompts" / "llm"


# Characters a language model reaches for that the project's written style does not use. Model
# output is the one text path that cannot be cleaned at authoring time: a customer-facing reply is
# written at runtime, so the substitution has to happen here, on the way out of the adapter.
#
# Safe to apply to a JSON response, which matters because `generate_json` parses exactly this
# text. No replacement introduces a brace, bracket, colon or comma, so JSON structure cannot
# change. The quote substitutions only ever produce characters that a JSON encoder escapes inside
# string values anyway, so a string boundary cannot move. Verified by
# tests/unit/test_llm_punctuation.py, which round-trips a JSON payload through this function.
#
# It is also idempotent: no replacement produces a character that is itself a key here. An earlier
# em-dash script in this project was not, and re-running it rewrote its own output across the repo.
_PUNCTUATION_SUBSTITUTIONS = {
    "—": ", ",  # em dash
    "–": "-",   # en dash
    "‘": "'",   # left single quote
    "’": "'",   # right single quote
    "“": '"',   # left double quote
    "”": '"',   # right double quote
    "…": "...",  # ellipsis
    "‑": "-",  # non-breaking hyphen, emitted in words like "power-cycle"
    "‒": "-",  # figure dash
    "−": "-",  # minus sign
    " ": " ",   # non-breaking space
}


def _normalise_punctuation(text: str) -> str:
    """Replace typographic characters a model emits with their plain equivalents."""
    for source, replacement in _PUNCTUATION_SUBSTITUTIONS.items():
        text = text.replace(source, replacement)
    return text


class GenerationInvalid(RuntimeError):
    pass


def _extract_json(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise GenerationInvalid(f"no JSON object found in LLM response: {raw[:200]!r}")
    return json.loads(raw[start : end + 1])


class _CircuitBreaker:
    """Opens after `failure_threshold` consecutive failures; half-opens after `reset_after_s`."""

    def __init__(self, failure_threshold: int = 5, reset_after_s: float = 30.0) -> None:
        self._failure_threshold = failure_threshold
        self._reset_after_s = reset_after_s
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    def before_call(self) -> None:
        with self._lock:
            if self._opened_at is None:
                return
            if time.monotonic() - self._opened_at >= self._reset_after_s:
                return  # half-open: allow one trial call through
            raise RuntimeError("circuit breaker open: LLM adapter unavailable")

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._opened_at = time.monotonic()


class OllamaGenerator:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_s: float = 60.0,
        num_ctx: int = 8192,
        max_in_flight: int = 2,
        max_attempts: int = 3,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_s = timeout_s
        self._num_ctx = num_ctx
        self._max_attempts = max_attempts
        self._semaphore = threading.Semaphore(max_in_flight)
        self._breaker = _CircuitBreaker()

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        json_schema: type[BaseModel] | None = None,
        **opts: Any,
    ) -> str:
        self._breaker.before_call()

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "format": "json" if json_schema is not None else None,
            "options": {"temperature": opts.get("temperature", 0.2), "num_ctx": self._num_ctx},
        }

        last_exc: Exception | None = None
        with self._semaphore:
            for attempt in range(self._max_attempts):
                try:
                    resp = httpx.post(
                        f"{self._base_url}/api/chat", json=payload, timeout=self._timeout_s
                    )
                    resp.raise_for_status()
                    content = resp.json()["message"]["content"]
                    self._breaker.record_success()
                    return _normalise_punctuation(content)
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    self._breaker.record_failure()
                    if attempt + 1 < self._max_attempts:
                        backoff = min(2**attempt * 0.5, 8.0) + random.uniform(0, 0.25)
                        time.sleep(backoff)

        assert last_exc is not None
        raise last_exc

    def generate_json(
        self, prompt: str, schema: type[BaseModel], system: str | None = None, **opts: Any
    ) -> BaseModel:
        raw = self.generate(prompt, system=system, json_schema=schema, **opts)
        try:
            parsed = _extract_json(raw)
            return schema.model_validate(parsed)
        except Exception:
            repair_template = _PROMPT_DIR / "repair.txt"
            repair_prompt = (
                repair_template.read_text(encoding="utf-8").format(
                    schema=schema.model_json_schema(), broken_output=raw
                )
                if repair_template.exists()
                else f"The following output must be valid JSON matching this schema: "
                f"{schema.model_json_schema()}\n\nFix this output and return only JSON:\n{raw}"
            )
            repaired_raw = self.generate(repair_prompt, json_schema=schema)
            try:
                parsed = _extract_json(repaired_raw)
                return schema.model_validate(parsed)
            except Exception as exc:
                raise GenerationInvalid(f"LLM output invalid even after repair: {exc}") from exc


class StubGenerator:
    """Deterministic JSON for CI, but it never invents facts that were not supplied in the
    prompt. The stub exists for execution-path coverage, not for customer-facing claims."""

    _CANNED: dict[str, dict[str, Any]] = {
        "diagnosis": {
            "intent": "needs_review",
            "fault": "unknown",
            "confidence": 0.0,
            "alternatives": [],
            "rationale": "Stub mode: no real model output was produced, so the claim is intentionally left neutral.",
            "citations": [],
        },
        "draft": {
            "ai_text": "Thanks for reaching out. We are reviewing the reported issue and will follow up with the next steps.",
        },
        "classify": {
            "department": "general",
            "confidence": 0.0,
            "alternatives": [],
        },
    }

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        json_schema: type[BaseModel] | None = None,
        **opts: Any,
    ) -> str:
        kind = opts.get("prompt_kind", self._guess_kind(prompt))
        return json.dumps(self._CANNED.get(kind, {"text": "stub response"}))

    def generate_json(self, prompt: str, schema: type[BaseModel], system: str | None = None, **opts: Any) -> BaseModel:
        raw = self.generate(prompt, system=system, json_schema=schema, **opts)
        return schema.model_validate(json.loads(raw))

    @staticmethod
    def _guess_kind(prompt: str) -> str:
        lowered = prompt.lower()
        if "diagnos" in lowered or "fault" in lowered:
            return "diagnosis"
        if "draft" in lowered or "reply" in lowered:
            return "draft"
        if "classify" in lowered or "department" in lowered:
            return "classify"
        return "generic"
