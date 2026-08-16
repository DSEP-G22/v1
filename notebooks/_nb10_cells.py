"""Cell definitions for notebooks/10_llm_triage_and_students.ipynb, applied by _build_notebooks.py.

Kept as a Python file so the notebook is reviewable in a diff and regenerable, rather than being
edited as raw JSON.
"""

CELLS = [
    ("markdown", """# 10. LLM triage, and two ways to make it cheap

**Inputs:** `data/processed/unified_dataset.jsonl` from notebook 09.

**Outputs:** `data/processed/distillation_dataset.jsonl` (teacher judgements), plus two trained
triage artefacts and the measurements needed to choose between them.

**The problem.** A large language model reading the fused payload triages well and explains
itself, but costs seconds per ticket. The SRS budget allows a few seconds for the *whole*
pipeline, so the teacher cannot sit on the hot path. Two ways to get its judgement cheaply:

```
                         unified payload
                               |
                        TEACHER LLM  (gpt-oss:120b, seconds per ticket)
                               |
                     teacher judgements on disk
                        /                  \\
        A: fine-tune DistilBERT      B: frozen embeddings + logistic heads
           66M params, minutes          no training of the encoder, seconds
```

Both learn from the same teacher on the same split, so the comparison isolates the approach."""),

    ("markdown", """## The teacher

`gpt-oss:120b-cloud` through Ollama. The original plan was a local `llama3.1:8b-instruct-q4_K_M`,
but the pull failed repeatedly on this connection: the 8B stalled around 20%, a 3B retry restarted
from zero, and a 0.5B attempt died with `net/http: TLS handshake timeout`. An Ollama cloud model
needs no download and runs on the same `/api/chat` endpoint, so the switch is one flag and nothing
else in the pipeline changes.

Three instructions in `models/prompts/llm/triage.txt` carry most of the weight:

- **treat audio as less reliable than typed text**, because it is a machine transcript, and
  without this the model weights an ASR error as heavily as something the customer typed;
- **prefer the image for hardware state when it contradicts the text**, because a photograph of a
  panel is direct evidence while a customer's description of it is a report;
- **when evidence is thin, choose the safer option**, because a confident wrong department sends
  the ticket to a queue that cannot resolve it, which is worse than an honest `general`."""),

    ("code", """from mlops.llm_triage_labeller import PROMPT_PATH, call_teacher, validate

TEACHER = "gpt-oss:120b-cloud"
prompt = PROMPT_PATH.read_text(encoding="utf-8")
print(prompt[:900])"""),

    ("code", """import json
from pathlib import Path

unified = [json.loads(line) for line in
           Path("data/processed/unified_dataset.jsonl").read_text(encoding="utf-8").splitlines()
           if line.strip()]

# One live teacher call on a multimodal payload, so the notebook shows the teacher reasoning over
# more than one modality rather than only reporting cached output.
example = next(r for r in unified if r["metadata"]["is_multimodal"])
print(example["fused_text"][:300])
print("-" * 78)

try:
    label, latency, _ = call_teacher("http://localhost:11434", TEACHER, prompt,
                                     example["fused_text"], timeout=120)
    print(f"latency {latency:.1f}s | valid: {validate(label)}")
    print(json.dumps(label, indent=2))
except Exception as exc:
    print(f"teacher unreachable ({type(exc).__name__}); showing a cached judgement instead")
    label = None"""),

    ("markdown", """### Validation, and why bad labels are dropped rather than repaired

Every teacher judgement is checked before it enters the dataset: the department must be one of the
seven, the band one of the four, the confidences in range. A teacher that hallucinates a class
outside the taxonomy produces a label the routing layer cannot act on, and a student trained on it
would learn to emit a department that no queue exists for. Rejecting the row is cheaper than
teaching that.

The labeller is resumable and flushes after every row, because a run over a thousand tickets will
be interrupted."""),

    ("code", """# Throughput. The teacher is a network call, so the run is latency-bound, not CPU-bound, and
# parallelises. Measured: 4.5 s/row sequentially against 2.2 s/row at 4 workers.
#
# Concurrency is capped at 4 deliberately. At 8 workers the cloud endpoint began refusing roughly
# a third of requests, so more workers produced fewer labels, not more.
#
#     python -m mlops.llm_triage_labeller --limit 1200 --workers 4

labelled = [json.loads(line) for line in
            Path("data/processed/distillation_dataset.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]

import statistics
from collections import Counter

print(f"teacher-labelled: {len(labelled)}")
print(f"teacher model:    {labelled[0]['teacher_model']}")
print(f"median latency:   {statistics.median(r['teacher_latency_s'] for r in labelled):.2f}s per ticket")
print()
print("teacher departments:", dict(Counter(r["teacher_label"]["department"] for r in labelled).most_common()))
print("teacher bands:      ", dict(Counter(r["teacher_label"]["priority_band"] for r in labelled).most_common()))"""),

    ("markdown", """### Does the teacher agree with the Bitext ground truth?

Worth checking, but worth interpreting carefully. Disagreement is not automatically teacher error.
Bitext labels a *text* by its surface intent; the teacher reads the fused payload including audio
and images, and is asked to route to a department. Where a payload carries evidence the original
text did not, the teacher is expected to diverge, and that divergence is the multimodal signal the
whole system exists to capture."""),

    ("code", """agree = sum(1 for r in labelled
            if r["ground_truth"].get("department") == r["teacher_label"]["department"])
print(f"teacher vs Bitext ground truth: {agree}/{len(labelled)} = {agree / len(labelled):.1%}")

multimodal = [r for r in labelled if r["is_multimodal"]]
if multimodal:
    mm_agree = sum(1 for r in multimodal
                   if r["ground_truth"].get("department") == r["teacher_label"]["department"])
    print(f"  on multimodal rows only:      {mm_agree}/{len(multimodal)} = {mm_agree / len(multimodal):.1%}")
    print("  (lower agreement here is expected: these payloads carry evidence the text alone "
          "did not)")

confidences = [r["teacher_label"]["department_confidence"] for r in labelled]
print(f"\\nteacher confidence: median {statistics.median(confidences):.2f} "
      f"| below 0.6: {sum(c < 0.6 for c in confidences)}")"""),

    ("markdown", """## Approach A, fine-tuned DistilBERT

One encoder, three heads: department, priority band, sentiment. Sharing the encoder is deliberate.
All three judgements draw on the same evidence, one encoder is cheaper than three, and multi-task
training regularises each head against the others.

Two signals are learned from, and the second is what makes this distillation rather than ordinary
supervised training:

1. the teacher's hard label, as cross-entropy;
2. the teacher's stated confidence, as a per-example weight, so a ticket the teacher was unsure
   about contributes less than one it was certain of.

Department is weighted 2.0 against 1.0 for band and 0.5 for sentiment, because the department is
the decision the routing layer acts on and a wrong one misroutes the ticket.

**A limitation worth stating plainly.** True distillation trains against the teacher's full output
distribution, not just its top choice. Ollama's chat API exposes no per-class probabilities, so the
stated confidence is the strongest soft signal available. This is weaker than a KL divergence
against teacher logits; serving the teacher through vLLM, which can return logprobs, would allow
the stronger form.

```bash
python -m mlops.train_distilled_triage --epochs 3 --register
```"""),

    ("markdown", """## Approach B, frozen embeddings with linear heads

Encode each payload once with a frozen sentence-transformer, then fit logistic regression on the
resulting 384-d vector.

```
fused_text -> [frozen MiniLM] -> 384-d vector -> LogisticRegression x3
```

Why it earns its place next to a fine-tuned transformer:

- **it trains in seconds on CPU**, and embeddings are cached, so re-fitting after new agent
  corrections is nearly free, which is what the continuous-learning loop needs;
- **it is the baseline that makes approach A's number mean something.** Fine-tuning 66M parameters
  is only worth its cost if it beats a linear model on frozen features. Without this figure, "0.85"
  cannot be called good or bad;
- **it adds no new model to the deployment**, because the same encoder already serves retrieval.

The trade-off: the encoder never adapts to the domain. It cannot learn that `[AUDIO:...]` marks
lower-trust evidence, or what a DSL sync failure is, because its weights are frozen. Closing that
gap is exactly what fine-tuning is for, and the comparison below measures whether it does.

`class_weight="balanced"` is set on each head, because the department distribution is heavily
skewed towards `general` and `billing`, and an unweighted linear model on skewed data collapses
onto the majority class while still reporting a respectable accuracy.

```bash
python -m mlops.train_embedding_triage --register
```"""),

    ("markdown", """## Comparing them fairly

Both trainers call `split_dataset(rows, test_fraction, seed)`, which sorts by `ticket_id` before
shuffling. The split is therefore identical for both, and the comparison measures the approach
rather than the luck of the draw. Comparing two models across two different random splits would
measure the split as much as the model."""),

    ("code", """import json
from pathlib import Path

results = {}
for name, path in (("distilled (fine-tuned)", "models/artifacts/distilled_triage/config.json"),
                   ("embedding (frozen)", "models/artifacts/embedding_triage/config.json")):
    config_path = Path(path)
    if config_path.exists():
        results[name] = json.loads(config_path.read_text(encoding="utf-8"))["metrics"]
    else:
        print(f"{path} not found; run its trainer first")

if results:
    keys = ["department_accuracy", "department_macro_f1", "band_accuracy", "sentiment_accuracy"]
    header = f"{'metric':<24}" + "".join(f"{n:>24}" for n in results)
    print(header)
    print("-" * len(header))
    for key in keys:
        row = f"{key:<24}"
        for metrics in results.values():
            value = metrics.get(key)
            row += f"{value:>24.3f}" if isinstance(value, (int, float)) else f"{'-':>24}"
        print(row)"""),

    ("markdown", """### Reading the comparison

**Macro-F1 matters more than accuracy here.** The department distribution is skewed, so a model
that learns only `general` and `billing` still posts a decent accuracy. Macro-F1 weights every
department equally and exposes that. `network_operations` and `field_service` are the smallest
classes and the ones the telecom supplement exists to make learnable at all.

**Latency is not the whole cost.** The embedding approach pays a sentence-transformer forward pass
per ticket, so its per-ticket latency is not dramatically below a distilled DistilBERT's. Its real
advantage is training cost, which is what the continuous-learning loop pays repeatedly.

**Whichever wins, the teacher stays the ceiling.** Both students are trained to reproduce the
teacher, so neither can exceed it on the judgement being imitated. Reported accuracy is agreement
with the teacher, not correctness in an absolute sense."""),

    ("code", """# Both adapters behind the same port, so triage_svc is indifferent to which one is deployed.
from pathlib import Path

from libs.platform.models.triage import DistilledTriageModel, EmbeddingTriageModel

sample = next(r for r in unified if r["metadata"]["is_multimodal"])["fused_text"]

for name, model in (
    ("distilled", DistilledTriageModel(Path("models/artifacts/distilled_triage"))),
    ("embedding", EmbeddingTriageModel(Path("models/artifacts/embedding_triage"),
                                       "sentence-transformers/all-MiniLM-L6-v2")),
):
    judgement = model.triage(sample)
    print(f"{name:10s} -> {judgement.department.value:20s} "
          f"conf={judgement.department_confidence:.3f} band={judgement.priority_band.value} "
          f"({judgement.model_version})")"""),

    ("markdown", """## Deploying one

```bash
# .env
TRIAGE_MODEL_IMPL=distilled     # or: embedding | llm | none
```

Three properties hold regardless of which adapter runs, and they are the reason the port exists:

- **routing rules still override the model**, because an operator-authored rule is policy and
  policy beats a prediction (ADR-010);
- **priority signals still come from the deterministic policy**, so the workspace can always show
  why a score was assigned even when a model assigned it;
- **every adapter degrades to rules rather than raising**, because a triage failure must leave the
  ticket reaching an agent flagged, never stranded.

`triage_result` records `model_version` and `rationale`, so any historical triage can be attributed
to the model that produced it."""),
]
