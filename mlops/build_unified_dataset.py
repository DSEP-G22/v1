"""Build the unified multimodal dataset that the triage LLM and its distilled student consume.

The system's contract is that every modality is converted to text at the edge and fused into one
`UnifiedTicketPayload` before any cognitive stage sees it (SAD ADR-002, C2). This script produces
a dataset in exactly that shape, so what a model is trained on is byte-identical to what it will
be served at inference time. Training on raw Bitext text and serving on fused multimodal text
would be a train/serve skew bug that no amount of accuracy tuning would fix.

Three sources are combined:

*   **Bitext** customer-support text, which supplies the text modality and a ground-truth
    category and intent.
*   **Telecom supplement**, which supplies the telecom fault vocabulary Bitext has none of.
*   **minds14** real 8 kHz call audio, transcribed by Whisper, which supplies genuine ASR output
    including its errors. Synthetic "transcripts" would teach the model that transcription is
    clean, which is precisely the assumption that breaks in production.

Visual summaries are synthesised from the router fault vocabulary rather than run through a VLM,
because the Roboflow dataset carries no LED annotations (verified, see docs/03-data-preparation.md)
and no other labelled router-panel corpus is available here. Those rows are marked
`visual_synthetic: true` so a reader can exclude them.

Output: `data/processed/unified_dataset.jsonl`, one `UnifiedTicketPayload`-shaped record per line.

    python -m mlops.build_unified_dataset --limit 2000 --with-audio 40
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

OUTPUT = REPO_ROOT / "data" / "processed" / "unified_dataset.jsonl"

# Router panel states paired with the fault they indicate. Used to synthesise the visual modality
# so a share of tickets exercise the image path end to end.
LED_SCENARIOS = [
    {
        "summary": "Router front panel: POWER solid red, DSL off, INTERNET off, WiFi off.",
        "fields": {"device_model": "ZTE F660", "led_states": [
            {"label": "POWER", "colour": "red", "behaviour": "solid"},
            {"label": "DSL", "colour": "off", "behaviour": "off"},
            {"label": "INTERNET", "colour": "off", "behaviour": "off"}]},
        "fault": "fault_power_supply",
        "department": "technical_support",
    },
    {
        "summary": "Router front panel: POWER solid green, DSL blinking red, INTERNET off.",
        "fields": {"device_model": "Huawei HG8145", "led_states": [
            {"label": "POWER", "colour": "green", "behaviour": "solid"},
            {"label": "DSL", "colour": "red", "behaviour": "blinking"},
            {"label": "INTERNET", "colour": "off", "behaviour": "off"}]},
        "fault": "fault_line_sync",
        "department": "network_operations",
    },
    {
        "summary": "Router rear: fiber connector unseated, LAN cable connected, power connected.",
        "fields": {"device_model": "unknown", "ports": [
            {"port_type": "fiber", "connected": False},
            {"port_type": "lan", "connected": True},
            {"port_type": "power", "connected": True}]},
        "fault": "fault_cable_disconnected",
        "department": "field_service",
    },
    {
        "summary": "Speed test screenshot: 2.1 Mbps down, 0.4 Mbps up, ping 180 ms.",
        "fields": {"numeric_values": {"download_mbps": 2.1, "upload_mbps": 0.4, "ping_ms": 180}},
        "fault": "fault_degraded_throughput",
        "department": "network_operations",
    },
]


def fuse(original_text: str, transcript: dict | None, visual: dict | None) -> tuple[str, list[dict]]:
    """Build fused text and exact provenance spans.

    Mirrors `libs/domain/policy/fusion.py`. Spans are computed from a single list of fragments so
    `fused_text[start:end]` always returns the fragment it claims to, which the payload validator
    checks and which the workspace relies on to label evidence.
    """
    fragments: list[tuple[str, dict]] = []

    if original_text.strip():
        fragments.append((
            f"[CUSTOMER_TEXT] {original_text.strip()}",
            {"modality": "text", "source": "customer", "confidence": 1.0},
        ))
    if transcript:
        fragments.append((
            f"[AUDIO:{transcript['attachment_id']}] {transcript['text'].strip()}",
            {"modality": "audio", "source": transcript["attachment_id"],
             "confidence": transcript["confidence"], "model_version": transcript["model_version"]},
        ))
    if visual:
        fragments.append((
            f"[IMAGE:{visual['attachment_id']}] {visual['summary_text'].strip()}",
            {"modality": "image", "source": visual["attachment_id"],
             "confidence": visual["confidence"], "model_version": visual["model_version"]},
        ))

    parts, provenance, offset = [], [], 0
    for text, meta in fragments:
        parts.append(text)
        provenance.append({**meta, "span": [offset, offset + len(text)]})
        offset += len(text) + 2  # the "\n\n" separator

    return "\n\n".join(parts), provenance


def load_text_rows(limit: int | None, seed: int) -> list[dict]:
    import pandas as pd

    frames = []
    processed = REPO_ROOT / "data" / "processed" / "train.csv"
    if processed.exists():
        frames.append(pd.read_csv(processed)[["text", "department", "intent"]])
    else:
        raise FileNotFoundError(
            f"{processed} not found. Run notebooks/01_data_preparation.ipynb or `dvc repro prepare` first."
        )

    df = pd.concat(frames, ignore_index=True).dropna(subset=["text", "department"])
    df = df.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    if limit:
        df = df.head(limit)
    return df.to_dict("records")


def transcribe_audio(count: int) -> list[dict]:
    """Real Whisper transcripts of real telephone audio, errors included."""
    if count <= 0:
        return []
    try:
        from evaluation.datasets import hf_audio
    except ImportError:
        return []

    if not hf_audio.is_available():
        print("datasets not installed; skipping the audio modality")
        return []

    try:
        samples = hf_audio.materialise(REPO_ROOT / "data" / "raw" / "minds14", limit=count)
    except Exception as exc:  # noqa: BLE001
        print(f"minds14 unavailable ({type(exc).__name__}); skipping the audio modality")
        return []

    if not samples:
        return []

    import math

    from faster_whisper import WhisperModel

    model = WhisperModel("base", device="cpu", compute_type="int8")
    transcripts = []
    for sample in samples:
        segments, _ = model.transcribe(str(sample.audio_path), language="en")
        segments = list(segments)
        if not segments:
            continue
        confidence = sum(math.exp(s.avg_logprob) for s in segments) / len(segments)
        transcripts.append({
            "attachment_id": f"att-audio-{sample.id}",
            "text": " ".join(s.text for s in segments).strip(),
            "reference_text": sample.reference_text,
            "confidence": round(confidence, 4),
            "low_confidence": confidence < 0.60,
            "model_version": "faster-whisper-base",
            "duration_s": round(sample.duration_s, 2),
            "source_intent": sample.intent,
            # The department this utterance is *about*, mapped from the minds14 intent. The
            # builder attaches a call only to a ticket of the same department, so the two
            # modalities describe one problem instead of two.
            "source_department": sample.department,
        })
        print(f"  transcribed {sample.id} conf={confidence:.3f} intent={sample.intent}")
    return transcripts


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the unified multimodal dataset")
    parser.add_argument("--limit", type=int, default=2000, help="text rows to include")
    parser.add_argument("--with-audio", type=int, default=30, help="real transcribed calls to attach")
    parser.add_argument("--image-fraction", type=float, default=0.25,
                        help="share of tickets that also carry a visual summary")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default=str(OUTPUT))
    args = parser.parse_args()

    random.seed(args.seed)

    print(f"[1/4] loading text rows (limit {args.limit})")
    rows = load_text_rows(args.limit, args.seed)
    print(f"      {len(rows)} rows")

    print(f"[2/4] transcribing {args.with_audio} real calls with Whisper")
    transcripts = transcribe_audio(args.with_audio)
    print(f"      {len(transcripts)} transcripts")

    print("[3/4] fusing into unified payloads")
    base_time = datetime.now(timezone.utc) - timedelta(days=30)
    records = []

    # Modalities are attached only where they are semantically coherent with the text. Pairing a
    # "track my order" complaint with banking call audio and a router photograph would produce a
    # ticket no customer could ever submit, and a teacher LLM asked to triage it would be labelling
    # noise. Coherence is the whole point of a fused payload.
    TELECOM_DEPARTMENTS = {"technical_support", "network_operations", "field_service"}

    # Audio attaches only to a ticket of the same department as the call is about. An earlier
    # version attached calls to any ticket, on the reasoning that minds14 is "generic support
    # speech". It is not: it is banking-domain, so that rule produced tickets whose text asked to
    # track an order while the attached call asked to open a joint account. Two unrelated problems
    # in one ticket is not a hard multimodal example, it is a corrupt label, and the teacher would
    # have had to pick one topic arbitrarily.
    audio_by_department: dict[str, list[dict]] = {}
    for transcript_row in transcripts:
        audio_by_department.setdefault(transcript_row["source_department"], []).append(transcript_row)
    audio_cursor = {department: 0 for department in audio_by_department}

    for index, row in enumerate(rows):
        department = row["department"]

        transcript = None
        available = audio_by_department.get(department, [])
        cursor = audio_cursor.get(department, 0)
        if cursor < len(available) and random.random() < 0.5:
            transcript = available[cursor]
            audio_cursor[department] = cursor + 1

        # A router photograph only makes sense on a telecom fault. Attaching one to a billing
        # query would teach the model that images are uninformative.
        visual = None
        if department in TELECOM_DEPARTMENTS and random.random() < args.image_fraction:
            candidates = [s for s in LED_SCENARIOS if s["department"] == department] or LED_SCENARIOS
            scenario = random.choice(candidates)
            visual = {
                "attachment_id": f"att-image-{index:05d}",
                "summary_text": scenario["summary"],
                "extracted_fields": scenario["fields"],
                "confidence": round(random.uniform(0.62, 0.94), 3),
                "model_version": "vlm-synthetic",
                "prompt_template": "router_led_panel",
                "implied_fault": scenario["fault"],
                "implied_department": scenario["department"],
            }

        fused_text, provenance = fuse(row["text"], transcript, visual)
        modalities = [p["modality"] for p in provenance]

        flags = []
        if transcript and transcript["low_confidence"]:
            flags.append("LOW_ASR_CONFIDENCE")
        if visual and visual["confidence"] < 0.70:
            flags.append("LOW_VLM_CONFIDENCE")

        records.append({
            "schema_version": "1.0.0",
            "ticket_id": f"synth-{index:06d}",
            "customer_id": f"cust-{index % 500:04d}",
            "channel": random.choice(["web_portal", "email", "chat", "phone"]),
            "created_at": (base_time + timedelta(minutes=index * 7)).isoformat(),
            "original_text": row["text"],
            "transcripts": [transcript] if transcript else [],
            "visual_summaries": [visual] if visual else [],
            "fused_text": fused_text,
            "provenance": provenance,
            "flags": flags,
            "partial": False,
            "metadata": {
                "modalities": modalities,
                "is_multimodal": len(modalities) > 1,
                "visual_synthetic": visual is not None,
                "audio_real": transcript is not None,
            },
            "revision": 1,
            # Ground truth carried alongside, never inside the payload: the payload is the model's
            # input and must contain nothing the model would not have at inference time.
            "ground_truth": {
                "department": row["department"],
                "intent": row.get("intent"),
                "implied_fault": visual["implied_fault"] if visual else None,
            },
        })

    print("[4/4] writing")
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    multimodal = sum(1 for r in records if r["metadata"]["is_multimodal"])
    with_audio = sum(1 for r in records if r["metadata"]["audio_real"])
    with_image = sum(1 for r in records if r["visual_summaries"])
    print(f"wrote {len(records)} payloads to {out}")
    print(f"  multimodal: {multimodal} | real audio: {with_audio} | image: {with_image}")

    # Fail loudly if provenance spans do not resolve: a silently wrong span would corrupt every
    # downstream evidence view without any visible error.
    for record in records[:200]:
        for entry in record["provenance"]:
            start, end = entry["span"]
            if not record["fused_text"][start:end].strip():
                raise AssertionError(f"bad provenance span in {record['ticket_id']}")
    print("  provenance spans verified on the first 200 records")

    # Every attached modality must agree with the ticket's department. Incoherent pairings are
    # invisible in the aggregate counts above, so they are asserted rather than eyeballed.
    for record in records:
        department = record["ground_truth"]["department"]
        for transcript_row in record["transcripts"]:
            if transcript_row["source_department"] != department:
                raise AssertionError(
                    f"{record['ticket_id']}: {transcript_row['source_department']} audio on a "
                    f"{department} ticket"
                )
        for visual_row in record["visual_summaries"]:
            if visual_row["implied_department"] not in TELECOM_DEPARTMENTS:
                raise AssertionError(f"{record['ticket_id']}: non-telecom image attached")
    print("  modality coherence verified on all records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
