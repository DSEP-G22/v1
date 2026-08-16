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

Built and verified: the unified dataset builder (300 payloads, real Whisper transcripts,
provenance spans checked), the triage port and all four adapters including the rule fallback, the
`triage_svc` integration, and the schema changes. 42 tests pass with the triage model on the hot
path.

Not yet run end to end: the teacher labelling pass and the student training, because the Ollama
model download did not complete on this connection (roughly 3.5 MB/s for a 4.9 GB model, competing
with a second pull). The code paths are written and their failure modes are handled, but the
accuracy numbers do not exist yet and no claim is made about them. Run steps 2 and 3 above once
the model is present.
