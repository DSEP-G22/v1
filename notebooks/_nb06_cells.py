"""Cell definitions for notebooks/06_asr_evaluation.ipynb, applied by _build_notebooks.py.

Kept as a Python file so the notebook is reviewable in a diff and regenerable, rather than being
edited as raw JSON.
"""

CELLS = [
    ("markdown", """# 06. ASR evaluation on real call-centre audio

**Inputs:** `PolyAI/minds14` (`en-US`) from Hugging Face, 563 real support calls recorded over the
telephone at 8 kHz with human reference transcripts, CC-BY-4.0. Falls back to
`ingestion-pipeline-prototype/data/sample_audio/` when the dataset cannot be downloaded.

**Outputs:** a real WER figure per model size, a per-segment confidence distribution, latency per
audio-minute, and a calibrated `asr_low_confidence_threshold`.

**Why this dataset.** The system's real input is a customer phoning about a fault. 8 kHz telephony
is the condition that actually degrades Whisper, so a WER measured on clean read speech would be
optimistic in a way the deployed system never reproduces. minds14 also carries intent labels, so
the same download serves the intent work.

**What changed from the previous version of this notebook.** It previously ran on two local sample
files, one of which is a synthetic tone with no reference transcript, so no real WER could be
computed and the notebook said so. That limitation is now resolved."""),

    ("code", """import os
import sys
from pathlib import Path

# Notebook hygiene: run from the v1 root, never hard-code absolute paths.
_here = Path.cwd()
if _here.name == "notebooks":
    os.chdir(_here.parent)
sys.path.insert(0, str(Path.cwd()))

print("cwd:", Path.cwd())"""),

    ("code", """from evaluation.datasets import hf_audio

# Materialise a subset to disk as 16 kHz WAV. The pipeline ingests files, not arrays, so this
# exercises the same path a customer upload would take.
SAMPLE_LIMIT = 30
audio_dir = Path("data/raw/minds14")

samples = []
if hf_audio.is_available():
    try:
        samples = hf_audio.materialise(audio_dir, limit=SAMPLE_LIMIT)
        print(f"minds14: {len(samples)} utterances at {audio_dir}")
    except Exception as exc:
        print(f"minds14 unavailable ({type(exc).__name__}: {exc}); falling back to local samples")

if not samples:
    samples = list(hf_audio.iter_local_fallback(Path("../ingestion-pipeline-prototype/data/sample_audio")))
    print(f"fallback: {len(samples)} local file(s), no reference transcripts, so WER is not computable")

has_references = any(s.reference_text for s in samples)
print("reference transcripts available:", has_references)"""),

    ("markdown", """## Transcribe with each model size, measuring WER and latency

WER is computed with `jiwer` after light normalisation (lowercase, strip punctuation), which is
the standard treatment and avoids penalising the model for casing the reference did not mark."""),

    ("code", """import time

import jiwer
from faster_whisper import WhisperModel

MODEL_SIZES = ["tiny", "base", "small"]

# jiwer requires the transform chain to end by splitting into words, otherwise it rejects the
# input with "each reference should be a list of strings".
normalise = jiwer.Compose([
    jiwer.ToLowerCase(),
    jiwer.RemovePunctuation(),
    jiwer.RemoveMultipleSpaces(),
    jiwer.Strip(),
    jiwer.ReduceToListOfListOfWords(),
])

rows = []
for size in MODEL_SIZES:
    model = WhisperModel(size, device="cpu", compute_type="int8")
    hypotheses, references, total_audio_s, total_wall_s = [], [], 0.0, 0.0

    for sample in samples:
        t0 = time.time()
        segments, info = model.transcribe(str(sample.audio_path), language="en")
        segments = list(segments)
        total_wall_s += time.time() - t0
        total_audio_s += info.duration

        text = " ".join(s.text for s in segments).strip()
        if sample.reference_text:
            hypotheses.append(text)
            references.append(sample.reference_text)

    entry = {
        "model": size,
        "utterances": len(samples),
        "audio_minutes": round(total_audio_s / 60, 2),
        "wall_seconds": round(total_wall_s, 1),
        "realtime_factor": round(total_wall_s / total_audio_s, 3) if total_audio_s else None,
    }
    if references:
        entry["wer"] = round(
            jiwer.wer(references, hypotheses, reference_transform=normalise, hypothesis_transform=normalise), 4
        )
    rows.append(entry)
    print(entry)"""),

    ("markdown", """## Confidence calibration

`asr_low_confidence_threshold` decides when a transcript is flagged for the agent to verify. It is
calibrated so that flagged transcripts capture the majority of genuinely bad ones: too low and
nothing is flagged, too high and every transcript is, which trains agents to ignore the flag."""),

    ("code", """import math

model = WhisperModel("base", device="cpu", compute_type="int8")
per_utterance = []

for sample in samples:
    segments, _ = model.transcribe(str(sample.audio_path), language="en")
    segments = list(segments)
    if not segments:
        continue
    # faster-whisper exposes avg_logprob; exp() maps it to a 0..1 confidence.
    confidence = sum(math.exp(s.avg_logprob) for s in segments) / len(segments)
    text = " ".join(s.text for s in segments).strip()
    entry = {"id": sample.id, "confidence": round(confidence, 4), "segments": len(segments)}
    if sample.reference_text:
        entry["wer"] = round(
            jiwer.wer(sample.reference_text, text, reference_transform=normalise, hypothesis_transform=normalise), 4
        )
    per_utterance.append(entry)

print(f"{len(per_utterance)} utterances scored")
for e in per_utterance[:5]:
    print(" ", e)"""),

    ("code", """# Choose the threshold that best separates high-WER utterances, when references exist.
scored = [e for e in per_utterance if "wer" in e]

recommended = 0.60
if scored:
    bad = [e for e in scored if e["wer"] > 0.30]
    good = [e for e in scored if e["wer"] <= 0.30]
    print(f"{len(bad)} poor transcripts (WER > 0.30), {len(good)} acceptable")

    best, best_score = recommended, -1.0
    for candidate in [x / 100 for x in range(30, 95, 5)]:
        caught = sum(1 for e in bad if e["confidence"] < candidate)
        false_alarms = sum(1 for e in good if e["confidence"] < candidate)
        recall = caught / len(bad) if bad else 0.0
        precision = caught / (caught + false_alarms) if (caught + false_alarms) else 0.0
        f1 = 2 * recall * precision / (recall + precision) if (recall + precision) else 0.0
        if f1 > best_score:
            best, best_score = candidate, f1
    recommended = best
    print(f"recommended asr_low_confidence_threshold = {recommended} (F1 {best_score:.3f})")
else:
    print("no reference transcripts, so the default threshold is kept:", recommended)"""),

    ("code", """import json

record = {
    "notebook": "06_asr_evaluation",
    "dataset": "PolyAI/minds14 en-US" if has_references else "local sample audio",
    "utterances": len(samples),
    "models": rows,
    "recommended_asr_low_confidence_threshold": recommended,
}

Path("evaluation/reports").mkdir(parents=True, exist_ok=True)
with open("evaluation/reports/metrics.jsonl", "a", encoding="utf-8") as fh:
    fh.write(json.dumps(record) + "\\n")

print(json.dumps(record, indent=2))"""),
]
