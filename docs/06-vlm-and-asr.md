# 06 — VLM and ASR

## VLM (notebooks/05_vlm_led_extraction.ipynb)

**Status: written, not executed** — Track B/C need a running Ollama server with `llava:7b`
(optionally `llava:13b`) pulled, unavailable in this sandbox.

### Dataset correction (verified by inspection, not assumed from the filename)

`data/router detection.v38-data_video.coco.zip` is a **cable/port/connector detection** dataset,
not an LED-colour-state dataset: 2,137 images, 4,630 boxes, categories `{fiber, lan, phone,
power, usb} x {cable, conn}` plus bare `phone`/`power`/`usb` port classes (verified via
`evaluation/datasets/roboflow_router.py::load_split`). The implementation plan's assumption that
this dataset covers "LED panel states" does not hold — it was corrected here rather than silently
worked around, since a wrong assumption baked silently into a notebook is worse than a documented
one.

Its actual use in the pipeline (per the notebook): a *structured hint* source — a detector over
this dataset's classes tells you which ports/cables are visibly connected, which gets injected
into the VLM prompt (`inject_structured_hint()` in the notebook) so the VLM's job narrows from
"describe the whole board" to "confirm/refine what a detector already found." A full
YOLO/Detectron training run over it is out of scope for v1.

### LED colour/behaviour ground truth

A **separate**, hand-labelled set, `data/processed/led_labels.jsonl` — this dataset has no LED
labels at all. This environment seeds it with the 2 router photos available
(`ingestion-pipeline-prototype/data/sample_images/router_{red,green}_led.png`); the plan's target
of 30-60 images needs more real router photos than are available here.

### Three-way comparison (as designed, not run)

| Track | Extractor | Needs |
|---|---|---|
| A | `HeuristicLedExtractor` (HSV masking + row clustering) | nothing — could run in this sandbox, kept alongside B/C unexecuted for a fair one-place comparison |
| B | `OllamaVisionExtractor` w/ `llava:7b` | Ollama server |
| C | `OllamaVisionExtractor` w/ `llava:13b` | Ollama server, more VRAM |

Field-level accuracy (device model, per-LED colour, per-LED behaviour) and JSON-validity rate,
against `led_labels.jsonl`.

### Chosen configuration (pending a real run)

Default to `vlm_impl=heuristic` (always available, matches the SAD deviation table's fallback
role) until Track B is measured to beat it on a real 30-60 image labelled set, then switch to
`vlm_impl=ollama`.

### Pitfall

Ollama vision needs the image as base64 **without** a `data:` prefix; a 400 "invalid image"
almost always means the prefix was left in, or the file is a PNG with an alpha channel that
should have been re-saved as RGB first —
`libs/platform/models/vlm.py::_ensure_rgb_png_bytes` already handles this for the real adapter.

## ASR (notebooks/06_asr_evaluation.ipynb)

**Status: executed for real** — `faster-whisper` `tiny`/`base` on CPU, no Ollama/GPU needed.

### Samples

`ingestion-pipeline-prototype/data/sample_audio/{sample_call.wav, audio.mp3}`:
- `sample_call.wav` — a **synthetic tone**, not speech (`generate_samples.py` generates it as
  such; confirmed by faster-whisper's VAD producing **zero segments** at every model size, both
  runs). Useful as a negative control.
- `audio.mp3` — real speech, ~11.5 minutes (a scam-call-style recording), 138-221 segments
  depending on model size.

### Known limitation, not worked around

Neither file has a human-labelled reference transcript, so **WER could not be computed** —
computing it against the model's own output would be circular. `wer_available: false` is recorded
explicitly in `evaluation/reports/metrics.jsonl` rather than a number being fabricated.

### Real measurements (from the executed run)

| model | sample | duration | transcribe time | latency/audio-min | mean confidence | segments |
|---|---|---|---|---|---|---|
| tiny | synthetic_tone | 2.0s | 0.6s | 18.0s | — (0 segments) | 0 |
| tiny | real_speech | 689.6s | 30.1s | 2.6s | 0.666 | 131 |
| base | synthetic_tone | 2.0s | 2.2s | 66.6s | — (0 segments) | 0 |
| base | real_speech | 689.6s | 67.2s | 5.8s | 0.675 | 221 |

(Exact numbers vary a few percent run-to-run; see `evaluation/reports/metrics.jsonl`,
`notebook: "06_asr_evaluation"`, for the numbers from the run that produced this table.)

### Threshold recommendation

The synthetic tone produces **zero segments** rather than low-confidence ones — `audio_svc`
already treats "the model returned nothing" and "the model returned a low-confidence transcript"
as two different, both-handled cases (an empty transcript still contributes an
`[AUDIO:...]` fragment of "" to `fuse()`, not a missing one; a failed/errored transcription is
the case that produces `PARTIAL_PAYLOAD`). On real speech, confidence ranges ~0.31-0.89 with a
mean of 0.65-0.68, comfortably straddling the v1 default `asr_low_confidence_threshold=0.60`.
This is **not** a statistically robust calibration (n=1 real recording) — it's a sanity check
that the default isn't obviously wrong. Revisit once a labelled call sample is available; see
`08-evaluation.md` for what a production ASR evaluation would additionally need.
