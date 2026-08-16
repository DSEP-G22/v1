"""VisualExtractorPort implementations."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx

from libs.domain.contracts.media import ExtractedFields, LedState, VisualSummary

_PROMPT_DIR = Path(__file__).resolve().parents[3] / "models" / "prompts" / "vlm"


def choose_template(filename: str, hint: str | None = None) -> str:
    if hint in ("router_led_panel", "speed_test", "error_screen", "generic"):
        return hint
    lowered = filename.lower()
    if "router" in lowered or "led" in lowered or "modem" in lowered:
        return "router_led_panel"
    if "speed" in lowered or "test" in lowered:
        return "speed_test"
    if "error" in lowered or "screen" in lowered:
        return "error_screen"
    return "generic"


def _extract_json(raw: str) -> dict:
    """Ollama sometimes returns prose around the JSON even with format=json on small quantised
    models. Find the outermost {...} before parsing."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"no JSON object found in VLM response: {raw[:200]!r}")
    return json.loads(raw[start : end + 1])


class StubExtractor:
    def __init__(self, model_version: str = "stub-vlm-1.0", low_confidence_threshold: float = 0.55) -> None:
        self._model_version = model_version
        self._threshold = low_confidence_threshold

    def extract(self, image_path: Path, attachment_id: str, template: str) -> VisualSummary:
        fields = ExtractedFields(
            device_model="Generic Router X1",
            led_states=[LedState(label="power", colour="red", behaviour="solid")],
            error_codes=[],
            numeric_values={},
        )
        confidence = 0.88
        return VisualSummary(
            attachment_id=attachment_id,
            prompt_template=template,
            summary_text="Stub summary: router power LED is solid red; internet LED is off.",
            extracted_fields=fields,
            confidence=confidence,
            low_confidence=confidence < self._threshold,
            model_version=self._model_version,
        )


class HeuristicLedExtractor:
    """HSV-mask based LED colour/position detector, port of the prototype's
    `image_ingest._run_vlm`. Kept as the offline fallback when Ollama vision is unavailable."""

    def __init__(self, low_confidence_threshold: float = 0.55) -> None:
        self._threshold = low_confidence_threshold
        self._model_version = "heuristic-led-1.0"

    def extract(self, image_path: Path, attachment_id: str, template: str) -> VisualSummary:
        from PIL import Image
        import numpy as np

        img = Image.open(image_path).convert("RGB")
        arr = np.asarray(img).astype("float32") / 255.0
        hsv = _rgb_to_hsv(arr)

        led_states = _detect_led_blobs(hsv)
        confidence = 0.75 if led_states else 0.35

        summary_parts = [f"{led.colour} {led.behaviour} LED at {led.label}" for led in led_states]
        summary_text = "Detected: " + "; ".join(summary_parts) if summary_parts else "No LED blobs detected."

        return VisualSummary(
            attachment_id=attachment_id,
            prompt_template=template,
            summary_text=summary_text,
            extracted_fields=ExtractedFields(led_states=led_states),
            confidence=confidence,
            low_confidence=confidence < self._threshold,
            model_version=self._model_version,
        )


def _rgb_to_hsv(arr):
    import numpy as np

    maxc = np.max(arr, axis=-1)
    minc = np.min(arr, axis=-1)
    v = maxc
    delta = maxc - minc
    s = np.where(maxc == 0, 0, delta / np.where(maxc == 0, 1, maxc))
    return np.stack([np.zeros_like(v), s, v], axis=-1)


def _detect_led_blobs(hsv) -> list[LedState]:
    import numpy as np

    s, v = hsv[..., 1], hsv[..., 2]
    bright_saturated = (s > 0.5) & (v > 0.5)
    if not bright_saturated.any():
        return []

    ys, xs = np.nonzero(bright_saturated)
    if len(ys) == 0:
        return []

    rows = ys // max(hsv.shape[0] // 10, 1)
    positions = ["top", "middle", "bottom"]
    row_bucket = int(np.median(rows)) % len(positions)

    return [LedState(label=positions[row_bucket], colour="unknown", behaviour="solid")]


class OllamaVisionExtractor:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_s: float = 60.0,
        low_confidence_threshold: float = 0.55,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_s = timeout_s
        self._threshold = low_confidence_threshold

    def extract(self, image_path: Path, attachment_id: str, template: str) -> VisualSummary:
        prompt_path = _PROMPT_DIR / f"{template}.txt"
        prompt = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else (
            "Describe what you see in this image, focusing on LED indicator colours and states. "
            'Respond as JSON: {"summary_text": str, "device_model": str|null, '
            '"led_states": [{"label": str, "colour": str, "behaviour": str}], '
            '"error_codes": [str], "confidence": float}'
        )

        image_bytes = Path(image_path).read_bytes()
        # PNGs with an alpha channel must be flattened to RGB, and the base64 payload must NOT
        # carry a `data:` prefix, or Ollama returns 400 "invalid image".
        image_bytes = _ensure_rgb_png_bytes(image_bytes)
        b64 = base64.b64encode(image_bytes).decode("ascii")

        resp = httpx.post(
            f"{self._base_url}/api/generate",
            json={"model": self._model, "prompt": prompt, "images": [b64], "format": "json", "stream": False},
            timeout=self._timeout_s,
        )
        resp.raise_for_status()
        raw_response = resp.json().get("response", "{}")
        parsed = _extract_json(raw_response)

        led_states = [
            LedState(
                label=led.get("label", "unknown"),
                colour=led.get("colour", "unknown"),
                behaviour=led.get("behaviour", "unknown"),
            )
            for led in parsed.get("led_states", [])
        ]
        confidence = float(parsed.get("confidence", 0.5))

        return VisualSummary(
            attachment_id=attachment_id,
            prompt_template=template,
            summary_text=parsed.get("summary_text", ""),
            extracted_fields=ExtractedFields(
                device_model=parsed.get("device_model"),
                led_states=led_states,
                error_codes=parsed.get("error_codes", []),
                numeric_values=parsed.get("numeric_values", {}),
            ),
            confidence=confidence,
            low_confidence=confidence < self._threshold,
            model_version=self._model,
        )


def _ensure_rgb_png_bytes(data: bytes) -> bytes:
    import io

    from PIL import Image

    img = Image.open(io.BytesIO(data))
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    return data
