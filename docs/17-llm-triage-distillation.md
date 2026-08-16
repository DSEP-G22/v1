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

### Modality coherence, and two bugs it took assertions to find

Both bugs below produced a dataset that was correct in every summary statistic (row counts,
modality counts, department distribution) and wrong row by row. Both are now asserted at the end
of the build and covered by `tests/unit/test_unified_dataset_coherence.py`.

**Audio was attached to unrelated tickets.** The builder attached any call to any ticket, on the
stated assumption that minds14 was generic support speech. It is not: it is banking-domain. The
result was tickets whose text asked to track an order while the attached call asked to open a
joint account. Two unrelated problems in one ticket is not a hard multimodal example, it is a
corrupt label, and the teacher had to pick one topic arbitrarily. Audio now attaches only where
the call's intent-mapped department matches the ticket's.

**The audio subset was one intent repeated.** minds14 is stored grouped by intent, so
`ds.select(range(6))` returned six `joint_account` calls. `hf_audio.load(stratify=True)` now takes
rows round-robin across intents.

**Stale WAV files silently mismatched their labels.** `materialise` named files by enumeration
index and skipped any that already existed. Once subset selection changed, `minds14_0001.wav`
referred to a different utterance, but the old file was still on disk and was read instead,
pairing one row's audio with another row's transcript and intent. Filenames now encode the intent,
so a changed subset writes new files rather than reading mismatched ones.

## The teacher

`gpt-oss:120b-cloud` through Ollama, prompted by `models/prompts/llm/triage.txt`.

The original choice was a local `llama3.1:8b-instruct-q4_K_M`. The pull failed repeatedly on this
connection: the 8B stalled around 20% at 3.5 MB/s, a 3B retry restarted from zero, and a 0.5B
attempt died with `net/http: TLS handshake timeout` against the CDN. An Ollama cloud model needs
no download and runs on the same `/api/chat` endpoint, so the switch is a single flag and nothing
else in the pipeline changes. Switching back to a local model once one is pulled is the same flag.

The teacher is a network call, so labelling is latency-bound rather than CPU-bound and
parallelises: 4.5 s/row sequentially against 2.2 s/row at 4 workers. Concurrency is capped at 4
deliberately, because at 8 workers the cloud endpoint began refusing roughly a third of requests,
so more workers produced fewer labels rather than more.

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

## The second student: frozen embeddings with linear heads

A fine-tuned 66M-parameter encoder is only worth its training cost if it beats the obvious cheap
alternative, so that alternative is built and measured rather than assumed to be worse.

```
fused_text -> [frozen MiniLM] -> 384-d vector -> LogisticRegression x3
```

`mlops/train_embedding_triage.py` encodes each payload once with the sentence-transformer that
already serves retrieval, caches the vectors, and fits three logistic-regression heads on them.

What it buys:

- **Training costs seconds, not minutes**, and the embedding cache means re-fitting after new
  agent corrections is nearly free. That is the cost the continuous-learning loop pays repeatedly,
  so it matters more than a one-off training run does.
- **It is the baseline that makes the distilled number interpretable.** Without it, an accuracy
  figure for the fine-tuned model cannot be called good or bad.
- **It adds no new model to the deployment**, because the encoder is already there.

What it gives up: the encoder never adapts to the domain. It cannot learn that `[AUDIO:...]` marks
lower-trust evidence, or what a DSL sync failure is, because its weights are frozen. Closing that
gap is precisely what fine-tuning is for.

Two details are load-bearing. `class_weight="balanced"` is set on each head, because the
department distribution is heavily skewed towards `general` and `billing` and an unweighted linear
model on skewed data collapses onto the majority class while still reporting a respectable
accuracy. And the teacher's confidence weights each example, mirroring the distilled trainer, so
both approaches learn from the same signal.

Both trainers call `split_dataset()`, which sorts by `ticket_id` before shuffling, so the held-out
set is identical for both. Comparing accuracy across two different random splits would measure the
split as much as the model.

## Serving

`TriageModelPort` is a new port alongside `ClassifierPort`. It exists because a triage LLM
produces department, band, sentiment and a rationale together, and forcing that through a port
that returns only a department would discard most of it.

| `triage_model_impl` | Adapter | Use |
|---|---|---|
| `none` | falls back to `ClassifierPort` | the original scikit-learn and rule paths |
| `llm` | `LlmTriageModel` | teacher served directly; accurate, seconds per ticket |
| `distilled` | `DistilledTriageModel` | fine-tuned student; milliseconds, intended production path |
| `embedding` | `EmbeddingTriageModel` | frozen encoder with linear heads; cheapest to retrain |
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
#    --with-audio costs a Whisper pass per call and dominates the runtime.
python -m mlops.build_unified_dataset --limit 1200 --with-audio 60

# 2. Label them with the teacher. Resumable, so an interrupted run is re-runnable as is.
ollama serve                       # a cloud model needs no pull, only `ollama signin`
python -m mlops.llm_triage_labeller --limit 1200 --workers 4

# 3. Train both students on the same split, then compare.
python -m mlops.train_distilled_triage --epochs 3 --register
python -m mlops.train_embedding_triage --register

# 4. Serve whichever wins.
#    .env:  TRIAGE_MODEL_IMPL=distilled   (or: embedding | llm | none)
```

Notebooks 09 and 10 walk through the same pipeline with the reasoning attached: **09** builds the
unified dataset and checks its coherence, **10** labels it, trains both students and compares
them.

## Status

Run end to end on real data with a real teacher.

| Stage | Result |
|---|---|
| Unified dataset | 1,200 payloads, 132 multimodal, real Whisper transcripts of minds14 telephony |
| Teacher labelling | **1,198 labelled by `gpt-oss:120b-cloud`**, 2 failed, p50 6.06 s p95 9.29 s per ticket |
| Split | 958 train / 240 test, shared by both students |

Both failures were truncated JSON: the teacher stopped mid-object while emitting a long
`rationale`, so the response was valid as far as it went but had no closing brace. That is an
output-length limit rather than a parser weakness, and dropping the two rows is the right
response, since a half-written judgement has no department to train on. Raising the teacher's
output cap would recover them if the loss ever mattered; at 2 rows in 1,179 it does not.

The teacher's own latency is the argument for distilling: 6 seconds per ticket is most of the
SRS budget for the entire pipeline, spent on triage alone.

### Teacher label distribution

```
general 483 | billing 366 | sales 217 | retention 77
technical_support 42 | network_operations 9 | field_service 4
```

Two things follow from this and both matter more than any headline accuracy.

**The telecom departments are nearly absent.** `network_operations` (9) and `field_service` (4)
have too few examples to learn or to evaluate. This is a property of the source corpus, not of
either model: Bitext is e-commerce and customer-service text, and the 928-row telecom supplement
is a small fraction of the sampled rows. Any macro-F1 quoted below is dominated by how these two
classes happen to fall in the split.

**The teacher agrees with the Bitext ground-truth department on 58.5% of rows.** That number is
not a teacher error rate, and reading it as one would be wrong. Bitext labels a text by its
surface intent; the teacher reads the fused payload, including audio and images, and is asked to
route to a telecom department that Bitext's taxonomy does not contain. Divergence is expected
where the payload carries evidence the original text did not. It does mean the teacher, not
Bitext, defines the target both students are trained against.

### The two students

Both trained on the identical 958/240 split.

| | fine-tuned DistilBERT | frozen MiniLM + logistic heads |
|---|---|---|
| department accuracy | see `models/artifacts/distilled_triage/config.json` | **0.838** |
| department macro-F1 | " | **0.711** |
| band accuracy | " | **0.854** |
| sentiment accuracy | " | **0.804** |
| latency per ticket | ~73 ms | **10.6 ms** (measured in-process: 22 ms) |
| training cost | minutes on CPU | **seconds**, embeddings cached |

The embedding baseline is the number to beat, and it is a strong one: 0.838 accuracy at 10.6 ms
from a frozen encoder and three linear heads that fit in seconds. Fine-tuning 66M parameters has
to earn its cost against that, and on a corpus this size and this skewed, it is not obvious that
it does.

### What these numbers do and do not show

- They measure **agreement with the teacher**, which is the correct metric for distillation but
  is not correctness in any absolute sense. Neither student can exceed its teacher on the
  judgement it is imitating.
- **Macro-F1 is the honest column**, not accuracy. With `general` and `billing` covering 71% of
  rows, a model that learned only those two would still post a respectable accuracy.
- **The telecom departments remain effectively untested.** Fixing that needs more telecom source
  text, not more training epochs.
- 132 multimodal rows out of 1,198 (11%) is still thin for claims about multimodal triage
  specifically.
