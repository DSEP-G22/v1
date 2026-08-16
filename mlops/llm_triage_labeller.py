"""Label unified payloads with a teacher LLM, producing the distillation dataset.

This is the teacher half of knowledge distillation. A local Llama 3.1 8B reads each unified
payload and emits a structured triage judgement; a small student model is then trained to
reproduce those judgements without needing an 8B model at inference time (see
`mlops/train_distilled_triage.py`).

Why distil at all, rather than serving the teacher directly: the SRS budget allows a few seconds
per ticket for the whole pipeline, and an 8B model on CPU spends 1-3 seconds on triage alone.
A distilled encoder answers in milliseconds, runs without a GPU or a model server, and degrades
to rules if it fails to load. The teacher's reasoning is retained in the dataset rather than in
the deployed artefact.

The labeller is resumable. Every completed row is appended immediately and previously labelled
ticket ids are skipped on restart, because a run over thousands of tickets will be interrupted.

    python -m mlops.llm_triage_labeller --limit 500
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PROMPT_PATH = REPO_ROOT / "models" / "prompts" / "llm" / "triage.txt"
INPUT = REPO_ROOT / "data" / "processed" / "unified_dataset.jsonl"
OUTPUT = REPO_ROOT / "data" / "processed" / "distillation_dataset.jsonl"

VALID_DEPARTMENTS = {
    "technical_support", "network_operations", "field_service",
    "billing", "retention", "sales", "general",
}
VALID_BANDS = {"critical", "high", "normal", "low"}
VALID_SENTIMENT = {"angry", "frustrated", "neutral", "satisfied"}


def extract_json(text: str) -> dict | None:
    """Pull the outermost JSON object out of a model response.

    Quantised models frequently wrap JSON in prose or a code fence even when asked not to, so
    parsing the raw response directly would discard usable labels.
    """
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
    return None


def validate(label: dict) -> tuple[bool, str]:
    """Reject a label rather than train a student on a malformed one.

    A teacher that hallucinates a department outside the taxonomy is worse than a missing label:
    the student would learn a class that the routing layer cannot act on.
    """
    if label.get("department") not in VALID_DEPARTMENTS:
        return False, f"bad department {label.get('department')!r}"
    if label.get("priority_band") not in VALID_BANDS:
        return False, f"bad priority_band {label.get('priority_band')!r}"
    if label.get("sentiment") not in VALID_SENTIMENT:
        return False, f"bad sentiment {label.get('sentiment')!r}"

    confidence = label.get("department_confidence")
    if not isinstance(confidence, (int, float)) or not 0.0 <= float(confidence) <= 1.0:
        return False, f"bad department_confidence {confidence!r}"

    score = label.get("priority_score")
    if not isinstance(score, (int, float)) or not 0 <= float(score) <= 100:
        return False, f"bad priority_score {score!r}"

    return True, ""


def call_teacher(base_url: str, model: str, prompt: str, fused_text: str, timeout: float) -> tuple[dict | None, float, str]:
    """One teacher call. Returns (label, latency_seconds, raw_response)."""
    import httpx

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": fused_text},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1, "num_ctx": 4096},
    }

    started = time.time()
    with httpx.Client(timeout=timeout) as client:
        response = client.post(f"{base_url}/api/chat", json=payload)
        response.raise_for_status()
        content = response.json()["message"]["content"]

    return extract_json(content), time.time() - started, content


def main() -> int:
    parser = argparse.ArgumentParser(description="Label unified payloads with a teacher LLM")
    parser.add_argument("--input", default=str(INPUT))
    parser.add_argument("--output", default=str(OUTPUT))
    # Ollama cloud model by default. The local 8B is a drop-in alternative
    # (`--model llama3.1:8b-instruct-q4_K_M`) but has to be pulled first, and the pull failed
    # repeatedly on this connection. A cloud model needs no download and runs on the same
    # /api/chat endpoint, so nothing else in this script changes.
    parser.add_argument("--model", default="gpt-oss:120b-cloud")
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument("--limit", type=int, default=None, help="rows to label this run")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--restart", action="store_true", help="ignore existing output and relabel")
    parser.add_argument("--workers", type=int, default=4,
                        help="concurrent teacher calls; above 4 the cloud endpoint starts refusing")
    args = parser.parse_args()

    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    rows = [json.loads(line) for line in Path(args.input).read_text(encoding="utf-8").splitlines() if line.strip()]

    output_path = Path(args.output)
    done: set[str] = set()
    if output_path.exists() and not args.restart:
        for line in output_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["ticket_id"])
        print(f"resuming: {len(done)} already labelled")

    pending = [r for r in rows if r["ticket_id"] not in done]
    if args.limit:
        pending = pending[: args.limit]

    print(f"labelling {len(pending)} of {len(rows)} payloads with {args.model}")
    if not pending:
        return 0

    # Warm the model once so the first measured latency is not the load time.
    try:
        call_teacher(args.base_url, args.model, "Reply with {}", "warmup", args.timeout)
        print("teacher warm")
    except Exception as exc:  # noqa: BLE001
        print(f"could not reach the teacher at {args.base_url}: {type(exc).__name__}: {exc}")
        print("start it with:  ollama serve   and   ollama pull " + args.model)
        return 1

    ok = failed = 0
    latencies: list[float] = []

    def label_one(row: dict) -> tuple[dict, dict | None, float, str]:
        """Run one teacher call. Returns (row, label_or_None, latency, failure_reason)."""
        try:
            label, latency, raw = call_teacher(
                args.base_url, args.model, prompt, row["fused_text"], args.timeout
            )
        except Exception as exc:  # noqa: BLE001
            return row, None, 0.0, f"call failed: {type(exc).__name__}"

        if label is None:
            return row, None, latency, f"unparseable: {raw[:70]!r}"

        valid, reason = validate(label)
        if not valid:
            return row, None, latency, f"rejected: {reason}"

        return row, label, latency, ""

    # The teacher is a network call, so the run is latency-bound rather than CPU-bound and
    # parallelises well: measured 4.5 s/row sequentially against 2.2 s/row at 4 workers.
    # Concurrency is capped low deliberately. At 8 workers the cloud endpoint started returning
    # failures for roughly a third of requests, so more workers meant fewer labels, not more.
    # Writes stay on this thread, so the append-and-flush-per-row property that makes the run
    # resumable is unchanged.
    completed = 0
    with output_path.open("a", encoding="utf-8") as fh:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for row, label, latency, reason in pool.map(label_one, pending):
                completed += 1
                if label is None:
                    print(f"  [{completed}/{len(pending)}] {row['ticket_id']} {reason}")
                    failed += 1
                    continue

                latencies.append(latency)
                record = {
                    "ticket_id": row["ticket_id"],
                    "fused_text": row["fused_text"],
                    "modalities": row["metadata"]["modalities"],
                    "is_multimodal": row["metadata"]["is_multimodal"],
                    "flags": row["flags"],
                    "teacher_model": args.model,
                    "teacher_latency_s": round(latency, 3),
                    "teacher_label": label,
                    "ground_truth": row.get("ground_truth", {}),
                }
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                fh.flush()  # a long run will be interrupted; never lose completed work
                ok += 1

                if completed % 25 == 0 or completed == len(pending):
                    mean = sum(latencies) / len(latencies) if latencies else 0.0
                    print(f"  [{completed}/{len(pending)}] ok={ok} failed={failed} "
                          f"mean_latency={mean:.2f}s")

    print(f"\nlabelled {ok}, failed {failed}, written to {output_path}")
    if latencies:
        latencies.sort()
        print(f"teacher latency: p50 {latencies[len(latencies)//2]:.2f}s "
              f"p95 {latencies[int(len(latencies)*0.95)]:.2f}s")
        print("This latency is the reason for distilling: it is the per-ticket cost of serving "
              "the teacher directly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
