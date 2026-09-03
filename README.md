# Multimodal Customer Support Triage (v1)

Reference implementation of the system specified in `docs/SRS_G22.md` and `docs/SAD_G22.md`
(both in the parent `DSEP22/` folder). A customer submits a support ticket that may contain text,
a voice recording and photographs. The system converts every modality to text at the edge, fuses
them into one payload, classifies and prioritises it, retrieves relevant procedures, predicts a
fault, drafts a reply, and presents all of it to a human agent who decides what actually gets sent.

No reply ever reaches a customer without a human approving it. That is enforced in the database
schema, not just in policy: `delivery.approval_id` is `NOT NULL` and references an
`agent_decision` row, so an unapproved outbound message cannot be represented.

## Quick start

Two processes. Backend:

```bash
uv venv --python 3.12 .venv
uv pip install -e ".[dev]" --python .venv
$env:APP_PROFILE="stub"; .\.venv\Scripts\python.exe scripts\seed.py --reset
$env:APP_PROFILE="stub"; .\.venv\Scripts\python.exe -m runtime.local
   # http://localhost:8000
$env:APP_PROFILE="cpu"
$env:DATABASE_URL="sqlite+pysqlite:///C:/Users/USER/Desktop/dsep/v1/v1_data/app.db"
.\.venv\Scripts\python.exe -m runtime.local
```

Frontend:

```bash
cd frontend
npm install
npm run dev                                                        # http://127.0.0.1:5300
```

Sign in with `dev-agent-token`, `dev-lead-token` or `dev-admin-token`.

`APP_PROFILE=stub` needs no GPU, no Ollama and no network. Set `APP_PROFILE=cpu` with
`ollama serve` running for real models. Details in `docs/01-setup.md`.

Note that on `stub` a voice message is **not** transcribed unless a `.txt` sidecar exists next to
that audio. In the absence of real transcription data, the stub transcriber returns a neutral
placeholder instead of inventing a customer report. Use `cpu` whenever the output matters. To
bring up MLflow, Spark, Kafka and Postgres as well, see `docs/18-running-the-system.md`.

## Architecture

Twelve pipeline services communicate only through an event broker and the database. No service
imports another service, which is enforced mechanically by `tests/architecture/test_imports.py`
rather than by convention. The apparent pipeline order exists purely in the broker topology.

```
                    POST /api/v1/tickets
                            |
                            v
                     [intake_api]  writes ticket + attachments + outbox row
                            |
                       tickets.raw
                            |
                     [routing_svc]  registers the expected completion set
                     /      |      \
        tickets.audio  tickets.image  tickets.text
              |             |             |
        [audio_svc]    [image_svc]    [text_svc]
          Whisper      LLaVA / HSV    normalise, PII scan
              \             |             /
               \            |            /
                    [aggregator_svc]  fuses fragments, 120s window
                            |
                    tickets.aggregated   (UnifiedTicketPayload)
                            |
                      [triage_svc]  department + priority band
                            |
                      tickets.triaged
                            |
                  [orchestrator_svc]  retrieval -> LLM diagnosis
                            |          (dense vectors + knowledge graph)
                    tickets.diagnosed
                            |
                     [response_svc]  draft reply + action recommendation
                            |
                      tickets.ready
                       /         \
            [projector_svc]   WebSocket fan-out
                   |
            queue_projection  ---->  Agent workspace (React)
                                            |
                                     human approves
                                            |
                                   [delivery_gateway]  the only egress
```

### Layers

Dependencies point downward only. The domain layer depends on nothing but Pydantic.

| Layer | Location | Contents |
|---|---|---|
| Presentation | `frontend/` | React 18 + TypeScript agent workspace |
| API | `services/{intake_api,workspace_api,admin_api}` | FastAPI, role-based access |
| Pipeline | `services/*` | Twelve broker consumers, one responsibility each |
| Domain | `libs/domain` | Contracts, state machine, policies, ports. No I/O |
| Adapters | `libs/platform` | Model runtimes, broker, database, stores |
| Infrastructure | `libs/platform/{db,broker,objectstore,vector,graph}` | SQLite, in-process broker, filesystem, NumPy index |

### Ports and adapters

Every model and external system sits behind a port declared in `libs/domain/ports/`. Nothing
above that line names a vendor. This is what lets the entire pipeline run in CI in ten seconds
with no GPU: the `stub` profile swaps every adapter for a deterministic fake, and the same code
paths execute.

| Port | Real adapter | Fallback | Stub |
|---|---|---|---|
| `TranscriberPort` | faster-whisper | - | fixed transcript |
| `VisualExtractorPort` | LLaVA via Ollama | HSV heuristic LED reader | fixed summary |
| `TextGeneratorPort` | Ollama, OpenAI-compatible | - | canned JSON |
| `EmbedderPort` | sentence-transformers | - | hashing vectoriser |
| `ClassifierPort` | trained sklearn artifact | keyword rules | keyword rules |
| `EventBrokerPort` | Kafka | - | in-process threads |
| `VectorIndexPort` | NumPy index persisted to JSON | - | same |
| `GraphStorePort` | in-memory graph from YAML seed | - | same |

The degradation test suite kills each adapter in turn and asserts a ticket still reaches
`READY_FOR_AGENT` with the correct flags raised. Graceful degradation is a tested property here,
not an aspiration.

### Deviations from the SAD

v1 substitutes lighter infrastructure behind the same ports. Kafka becomes an in-process broker,
PostgreSQL becomes SQLite, Qdrant becomes a NumPy index, Neo4j becomes an in-memory graph, MinIO
becomes the local filesystem, vLLM becomes Ollama. Because all of it sits behind ports, no service
code changes when swapping back. Full table in `docs/02-architecture-mapping.md`.

## Data

The datasets are **not committed**. They total about 70 MB, which is not what git is for, and two
of the three are freely available from their original sources. `data/` is git-ignored apart from
`telecom_supplement.csv`, which is generated by this project and therefore tracked.

Set the folder up as follows.

```
data/
├── telecom_supplement.csv          tracked in git, nothing to do
├── raw/
│   ├── Bitext_Sample_Customer_Support_Training_Dataset_27K_responses-v11.csv
│   ├── router detection.v38-data_video.coco/
│   │   ├── train/  valid/  test/           each with _annotations.coco.json
│   └── archive/Call center data samples/   optional, ASR work only
└── processed/                      generated by notebook 01, do not create by hand
```

Then run `notebooks/01_data_preparation.ipynb`, which writes `data/processed/{train,val,test}.csv`.
Nothing else needs the raw files at runtime: the pipeline itself runs on seeded SOPs and the
`stub` profile, so you only need these to retrain or re-evaluate.

### 1. Bitext customer support (19 MB, required)

26,872 customer-support exchanges. Columns: `flags`, `instruction`, `category`, `intent`,
`response`. 11 categories, 27 intents. Trains the department and intent classifiers.

Source: <https://huggingface.co/datasets/bitext/Bitext-customer-support-llm-chatbot-training-dataset>
(Community Data License Agreement, Sharing, v1.0). Download the CSV and place it at the path above.

Two properties matter. The `instruction` and `response` fields contain templated slots such as
`{{Order Number}}`, which must be stripped or filled before training, or the model learns to key on
the braces. And the corpus contains **no telecommunications content at all**, so
`network_operations` and `field_service` are unlearnable from it. That is why
`data/telecom_supplement.csv` exists: 928 rows generated by
`scripts/generate_telecom_supplement.py` covering router faults, line sync failures, outages and
field visits. Without it the classifier silently never predicts two of the six departments.

### 2. Roboflow router detection v38 (39 MB, 2342 images, optional)

Needed only for notebook 05. Train 2137 images / 4630 boxes, valid 111 / 291, test 94 / 218.

Source: <https://universe.roboflow.com/router/router-detection> (CC BY 4.0). Export as **COCO**,
version 38 `data_video`, and unzip so that `train/`, `valid/` and `test/` sit directly inside the
folder named above.

The 16 categories are ports, cables and connectors: `{fiber, lan, phone, power, usb}` crossed with
`{cable, conn}`, plus a `router-detection` super-category. **There are no LED annotations.** This
was verified by reading the annotation files rather than assumed from the dataset name, and it
determines what the data is good for: it can train a port and cable detector ("the fiber connector
is not seated"), but it cannot train an LED-state reader. LED extraction therefore stays a VLM
prompt with the HSV heuristic as fallback. See `evaluation/datasets/roboflow_router.py`.

One trap: Roboflow generated three augmented variants per source image, so a naive split leaks
augmented copies of the same photograph across train and test. Group by the filename stem before
`.rf.` when splitting.

### 3. Call centre recordings (13 MB, optional)

Eleven real call-centre recordings as MP3 with DOCX transcripts, in English, Russian, Polish and
French. Used by notebook 06 for ASR latency and confidence-distribution work. The transcripts are
not word-aligned references, so they do not support a rigorous WER number.

These are not redistributable here. Substitute any small set of support-call recordings, or skip
notebook 06, which degrades to the synthetic sample audio in
`../ingestion-pipeline-prototype/data/sample_audio/`.

### Processed splits

Notebook 01 produces `train.csv` (21,825 rows), `val.csv` and `test.csv` (2,729 rows) from Bitext
plus the telecom supplement, stratified on department and intent.

Class balance is heavily skewed: `general` 9,558 rows against `field_service` 128. Report
macro-F1, never accuracy.
## Notebooks

Run them in order; each writes artefacts the next one and the pipeline consume. Several were
deliberately left unexecuted in this environment, and each says so at the top rather than shipping
a fabricated result.

| Notebook | Does | Produces |
|---|---|---|
| `01_data_preparation` | Extracts Bitext, strips template slots, maps 11 categories onto 6 departments, merges the telecom supplement, stratified 80/10/10 split | `data/processed/{train,val,test}.csv` |
| `02_department_classifier` | TF-IDF word and character n-grams, compares calibrated LinearSVC against logistic regression, checks probability calibration because the triage threshold consumes those confidences | `models/artifacts/department_clf.joblib` |
| `03_intent_and_diagnosis_llm` | Track A: few-shot prompting of `llama3.1:8b` through Ollama. Track B: QLoRA fine-tune, merge, GGUF conversion, `ollama create`. **Not executed here** (needs a GPU, a running Ollama and Hugging Face access to gated Llama weights) | LoRA adapter, GGUF, `Modelfile` |
| `04_priority_and_sentiment` | Calibrates the six priority weights by grid search against labelled band targets, maximising Cohen's kappa. The scoring policy stays code; only weights are data | `config/priority_weights.yaml` |
| `05_vlm_led_extraction` | Compares the HSV heuristic against LLaVA prompts for reading router panels. **Not executed here** (needs Ollama with `llava:7b`) | Tuned prompts, confidence threshold |
| `06_asr_evaluation` | faster-whisper across model sizes on the sample audio: latency per audio-minute, per-segment confidence distribution, threshold recommendation | Threshold recommendation, plot |
| `07_knowledge_and_graphrag` | Chunking strategies, embedding-model comparison, recall@5 and MRR over 40 question-to-chunk pairs, then dense-only against dense-plus-graph-expansion. This is the experiment that justifies the second store (ADR-007) | Chunking and embedding parameters |
| `08_end_to_end_evaluation` | Drives 100 synthetic multimodal tickets through the real pipeline via the same entrypoint `intake_api` uses, measuring per-stage latency and accuracy | `evaluation/reports/e2e_report.{json,csv,md}` |
| `09_unified_dataset` | Fuses Bitext text, real Whisper transcripts of minds14 telephony and router LED scenarios into `UnifiedTicketPayload`-shaped records, then asserts modality coherence and provenance spans | `data/processed/unified_dataset.jsonl` |
| `10_llm_triage_and_students` | Labels those payloads with a teacher LLM, then trains and compares two ways of serving that judgement cheaply: a fine-tuned DistilBERT and logistic heads on frozen sentence embeddings | `data/processed/distillation_dataset.jsonl`, `models/artifacts/{distilled,embedding}_triage/` |

### Performance metrics

Measured numbers as recorded by the notebooks in `evaluation/reports/metrics.jsonl` and the model
artifact configs. Read them together with the caveats in the next section: several are optimistic
for reasons that have nothing to do with the models.

**Department classification** (notebook 02, 2,729 test rows)

| Model | Val macro-F1 | Test macro-F1 |
|---|---|---|
| LinearSVC (calibrated) — selected | 1.000 | 1.000 |

**Triage students** (notebook 10, 958 train / 240 held-out payloads, teacher `gpt-oss:120b-cloud`)

| Model | Dept acc | Dept macro-F1 | Band acc | Sentiment acc | Latency |
|---|---|---|---|---|---|
| Frozen MiniLM-L6 embeddings + logistic heads | 0.838 | 0.711 | 0.854 | 0.804 | 70.4 ms |
| Fine-tuned DistilBERT | 0.796 | 0.423 | 0.846 | 0.817 | — |

The embedding heads win on every macro-averaged metric at a fraction of the training cost, which
is why they are the default served triage model. Accuracy here means agreement with the teacher.

**Retrieval** (notebook 07, 40 question-to-chunk pairs)

| Configuration | Recall@5 | MRR |
|---|---|---|
| `all-MiniLM-L6-v2` | 0.900 | 0.668 |
| `all-MiniLM-L12-v2` | 0.900 | 0.658 |

Fault identification over the same corpus: dense-only 1.000, dense plus graph expansion 0.857.
The graph store earns its place on multi-hop questions, not on this flat retrieval measure.

**ASR** (notebook 06, faster-whisper, 689.6 s of real telephony speech)

| Model size | Latency per audio-minute | Segments | Mean segment confidence |
|---|---|---|---|
| `tiny` | 2.62 s | 131 | 0.666 |
| `base` | 5.84 s | 221 | 0.675 |

Recommended low-confidence threshold 0.6. No WER: neither sample has a reference transcript.

**Priority calibration** (notebook 04): Cohen's kappa against labelled band targets improves from
0.646 with the default weights to 0.704 after grid search. Sentiment lexicon accuracy 0.75.

**End-to-end pipeline** (notebook 08, 100 synthetic multimodal tickets, `APP_PROFILE=stub`)

| Measure | Value |
|---|---|
| Tickets completed | 100 / 100, none timed out |
| Wall clock | 4.51 s |
| Throughput | 22.2 tickets/s |
| JSON validity rate | 1.000 |

| Stage | p50 | p95 | Mean |
|---|---|---|---|
| `PROCESSING` → `AGGREGATED` | 2,625 ms | 3,980 ms | 2,426 ms |
| `AGGREGATED` → `TRIAGED` | 118 ms | 363 ms | 150 ms |
| `TRIAGED` → `DIAGNOSED` | 97 ms | 431 ms | 159 ms |
| `DIAGNOSED` → `READY_FOR_AGENT` | 93 ms | 681 ms | 186 ms |

Ingestion dominates: it fans out ASR, vision and text processing before aggregation. The three
downstream stages together cost less than a fifth of it.

### Reading the numbers honestly

The saved classifier reports macro-F1 1.0. **Do not treat that as a real generalisation
estimate.** Two things inflate it: 289 of 2,660 test texts appear verbatim in the training split,
and Bitext phrasings are templated, so held-out rows are near-duplicates of training rows.
Deduplicate by text before splitting to get a trustworthy figure.

Likewise, `evaluation/reports/e2e_report.md` (git-ignored; regenerate it by running notebook 08)
was produced under `APP_PROFILE=stub`, where
`StubGenerator` returns one fixed diagnosis for every ticket and the rule-based classifier stands
in for the trained artifact. Its 0.590 department accuracy and 0.229 fault accuracy measure the
plumbing, not the models. Stage latencies from that run are meaningful; accuracy numbers are not.

The same caution applies to the triage models from notebook 10. Their reported accuracy is
**agreement with the teacher LLM**, which is the right metric for distillation but is not
correctness in an absolute sense, since neither student can exceed the teacher it imitates. Read
macro-F1 rather than accuracy: `general` and `billing` cover 71% of teacher labels, so a model
that learned only those two would still post a respectable accuracy. And `network_operations` (9
rows) and `field_service` (4 rows) are too rare in the corpus to be either learned or evaluated,
which is a property of the source data rather than of the models. See
`docs/17-llm-triage-distillation.md`.

## Testing

```bash
APP_PROFILE=stub .venv/Scripts/python.exe -m pytest       # 47 tests, about 11 seconds
```

| Suite | Checks |
|---|---|
| `tests/unit` | Domain policies, state machine, payload validation, provenance spans |
| `tests/integration` | Full pipeline under the stub profile, ticket in to `READY_FOR_AGENT` out |
| `tests/architecture` | No service imports another; each table has exactly one writer |
| `tests/degradation` | Every model adapter forced to fail; ticket must still arrive with correct flags |

## Layout

```
config/          profiles, routing rules, action registry, seed SOPs and graph
data/            raw datasets, processed splits, telecom supplement
docs/            setup, architecture mapping, per-model writeups, operations, troubleshooting
evaluation/      dataset loaders, harness, metrics, reports
frontend/        React 18 + TypeScript agent workspace
libs/domain/     contracts, enums, state machine, policies, ports. No I/O
libs/platform/   adapters: models, broker, database, object store, vector, graph
migrations/      forward-only SQL
models/          prompt templates and trained artefacts
notebooks/       the eight training and evaluation notebooks above
runtime/         service wiring, local single-process runner, demo driver
scripts/         seeding, migration generation, data generation
services/        the sixteen services
tests/           unit, integration, architecture, degradation
```

## Documentation

Start with `docs/01-setup.md`. `docs/18-running-the-system.md` brings up every tier at once,
including the Docker infrastructure, and records the failures that occur when you do.
`docs/02-architecture-mapping.md` maps each SAD element to its v1 module and lists every
deviation. `docs/14-ui.md` covers the agent workspace. `docs/11-troubleshooting.md` is a
symptom-to-cause table for the failures this stack actually produces.

## Status

The pipeline runs end to end, the agent workspace is complete against SRS UI-1 through UI-7, and
42 tests pass. Known limitations are recorded in `docs/14-ui.md` section 6 and
`docs/08-evaluation.md`: authentication is a static-token stand-in rather than an identity
provider, routing rules and thresholds are read-only at runtime, historical ticket import is not
built, and the LLM fine-tune has not been run in this environment.
