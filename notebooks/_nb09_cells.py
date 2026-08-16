"""Cell definitions for notebooks/09_unified_dataset.ipynb, applied by _build_notebooks.py.

Kept as a Python file so the notebook is reviewable in a diff and regenerable, rather than being
edited as raw JSON.
"""

CELLS = [
    ("markdown", """# 09. Building the unified multimodal dataset

**Inputs:** `data/processed/train.csv` (Bitext plus the telecom supplement), `PolyAI/minds14`
real 8 kHz call audio from Hugging Face, and the router LED scenario vocabulary.

**Outputs:** `data/processed/unified_dataset.jsonl`, one `UnifiedTicketPayload`-shaped record per
line, ready for the teacher LLM in notebook 10.

**Why this notebook exists.** The system converts every modality to text at the edge and fuses it
into a single payload before any cognitive stage runs (SAD ADR-002, C2). A model trained on raw
Bitext text but served fused multimodal text has a train/serve skew bug: it has never seen an
`[AUDIO:...]` marker, never seen an ASR error, never seen a router panel description. Offline
metrics will not reveal that, and no amount of tuning will fix it. So the training corpus is built
in exactly the production shape."""),

    ("markdown", """## What each source contributes

| Source | Supplies | Real or synthetic |
|---|---|---|
| Bitext + telecom supplement | customer text, ground-truth department and intent | real (supplement is project-authored) |
| minds14 | 8 kHz call audio transcribed by Whisper | **real audio, real ASR output** |
| LED scenarios | router panel and speed-test descriptions | **synthetic**, flagged `visual_synthetic: true` |

The audio is genuinely transcribed, errors included. A hand-written "transcript" would teach the
model that transcription is clean, which is precisely the assumption that breaks in production.

The visual summaries are synthetic, and that is a real limitation rather than a shortcut. The
Roboflow router dataset carries no LED annotations (verified by reading its COCO categories, see
`docs/03-data-preparation.md`), so there is no labelled corpus of router panel states to draw on.
Rows carrying a synthetic image are flagged so any analysis can exclude them."""),

    ("code", """from mlops.build_unified_dataset import LED_SCENARIOS, fuse

# `fuse` mirrors libs/domain/policy/fusion.py. Spans are computed from one fragment list so that
# fused_text[start:end] always returns the fragment the provenance entry claims it does, which the
# payload validator checks and the agent workspace relies on to label evidence.
demo_text = "my internet has been down since this morning"
demo_audio = {
    "attachment_id": "att-audio-demo",
    "text": "the light on the box is red and nothing works",
    "confidence": 0.71,
    "model_version": "faster-whisper-base",
}
demo_image = {
    "attachment_id": "att-image-demo",
    "summary_text": LED_SCENARIOS[1]["summary"],
    "confidence": 0.88,
    "model_version": "vlm-synthetic",
}

fused, provenance = fuse(demo_text, demo_audio, demo_image)
print(fused)
print()
for entry in provenance:
    start, end = entry["span"]
    print(f"{entry['modality']:6s} conf={entry['confidence']:.2f}  ->  {fused[start:end][:60]!r}")"""),

    ("markdown", """## Modality coherence, and a bug this notebook exists to prevent

Modalities are attached only where they are semantically coherent with the text.

An early version of the builder attached audio to any ticket, reasoning that the minds14
transcripts were generic support speech. They are not: minds14 is banking-domain. That rule
produced tickets whose text asked to track an order while the attached call asked to open a joint
account. Two unrelated problems in one ticket is not a hard multimodal example, it is a corrupt
label, and the teacher would have had to pick one topic arbitrarily.

Two rules now hold, and both are asserted at the end of the build rather than eyeballed:

1. audio attaches only to a ticket whose department matches the call's own intent-mapped
   department;
2. a router photograph attaches only to a telecom department, because attaching one to a billing
   query would teach the model that images are uninformative."""),

    ("code", """import json
from collections import Counter
from pathlib import Path

rows = [json.loads(line) for line in
        Path("data/processed/unified_dataset.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()]

print(f"payloads:    {len(rows)}")
print(f"multimodal:  {sum(r['metadata']['is_multimodal'] for r in rows)}")
print(f"with audio:  {sum(bool(r['transcripts']) for r in rows)}")
print(f"with image:  {sum(bool(r['visual_summaries']) for r in rows)}")
print()
print("departments:", dict(Counter(r["ground_truth"]["department"] for r in rows).most_common()))"""),

    ("code", """# Coherence check, re-run here so the notebook fails loudly if the dataset on disk was built
# by an older version of the builder.
TELECOM = {"technical_support", "network_operations", "field_service"}
violations = []
for row in rows:
    department = row["ground_truth"]["department"]
    for transcript in row["transcripts"]:
        if transcript.get("source_department") != department:
            violations.append((row["ticket_id"], "audio", transcript.get("source_department"), department))
    for visual in row["visual_summaries"]:
        if visual["implied_department"] not in TELECOM:
            violations.append((row["ticket_id"], "image", visual["implied_department"], department))

print(f"coherence violations: {len(violations)}")
assert not violations, violations[:5]"""),

    ("markdown", """## The audio subset, and why it is stratified

minds14 is stored grouped by intent, so taking the first N rows returns N utterances of the *same*
intent. An early 6-row subset came back as six `joint_account` calls, which is not an audio sample
of a support line, it is one question asked six ways.

`hf_audio.load(stratify=True)` instead takes rows round-robin across intents, so even a small
subset covers the intent space.

A second bug is worth recording because it was silent. `materialise` originally named its WAV
files by enumeration index (`minds14_0001.wav`) and skipped writing a file that already existed.
Once the subset selection changed, index 1 referred to a different utterance, but the old file was
still on disk and was reused: the audio no longer matched the transcript and intent recorded
beside it. Filenames now include the intent, so a changed subset writes new files instead of
silently reading mismatched ones."""),

    ("code", """audio_rows = [r for r in rows if r["transcripts"]]
print("intents covered:", dict(Counter(r["transcripts"][0]["source_intent"] for r in audio_rows)))
print()
for row in audio_rows[:5]:
    transcript = row["transcripts"][0]
    print(f"[{row['ground_truth']['department']}] intent={transcript['source_intent']} "
          f"conf={transcript['confidence']:.2f}")
    print(f"   text : {row['original_text'][:70]}")
    print(f"   audio: {transcript['text'][:70]}")"""),

    ("markdown", """### Whisper errors are kept, deliberately

Some transcripts contain real recognition errors ("what is my occult balance" for "what is my
account balance"). These are not cleaned. Whisper confidence on this 8 kHz telephony runs roughly
0.32 to 0.86, and the low-confidence rows are exactly the ones the `LOW_ASR_CONFIDENCE` flag and
the teacher prompt's "treat audio as less reliable than typed text" instruction exist to handle.
Removing them would remove the reason those mechanisms exist."""),

    ("code", """import statistics

confidences = [r["transcripts"][0]["confidence"] for r in audio_rows]
if confidences:
    print(f"ASR confidence: min {min(confidences):.2f} | median {statistics.median(confidences):.2f} "
          f"| max {max(confidences):.2f}")
    print(f"below the 0.60 low-confidence threshold: "
          f"{sum(c < 0.60 for c in confidences)}/{len(confidences)}")

flagged = [r for r in rows if r["flags"]]
print(f"\\nflagged payloads: {len(flagged)}")
print("flags:", dict(Counter(f for r in flagged for f in r["flags"])))"""),

    ("code", """# One complete multimodal payload, as the teacher will receive it.
example = next(r for r in rows if len(r["metadata"]["modalities"]) > 1)
print("ticket:", example["ticket_id"], "| modalities:", example["metadata"]["modalities"])
print("ground truth:", example["ground_truth"])
print("-" * 78)
print(example["fused_text"])"""),

    ("markdown", """## Rebuilding

```bash
python -m mlops.build_unified_dataset --limit 1200 --with-audio 60
```

`--with-audio` costs a Whisper pass per call, so it dominates the runtime. Transcripts are cached
as WAV files under `data/raw/minds14/`, but the transcription itself re-runs.

Next: **notebook 10** labels these payloads with a teacher LLM and trains the two triage models
that consume them."""),
]
