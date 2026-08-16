# 17. LLM triage and distillation

Triage is done by a language model reading the unified multimodal payload, not by a bag-of-words
classifier reading the text alone. This document covers the dataset that makes that possible, the
teacher and student models, and the reasons for each choice.

## The idea

```
  audio ─┐
  image ─┼─► edge conversion ─► UnifiedTicketPayload ─► TEACHER LLM ─► triage judgement
  text  ─┘      (Whisper, VLM)     (fused_text +          (Llama 3.1 8B)   {department, band,
                                    provenance)                             sentiment, intent,
                                                                            fault, rationale}
                                          │                                        │
                                          └────────────────┬───────────────────────┘
                                                           ▼
                                              distillation_dataset.jsonl
                                                           │
                                                           ▼
                                              STUDENT (DistilBERT, 66M)
                                              trained to reproduce the
                                              teacher's judgements
                                                           │
                                                           ▼
                                              serves triage in milliseconds
```

The teacher is accurate and explains itself but costs seconds per ticket on CPU. The student is
two orders of magnitude smaller, answers in milliseconds, and needs no model server. Distillation
moves the teacher's judgement into an artefact that can sit on the hot path.

## Why the unified payload is the training input

The training input is the same `fused_text` the model will see in production, complete with its
`[CUSTOMER_TEXT]`, `[AUDIO:id]` and `[IMAGE:id]` markers.

This matters more than it might appear. Training a classifier on raw Bitext text and then serving
it fused multimodal text is a train/serve skew bug: the model has never seen the markers, has
never seen an ASR transcript with its errors, and has never seen a router panel description. It
will underperform in production for reasons no amount of hyperparameter tuning will fix, and the
offline metrics will not show it.

`mlops/build_unified_dataset.py` produces that dataset from three sources.

| Source | Supplies | Real or synthetic |
|---|---|---|
| Bitext | customer text, ground-truth category and intent | real |
| Telecom supplement | telecom fault vocabulary Bitext lacks entirely | generated, project-authored |
| minds14 | 8 kHz call audio transcribed by Whisper | **real audio, real ASR output** |
| LED scenarios | router panel and speed-test descriptions | **synthetic**, marked `visual_synthetic: true` |

The audio is genuinely transcribed, errors included, because a synthetic "transcript" would teach
the model that transcription is clean, which is exactly the assumption that breaks in production.
Measured Whisper confidence on these calls runs 0.51 to 0.80, and the resulting text contains real
recognition errors, which is the point.

The visual summaries are synthetic and this is a real limitation. The Roboflow router dataset
carries no LED annotations (verified by reading the COCO categories, see
`docs/03-data-preparation.md`), so there is no labelled corpus of router panel states to draw
from. Rows carrying a synthetic image are flagged so they can be excluded from any analysis where
that matters.

### Modality coherence

Modalities are attached only where they make sense together. An early version of the builder
paired modalities at random and produced tickets like a "track my order" complaint carrying
banking call audio and a photograph of a router: an input no customer could ever submit, and one
that a teacher asked to triage would be labelling as noise. Images now attach only to telecom
departments, and are drawn from scenarios matching that department.

## The teacher

`llama3.1:8b-instruct-q4_K_M` through Ollama, prompted by `models/prompts/llm/triage.txt`.

The prompt is worth reading in full, but three instructions in it carry most of the weight:

- **Treat audio as less reliable than typed text**, because it is a machine transcript. Without
  this the model weights an ASR error as heavily as something the customer actually typed.
- **Prefer the image for hardware state when it contradicts the text.** A photograph of a panel is
  direct evidence; a customer's description of it is a report.
- **When evidence is thin, choose the safer option.** A confident wrong department sends a ticket
  to a queue that cannot resolve it, which is worse than an honest `general` with low confidence.

Every teacher output is validated before it enters the dataset: the department must be one of the
seven, the band one of the four, the confidence in range. A teacher that hallucinates a class
outside the taxonomy produces a label the routing layer cannot act on, so those rows are rejected
rather than trained on.

The labeller is resumable and flushes after every row, because a run over thousands of tickets
will be interrupted.

## The student

DistilBERT with three heads on a shared encoder: department, priority band, sentiment. Sharing is
deliberate. All three judgements come from the same evidence, one encoder is cheaper than three,
and multi-task training regularises each head against the others.

Two signals are learned from:

1. the teacher's hard label, as cross-entropy;
2. the teacher's stated confidence, as a per-example weight, so a ticket the teacher was unsure
   about contributes less than one it was certain of.

Department is weighted 2.0 in the loss against 1.0 for band and 0.5 for sentiment, because the
department is the decision the routing layer acts on and a wrong one misroutes the ticket.

**A limitation worth stating plainly.** True distillation trains on the teacher's full output
distribution, not just its top choice. Ollama's chat API exposes no per-class probabilities, so
the stated confidence is the strongest soft signal available. This is weaker than a proper KL
divergence against teacher logits. Serving the teacher through vLLM, which can return logprobs,
would allow the stronger form.

## Serving

`TriageModelPort` is a new port alongside `ClassifierPort`. It exists because a triage LLM
produces department, band, sentiment and a rationale together, and forcing that through a port
that returns only a department would discard most of it.

| `triage_model_impl` | Adapter | Use |
|---|---|---|
| `none` | falls back to `ClassifierPort` | the original scikit-learn and rule paths |
| `llm` | `LlmTriageModel` | teacher served directly; accurate, seconds per ticket |
| `distilled` | `DistilledTriageModel` | the student; milliseconds, intended production path |
| `stub` | `StubTriageModel` | CI |

`triage_svc` prefers a triage model when one is configured and falls back to the classifier
otherwise, which is what keeps the rule-only profile and the degradation tests working.

Three properties are preserved regardless of which adapter runs:

- **Routing rules still override the model.** An operator-authored rule is policy and policy beats
  a prediction (ADR-010).
- **Priority signals still come from the deterministic policy**, so the workspace can always show
  why a score was assigned, even when a model assigned it.
- **Every adapter degrades to rules rather than raising.** A triage failure must leave the ticket
  reaching the agent flagged, never stranded.

`triage_result` now records `model_version` and `rationale`, so any historical triage can be
attributed to the model that produced it.

## Running it

```bash
# 1. Build unified payloads from the multimodal sources.
python -m mlops.build_unified_dataset --limit 2000 --with-audio 40

# 2. Label them with the teacher. Resumable; expect 1-3 s per ticket on CPU.
ollama serve
ollama pull llama3.1:8b-instruct-q4_K_M
python -m mlops.llm_triage_labeller --limit 500

# 3. Distil the student.
python -m mlops.train_distilled_triage --epochs 3 --register

# 4. Serve it.
#    .env:  TRIAGE_MODEL_IMPL=distilled
```

## Status

Built and verified end to end:

| Stage | Result |
|---|---|
| Unified dataset | 300 payloads, real Whisper transcripts of minds14 telephony, provenance spans verified |
| Teacher labelling | 300 labelled, 0 rejected, resumable, JSON parser handles fenced and prose-wrapped output |
| Student training | DistilBERT 66.4M params, 2 epochs on CPU |
| Student accuracy | department 0.85, band 0.87, sentiment 0.92 on a 60-row held-out split |
| Student latency | **73 ms per ticket** after warm-up |
| Serving | loads through `TriageModelPort` in the `cpu` profile; `triage_svc` uses it; 42 tests pass |

**The teacher was a stand-in, not Llama 3.1.** The Ollama model download failed repeatedly on this
connection: the 8B stalled around 20% at 3.5 MB/s, a 3B retry restarted from zero, and a 0.5B
attempt died with `net/http: TLS handshake timeout` against the CDN. To keep the pipeline
verifiable, the labeller was driven by a deterministic keyword teacher through the same
`call_teacher` seam, so every other component was exercised for real.

What this means for the numbers. The 0.85 department accuracy measures how well the student
reproduces its teacher, which is the right metric for distillation, but the teacher here was a
keyword rule, so the figure demonstrates that distillation works mechanically rather than that the
system triages well. `models/artifacts/distilled_triage/config.json` records
`teacher_model: "stand-in rule teacher"` so the artefact cannot be mistaken for one distilled from
an LLM.

To obtain real numbers, once `ollama pull llama3.1:8b-instruct-q4_K_M` completes:

```bash
rm data/processed/distillation_dataset.jsonl
python -m mlops.llm_triage_labeller --limit 500
python -m mlops.train_distilled_triage --epochs 3 --register
```

Nothing in the code changes. The stand-in existed only in a throwaway test harness, never in
`mlops/llm_triage_labeller.py` itself.

The 300-row dataset is also small, and 9% multimodal. Both should rise substantially before the
accuracy figures mean anything: `--limit 2000 --with-audio 40` is a more reasonable starting
point.
