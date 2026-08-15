# v1 Implementation Plan

Reference implementation of the system specified in `docs/SRS_G22.md` and `docs/SAD_G22.md`,
built under `d:\DSEP22\v1`. This plan is written to be executed step by step by an
implementer (human or model) without re-reading the whole SAD. Every step states the files to
create, the exact contracts, the acceptance check, and the failure modes to expect.

Source-of-truth documents:

- `docs/SAD_G22.md` §5.2.1 (domain classes), §5.2.2 (service/table ownership), §5.2.3 (ports and
  adapters), §6.4 (topics), §6.5 (aggregation window), §8.2.1 (source tree), §9.2 (database), §9.5
  (graph schema)
- `docs/SRS_G22.md` §4.1-4.12 (functional requirements REQ-*), Appendix B.5 (payload instance)
- `docs/Appendix_C-technology-stack.md` (allowed technologies)

Deviations from the SAD that v1 deliberately makes (record these in `v1/docs/02-architecture-mapping.md`):

| SAD element | v1 substitute | Reason |
|---|---|---|
| Kafka | in-process broker by default, Kafka adapter behind the same port | single-host demo, CI without Docker |
| PostgreSQL 16 | SQLAlchemy 2 over SQLite by default, Postgres by URL | zero-setup dev; same ORM code |
| Qdrant | in-memory NumPy index persisted to JSON | small corpus (<10k chunks) |
| Neo4j | in-memory graph loaded from a YAML seed | graph is ~200 nodes in the demo |
| vLLM | **Ollama** (explicit instruction for v1) | local, no GPU-only requirement |
| MinIO | local filesystem object store | same `ObjectStorePort` |
| (not in SAD) | **MLflow** tracking + model registry as the single source of trained artefacts | SAD Appendix C already lists MLflow for experiment tracking; v1 extends it to be the *serving* source so notebooks and runtime never disagree about which checkpoint is live |
| Response Generation Service as a single LLM call | **Agentic loop** (tool-calling planner) behind the same `tickets.diagnosed → tickets.ready` contract | requested for v1; the service's inputs, outputs, tables, and the human-in-the-loop gate are unchanged, so the architecture is untouched |

Everything above sits behind the ports of SAD §5.2.3, so none of it changes service code.

### What is actually in `d:\DSEP22\data\` (verified)

| File | Contents | What it can and cannot train |
|---|---|---|
| `Bitext_Sample_Customer_Support_Training_Dataset_27K_responses-v11.csv.zip` | one CSV, ~19 MB, 27k rows, columns `flags, instruction, category, intent, response`; 11 categories, 27 intents; `instruction`/`response` contain templated slots such as `{{Order Number}}`; `flags` encodes language-variation tags (B basic, Q colloquial, Z noise, and so on) | **Can** train: department classifier, intent classifier, reply-drafting style, sentiment/politeness cues. **Cannot** cover: telecom faults, network operations, field service, there is not one telecom row in it. A telecom supplement is mandatory (§9, notebook 01). |
| `router detection.v38-data_video.coco.zip` | 2350 files, COCO format, `train/` 2137 images 4630 boxes, `valid/` 111 images 291 boxes, `test/` 94 images 218 boxes. 16 categories: `router-detection` (super-category), `fiber-cable, fiber-conn, fibers, lan-cable, lans, lans-conn, phone, phone-cable, phone-conn, power, power-cable, power-conn, usb, usb-cable, usb-conn`. Images resized to 516×516, 3 augmented versions per source image | **Can** train: a **port and cable detector**, which ports exist on the unit and which cables are connected. This is genuinely useful evidence ("customer says no internet; the WAN/fiber connector is not seated"). **Cannot** train an LED-state reader, there are no LED annotations at all. LED reading therefore stays a VLM prompt plus the heuristic HSV extractor, evaluated on a small hand-labelled subset drawn from these same images. |

This changes two things versus the earlier draft: the vision notebook trains a **detector over ports
and cables** rather than an LED classifier, and `ExtractedFields` gains a `connectivity` block so
detector output has somewhere to live in the contract.

---

## 0. Prerequisites

1. Python 3.11+ (`python --version`). 3.13 also works but `faster-whisper` wheels can lag; if
   installation fails, fall back to 3.11.
2. Ollama installed and running: `ollama serve` (default `http://localhost:11434`).
   Pull models: `ollama pull llama3.1:8b-instruct-q4_K_M` and `ollama pull llava:7b`.
   Verify: `curl http://localhost:11434/api/tags`.
3. The two datasets stay zipped where they are (`d:\DSEP22\data\`, referenced as `../data` from
   `v1/`); notebook 01 extracts them to `v1/data/raw/` (git-ignored). Never copy the zips into `v1/`.
4. MLflow: `pip install mlflow` then `mlflow server --host 127.0.0.1 --port 5000
   --backend-store-uri sqlite:///v1_data/mlflow.db --artifacts-destination ./v1_data/mlruns`.
   Verify at `http://127.0.0.1:5000`. All notebooks log to `MLFLOW_TRACKING_URI=http://127.0.0.1:5000`.
5. Work from `d:\DSEP22\v1` as the working directory for every command below.

---

## 1. Repository scaffold

Create this tree (mirrors SAD §8.2.1; `frontend/` is out of scope for v1):

```
v1/
├── pyproject.toml
├── README.md
├── .env.example
├── .gitignore
├── Makefile                       # optional; on Windows use tasks.ps1
├── config/
│   ├── settings.yaml              # profile definitions: stub | cpu | full
│   ├── registry.yaml              # active model version per role
│   ├── routing_rules.yaml
│   ├── action_registry.yaml
│   └── seed/
│       ├── knowledge/*.md         # 6-10 SOP documents
│       └── graph_seed.yaml
├── libs/
│   ├── domain/{contracts,policy,ports,state}
│   ├── platform/{broker,db,objectstore,models,vector,graph}
│   ├── observability/
│   └── testing/
├── services/
│   ├── intake_api/ routing_svc/ audio_svc/ image_svc/ text_svc/
│   ├── aggregator_svc/ triage_svc/ retrieval_svc/ orchestrator_svc/
│   ├── response_svc/ action_svc/ delivery_gateway/ projector_svc/
│   ├── knowledge_ingest/ workspace_api/ admin_api/
├── runtime/                       # process wiring, local single-process runner
├── models/
│   ├── prompts/vlm/*.txt
│   ├── prompts/llm/*.txt
│   └── artifacts/                 # trained sklearn models, LoRA adapters (git-ignored)
├── evaluation/{harness,datasets,reports}
├── notebooks/
├── migrations/
├── tests/
└── docs/
```

`pyproject.toml`, package discovery over `libs*`, `services*`, `runtime*`, `evaluation*`;
`requires-python = ">=3.11"`.

Dependency groups (keep the base install small so CI needs no ML wheels):

- base: `pydantic>=2.6`, `pydantic-settings>=2.2`, `fastapi`, `uvicorn[standard]`,
  `python-multipart`, `SQLAlchemy>=2.0`, `httpx`, `PyYAML`, `numpy`, `python-ulid`
- `[ml]`: `scikit-learn`, `joblib`, `sentence-transformers`, `faster-whisper`, `Pillow`, `pandas`
- `[train]`: `datasets`, `transformers`, `peft`, `accelerate`, `torch`, `jupyter`, `jiwer`,
  `matplotlib`
- `[kafka]`: `confluent-kafka`
- `[dev]`: `pytest`, `pytest-asyncio`, `ruff`, `mypy`

Install: `pip install -e ".[dev]"` first; add `[ml]`/`[train]` only when reaching steps 9 and 11.

**Acceptance:** `python -c "import libs.domain"` succeeds from `v1/`.

**Pitfalls**
- `libs` and `services` are namespace-ish top-level packages. Every directory needs
  `__init__.py`, otherwise `pip install -e .` will not discover them and imports work from the
  source dir but break in tests run from elsewhere.
- Do not name any module `types.py`, `queue.py`, `logging.py`, or `json.py` at top level of a
  package that also does `import logging`, shadowing causes confusing `AttributeError` at import.

---

## 2. Configuration layer (`libs/platform/config.py`)

One `Settings` class (pydantic-settings) reading `.env` + `config/settings.yaml`, with an
`APP_PROFILE` of `stub | cpu | full`.

Fields (with defaults):

```
profile: str = "cpu"
database_url: str = "sqlite+pysqlite:///./v1_data/app.db"
object_store_root: Path = "./v1_data/objects"
broker: str = "inprocess"            # inprocess | kafka
kafka_bootstrap: str = "localhost:9092"
ollama_base_url: str = "http://localhost:11434"
llm_model: str = "llama3.1:8b-instruct-q4_K_M"
vlm_model: str = "llava:7b"
llm_timeout_s: float = 60.0
llm_num_ctx: int = 8192
asr_impl: str = "faster_whisper"     # faster_whisper | stub
asr_model: str = "base"
vlm_impl: str = "ollama"             # ollama | heuristic | stub
llm_impl: str = "ollama"             # ollama | stub
embedder_impl: str = "sentence_transformers"  # | hash_stub
embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
classifier_path: Path = "./models/artifacts/department_clf.joblib"   # fallback if MLflow is down
vector_store_path: Path = "./v1_data/vectors.json"

# MLflow, the source of truth for every trained artefact
mlflow_tracking_uri: str = "http://127.0.0.1:5000"
mlflow_enabled: bool = True
model_source: str = "mlflow"          # mlflow | local | stub
mlflow_models: dict[str, str] = {     # role -> registry URI
    "department_clf": "models:/cst-department-classifier@champion",
    "sentiment_clf":  "models:/cst-sentiment-classifier@champion",
    "port_detector":  "models:/cst-port-detector@champion",
    "embedder":       "models:/cst-embedder@champion",
}

# Agentic response generation
agent_enabled: bool = True
agent_max_steps: int = 6
agent_step_timeout_s: float = 45.0
agent_total_budget_s: float = 150.0
agent_tool_allowlist: list[str] = [...]   # see §5.10
aggregation_window_s: int = 120
asr_low_confidence_threshold: float = 0.60
vlm_low_confidence_threshold: float = 0.55
diagnosis_min_confidence: float = 0.45
max_retries: int = 3
```

The `stub` profile forces every `*_impl` to a stub. This is the CI profile of SAD §8.2.3.

**Acceptance:** `APP_PROFILE=stub python -c "from libs.platform.config import get_settings; print(get_settings().llm_impl)"` prints `stub`.

---

## 3. Domain layer (`libs/domain`), no I/O, no third-party imports except Pydantic

### 3.1 `enums.py`
`Modality(text|audio|image)`, `Channel(web_portal|email|phone|chat)`,
`TicketState(RECEIVED|PROCESSING|AGGREGATED|TRIAGED|DIAGNOSED|READY_FOR_AGENT|IN_REVIEW|AWAITING_APPROVAL|RESOLVED|CLOSED|FAILED)`,
`AttachmentStatus`, `Department(technical_support|billing|network_operations|field_service|sales|retention|general)`,
`PriorityBand(critical|high|normal|low)`, `Sentiment(angry|frustrated|neutral|satisfied)`,
`DecisionType(APPROVE_SEND|EDIT|REJECT|REASSIGN|ESCALATE|EXECUTE_ACTION)`,
`ExecutionStatus`, `DeliveryStatus`, `FlagCode` (string enum: `PARTIAL_PAYLOAD`,
`LOW_ASR_CONFIDENCE`, `LOW_VLM_CONFIDENCE`, `LLM_UNAVAILABLE`, `RETRIEVAL_EMPTY`,
`UNVERIFIED_CITATION`, `PII_DETECTED`, `NO_DRAFT`).

### 3.2 `contracts/`
Frozen Pydantic models, `model_config = ConfigDict(frozen=True)`:

- `media.py`: `Segment(start_s, end_s, text, confidence)`,
  `AudioTranscript(attachment_id, text, segments[], language, duration_s, acoustic_sentiment,
  confidence, low_confidence, model_version)`,
  `LedState(label, colour, behaviour)`,
  `PortObservation(port_type: usb|lan|phone|power|fiber, connected: bool, confidence, bbox)`,
  `ExtractedFields(device_model|None, led_states[], ports[], error_codes[], numeric_values{})`
, `ports[]` is filled by the trained detector of notebook 05 and is what makes the Roboflow
  dataset useful downstream; the graph gains `PortState -EVIDENCE_FOR-> Symptom` edges to match,
  `VisualSummary(attachment_id, prompt_template, summary_text, extracted_fields, confidence,
  low_confidence, model_version)`
- `payload.py`: `Provenance(modality, source, span: tuple[int,int], confidence, model_version|None)`,
  `UnifiedTicketPayload` with **exactly** the field names of SRS Appendix B.5:
  `schema_version="1.0.0"`, `ticket_id`, `customer_id`, `channel`, `created_at`, `original_text`,
  `transcripts[]`, `visual_summaries[]`, `fused_text`, `provenance[]`, `flags[]`, `partial`,
  `metadata{}`, plus `revision: int`. Add `validate_payload()` raising `PayloadInvalid` when
  `fused_text` is empty, spans overlap, or a span exceeds `len(fused_text)`.
- `analysis.py`: `TriageResult`, `Citation`, `Diagnosis`, `PolicyFinding`, `DraftResponse`,
  `ActionRecommendation`, fields exactly as SAD Figure 4.
- `events.py`: `EventEnvelope(schema_version, event_id, ticket_id, occurred_at, stage, body: dict)`
  and a `Topics` constant class holding the eleven topics of SAD Figure 9:
  `tickets.raw`, `tickets.audio.work`, `tickets.image.work`, `tickets.text.work`,
  `tickets.audio.done`, `tickets.image.done`, `tickets.text.done`, `tickets.aggregated`,
  `tickets.triaged`, `tickets.diagnosed`, `tickets.ready`, `tickets.dlq`.

### 3.3 `state/machine.py`
`ALLOWED: dict[TicketState, set[TicketState]]` plus
`transition(current, target) -> TicketState` raising `IllegalTransition`. Every state may go to
`FAILED`. Pure function; no persistence.

### 3.4 `policy/`
All pure functions over domain types, this is where the 85 % coverage gate applies.

- `priority.py::score(triage_inputs) -> (score:int 0..100, band, signals[])`.
  Weighted sum, weights loaded as a plain dict argument (never read config inside the domain):
  sentiment 25, urgency keywords 20, customer segment 15, outage scope 20, prior contacts 10,
  SLA age 10. Clamp to 0-100. Band thresholds: ≥80 critical, ≥60 high, ≥35 normal, else low.
- `routing.py::evaluate(rules, triage_result) -> Department`, first matching rule wins, else the
  classifier's department.
- `action_selection.py::select(fault, registry_entries, params) -> ActionRecommendation|None`,
  must return `None` if no `ActionRegistryEntry.permits(params)`.
- `compliance.py::check(draft_text, policy_rules) -> list[PolicyFinding]`, regex-based checks for
  promises of refunds/credits, absolute guarantees, missing greeting, PII echo.
- `fusion.py::fuse(original_text, transcripts, visual_summaries) -> (fused_text, provenance[])`,
  the only place fused text is built. Format each fragment as
  `[CUSTOMER_TEXT] …`, `[AUDIO:{attachment_id}] …`, `[IMAGE:{attachment_id}] …`, joined by `\n\n`,
  and compute spans with a running offset so provenance spans are exact character offsets.

### 3.5 `ports/`
`Protocol` classes (PEP 544), one file each, no implementations:
`TranscriberPort.transcribe(audio_path, attachment_id) -> AudioTranscript`;
`VisualExtractorPort.extract(image_path, attachment_id, template) -> VisualSummary`;
`TextGeneratorPort.generate(prompt, system=None, json_schema=None, **opts) -> str`;
`EmbedderPort.embed(texts: list[str]) -> list[list[float]]`;
`ClassifierPort.classify(text) -> (Department, confidence, alternatives)`;
`VectorIndexPort.upsert/query/delete_by_doc`;
`GraphStorePort.expand(seed_terms, hops) -> Subgraph`;
`ObjectStorePort.put/get/signed_url`;
`EventBrokerPort.produce(topic, key, envelope)/subscribe(topic, group, handler)/start/stop`;
`ActionAdapterPort.execute(action_id, params, idempotency_key) -> ExecutionResult`;
`MailGatewayPort.send(to, subject, body) -> str`.

**Acceptance for step 3:** `pytest tests/unit/test_policy_*.py` passes with no adapter imported;
`mypy --strict libs/domain` is clean.

**Pitfalls**
- Frozen models plus `datetime` defaults: use `Field(default_factory=lambda: datetime.now(timezone.utc))`,
  never a bare `datetime.utcnow()` default (shared mutable default + naive tz).
- Provenance spans drift if `fuse()` builds the string by one path and computes offsets by another.
  Build the list of fragments once, then `"\n\n".join`, accumulating `offset += len(fragment) + 2`.
  Add a unit test asserting `fused_text[span[0]:span[1]]` equals the fragment for every entry.

---

## 4. Platform layer (`libs/platform`)

### 4.1 Broker (`broker/`)
- `inprocess.py`: `InProcessBroker`, dict of topic → list of `(group, handler)`, a
  `queue.Queue` per group, worker threads, `produce()` appends, at-least-once semantics simulated by
  re-delivering on handler exception up to `max_retries`, then producing to `tickets.dlq` with the
  error context. Must preserve per-`ticket_id` ordering: hash the key to one of N worker lanes.
- `kafka.py`: `KafkaBroker` implementing the same port with `confluent-kafka`; commit offsets only
  after the handler returns (SAD §6.4).
- `factory.py`: `build_broker(settings)`.

### 4.2 Database (`db/`)
- `models.py`: SQLAlchemy 2 declarative ORM for the tables of SAD §9.2. Minimum set for v1:
  `organization, customer, ticket, attachment, audio_transcript, visual_summary, unified_payload,
  triage_result, diagnosis, citation, draft_response, action_recommendation, action_execution,
  agent_decision, delivery, audit_record, outbox, queue_projection, knowledge_document,
  knowledge_chunk, action_registry_entry, app_user, config_version, aggregation_state,
  ticket_state_transition`.
  Constraints that must be present because the architecture depends on them:
  `delivery.approval_id` FK **NOT NULL** to `agent_decision`;
  unique `(ticket_id, revision)` on `unified_payload`;
  unique `(attachment_id, model_version)` on `audio_transcript`;
  unique `(ticket_id, action_id, parameters_hash)` on `action_execution`;
  partial unique `(org_id, idempotency_key)` on `ticket`;
  CHECK `priority_score BETWEEN 0 AND 100`.
- `session.py`: engine + `session_scope()` context manager. For SQLite set
  `PRAGMA journal_mode=WAL` and `check_same_thread=False`.
- `repositories.py`: one repository class per aggregate; **enforce the single-writer rule of SAD
  §5.2.2 by convention and a test**, `tests/architecture/test_single_writer.py` greps each service
  package for repository write calls it does not own.
- `outbox.py`: `enqueue(session, topic, key, payload)` writing in the same transaction as the state
  change, plus `drain(broker)` publishing rows where `published_at IS NULL` and stamping them.

### 4.3 Object store (`objectstore/local.py`, `s3.py`)
Local: content-addressed path `{root}/{org}/{yyyy}/{mm}/{sha256}{ext}`; `signed_url` returns a
`file://` path in dev.

### 4.4 Model adapters (`models/`)
- `asr.py`: `FasterWhisperTranscriber` (segment-level `avg_logprob → exp()` as confidence, mean
  weighted by duration; `low_confidence = conf < threshold`; naive acoustic sentiment from
  keyword+prosody proxy) and `StubTranscriber` returning a fixed transcript from a sidecar
  `.txt` file next to the audio if present.
- `vlm.py`:
  - `OllamaVisionExtractor`, POST `/api/generate` with `images: [base64]`, `format: "json"`, the
    prompt template from `models/prompts/vlm/{template}.txt`, then parse to `ExtractedFields`.
  - `HeuristicLedExtractor`, port of the prototype's `image_ingest._run_vlm`: HSV masking for
    red/green/amber blobs, row clustering to guess LED labels. Kept as the R1 fallback.
  - `StubExtractor`.
  - Template selection helper `choose_template(filename, hint) -> router_led_panel | speed_test |
    error_screen | generic`.
- `llm.py`: `OllamaGenerator` implementing `TextGeneratorPort` via
  `POST {base}/api/chat` with `{"model":…, "messages":[…], "stream": false, "format": "json"|None,
  "options": {"temperature":0.2, "num_ctx": …}}`. Add:
  - a bounded semaphore (`max_in_flight`, default 2), ADR-012 bounded WIP;
  - retry with exponential backoff + jitter, 3 attempts;
  - a circuit breaker (open after 5 consecutive failures, half-open after 30 s);
  - `generate_json(prompt, schema)` that validates against a Pydantic model and, on failure, does
    **one** repair call using `models/prompts/llm/repair.txt`, then gives up and raises
    `GenerationInvalid`.
  - `StubGenerator` returning deterministic canned JSON keyed by prompt kind (used by CI).
- `embedder.py`: `SentenceTransformerEmbedder` and `HashEmbedder` (deterministic 384-dim hashing
  vectorizer, no model download, used in CI).
- `classifier.py`: `SklearnClassifier` (model resolved through `MLflowModelResolver`, exposes
  `predict_proba` → top-1 + 2 alternatives), `LlmClassifier` (few-shot via `TextGeneratorPort`),
  `RuleOnlyClassifier` (keyword table fallback). Selection order at runtime: MLflow champion →
  local joblib → LLM → rules.
- `detector.py`: `PortCableDetector` implementing a new `ObjectDetectorPort`
  (`detect(image_path) -> list[PortObservation]`), loading the YOLO checkpoint trained in notebook 05
  from MLflow; `StubDetector` returns `[]`. The image service calls the detector **first** and passes
  its findings into the VLM prompt as structured hints, which measurably reduces VLM hallucination.

### 4.8 MLflow integration (`libs/platform/mlflow_registry.py`), new in v1

MLflow is used for three distinct jobs; keep them separate in your head or the design gets muddled.

1. **Experiment tracking** (notebooks): every training run logs params, metrics, plots, and the
   dataset fingerprint. Experiment names: `cst/department-classifier`, `cst/sentiment`,
   `cst/intent-llm`, `cst/port-detector`, `cst/led-vlm`, `cst/asr`, `cst/retrieval`, `cst/e2e`.
2. **Model registry** (the promotion gate): a run is registered as a model version, then given the
   alias `@champion` only after it beats the current champion on the notebook's acceptance metric.
   Registered names: `cst-department-classifier`, `cst-sentiment-classifier`, `cst-port-detector`,
   `cst-embedder`, `cst-intent-llm` (the LLM entry stores the LoRA adapter and the GGUF path as
   artifacts plus the Ollama tag as a tag, Ollama itself is not served by MLflow).
3. **Runtime resolution** (`MLflowModelResolver`): `resolve(role) -> (obj, model_version_string)`.
   - caches downloaded artefacts under `v1_data/mlflow_cache/`;
   - stamps `model_version` on every artefact the pipeline writes, using the MLflow
     `name/version/run_id` triple, so SAD §8.2.4 reproducibility actually holds;
   - **degrades, never blocks**: on any MLflow error, log a warning, fall back to the local artefact
     path, then to the rule-based adapter, and raise the `MODEL_FALLBACK` flag on the ticket. The
     degradation tests of §8 cover this path.

Notebook helper `evaluation/mlflow_utils.py` with `start_run(experiment, tags)`,
`log_dataset_fingerprint(df)` (row count + sha256 of the sorted id column), and
`promote_if_better(name, run_id, metric, higher_is_better=True)` so promotion logic is written once
and not copy-pasted into eight notebooks.

### 4.5 Vector + graph
- `vector/inmemory.py`: NumPy matrix + metadata list, cosine similarity, JSON persistence, filter by
  `org_id`/`department`. Records `embedding_model` in the file header and refuses to query when it
  differs from the configured model (SAD §9.4).
- `graph/inmemory.py`: nodes/edges loaded from `config/seed/graph_seed.yaml` following the labels of
  SAD Figure 16 (`LedState -EVIDENCE_FOR-> Symptom -INDICATES-> Fault -RESOLVED_BY-> Procedure
  -DEFINED_IN-> Document`, `Fault -PERMITS-> Action`, `Fault -ESCALATES_TO-> ResolverQueue`).
  `expand(seed_terms, hops=2)` returns nodes, edges, and the procedures/actions reached.

### 4.6 Registry + factory (`libs/platform/registry.py`)
`build_ports(settings) -> Ports` dataclass holding one instance per port, chosen by the `*_impl`
settings. Every service receives this object; **no service constructs an adapter directly** (ADR-005).
Also loads `config/registry.yaml` so each artefact can be stamped with `model_version`.

### 4.7 Observability (`libs/observability/`)
`logging.py`, JSON structured logs with `ticket_id`, `stage`, `duration_ms`, `model_version`.
`metrics.py`, in-process counters/histograms with an optional Prometheus exporter; decorator
`@timed(stage)`.

**Acceptance:** `pytest tests/unit/test_adapters_stub.py` green in the `stub` profile with no
network access.

**Pitfalls and debugging**
- Ollama `format: "json"` still returns prose sometimes on small quantised models. Always run the
  output through a `_extract_json()` helper that finds the outermost `{...}` before parsing.
- Ollama first call after `ollama serve` loads the model and may take 30-90 s. Set
  `llm_timeout_s=120` for the first run or pre-warm with a one-token request at startup.
- `httpx` default timeout is 5 s, always pass an explicit `timeout=`; a silent 5 s timeout looks
  identical to "the LLM is down" and will trip the circuit breaker.
- SQLite + threads: `sqlite3.ProgrammingError: SQLite objects created in a thread…` means the engine
  was created without `connect_args={"check_same_thread": False}`, or a `Session` is being shared
  across broker worker threads. Create one session per handler invocation.
- `sentence-transformers` downloads ~90 MB on first use; in CI force `embedder_impl=hash_stub`.

---

## 5. Services

Each service is a package with `handler.py` (pure-ish function taking `(ports, session, envelope)`),
`__main__.py` (stand-alone runner subscribing to its topic), and `README.md` (one paragraph: the
requirement it implements, the topic it consumes, the table it owns). **No service imports another
service**, enforced by `tests/architecture/test_imports.py`.

Build in this order; each step is independently testable.

1. **intake_api** (REQ-ING-1..15), FastAPI. `POST /api/v1/tickets` (multipart: `text`,
   `files[]`, `customer_id`, `channel`, `Idempotency-Key` header). Validates size/type by
   **sniffing magic bytes, not the declared MIME**, stores media, writes `ticket` + `attachment` +
   `outbox(tickets.raw)` in one transaction, returns `202 {ticket_id}`. Also `GET /api/v1/tickets/{id}/status`.
2. **routing_svc** (REQ-ING-8, REQ-FUS-4), consumes `tickets.raw`, writes `aggregation_state` with
   the expected completion set `{attachment_ids by modality} ∪ {"text"}`, fans out to the three
   `.work` topics.
3. **text_svc**, normalise (unicode NFKC, whitespace, quoted-reply stripping), language detect,
   PII scan (regex: email, phone, NIC, card) → flags, publish `tickets.text.done`.
4. **audio_svc** (REQ-ASR-1..12), `TranscriberPort`, retries, `low_confidence` flag, writes
   `audio_transcript`, publishes `tickets.audio.done`. On terminal failure publish a `done` event
   with `status="failed"`, never silently drop, or the aggregation window will always expire.
5. **image_svc** (REQ-VLM-1..12), template choice, `VisualExtractorPort`, JSON-schema repair,
   writes `visual_summary`, publishes `tickets.image.done`.
6. **aggregator_svc** (REQ-FUS-1..10), the statechart of SAD §6.5. Records each result
   idempotently against `aggregation_state`, emits when the set is complete, or emits a `partial`
   payload when the window (120 s) expires. Uses `policy.fusion.fuse`, validates, writes
   `unified_payload` revision *n+1*, publishes `tickets.aggregated`.
   The timer in v1 is a single background sweeper thread scanning for expired rows every 5 s, do
   not use one `threading.Timer` per ticket.
7. **triage_svc** (REQ-CLS-*, REQ-PRI-*), `ClassifierPort` + `policy.priority` + `policy.routing`;
   writes `triage_result`; publishes `tickets.triaged`.
8. **retrieval_svc**, library, not a consumer. Dense top-k (k=8) over `sop_chunks` +
   `historical_resolutions`, then graph expansion from extracted entities (LED states, **port and
   cable observations from the detector**, error codes, device model), then a bounded context
   assembler (max ~2500 tokens, dedupe by chunk id).
9. **orchestrator_svc** (REQ-FLT-1..14), retrieval → `TextGeneratorPort.generate_json` with
   `models/prompts/llm/diagnosis.txt` → `Diagnosis`; `verify_citations()` drops chunk ids absent
   from the retrieved context and sets `UNVERIFIED_CITATION`; below
   `diagnosis_min_confidence` mark `needs_human_diagnosis`. Timeouts and circuit breaker come from
   the adapter. Writes `diagnosis` + `citation`; publishes `tickets.diagnosed`.
10. **response_svc** (REQ-RES-1..12), **agentic**, see §5.10 below. Consumes `tickets.diagnosed`,
    writes `draft_response` + `action_recommendation` + `agent_trace`, publishes `tickets.ready`,
    transitions the ticket to `READY_FOR_AGENT`. Contract in and out is identical to the
    single-call version, so nothing downstream knows it is an agent.
11. **projector_svc**, maintains `queue_projection` from `tickets.ready` and from workspace
    commands; the queue read path never joins the analysis tables.
12. **workspace_api** (REQ-WKS-1..18), `GET /queue`, `GET /tickets/{id}`, `POST /tickets/{id}/lock`,
    `PATCH /tickets/{id}/draft`, `POST /tickets/{id}/approve` (writes `agent_decision` then calls the
    delivery gateway), `POST /tickets/{id}/reject`, `POST /tickets/{id}/actions/{rec_id}/execute`,
    `WS /ws/queue`. Auth in v1: a static bearer token per role in `.env`, enough to exercise the
    authorization checks without building an IdP.
13. **delivery_gateway** (REQ-BR-1, REQ-SAFE-1), the only egress. Refuses to send without a
    persisted `agent_decision.id`; writes `delivery`.
14. **action_svc**, re-validates against the registry, idempotent execution keyed by
    `(ticket_id, action_id, sha256(params))`, simulated adapters in v1.
15. **knowledge_ingest** (REQ-ONB-1..10), parse Markdown/PDF/TXT → heading-aware chunks
    (≈800 chars, 100 overlap) → embed → vector upsert → entity extraction → graph upsert; writes
    `knowledge_document`/`knowledge_chunk` and a data-quality report.
16. **admin_api**, users, routing rules, thresholds, action registry CRUD, health, DLQ listing and
    replay. Every mutation writes a `config_version` row.

### 5.10 Agentic response generation (`services/response_svc/agent/`)

The draft and the action recommendation are produced by a **bounded tool-calling agent** rather than
one prompt. This is worth doing because the useful work here genuinely branches: sometimes the
diagnosis is enough to draft immediately, sometimes the agent needs one more SOP passage, the
customer's contract tier, or a check of what the action registry actually permits before it can
write a truthful reply.

**Non-negotiable boundaries** (these are what keep the SAD's safety properties intact):

- the agent has **no tool that contacts a customer**, drafting is the terminal step, and
  `delivery_gateway` still requires a persisted `agent_decision` (ADR-008);
- the agent has **no tool that executes an action**, it may only *propose* an
  `ActionRecommendation`, which `action_svc` re-validates after human approval;
- every tool is read-only except `propose_action` and `emit_draft`, which write only to the
  service's own tables;
- the loop is bounded: `agent_max_steps` (6), per-step timeout, total wall-clock budget, and a
  hard stop that falls back to the single-call draft prompt.

**Files**

```
services/response_svc/
├── handler.py            # consumes tickets.diagnosed, decides agent vs fallback
├── agent/
│   ├── loop.py           # the controller: plan → tool call → observe → repeat → finish
│   ├── tools.py          # tool definitions + JSON schemas + dispatch table
│   ├── prompts.py        # system prompt, tool-result formatting, finish instruction
│   └── trace.py          # AgentStep records, persistence, redaction
└── fallback.py           # the deterministic single-call draft path
```

**Tool set** (each is a thin wrapper over an existing port, the agent introduces no new I/O paths):

| Tool | Signature | Backed by | Notes |
|---|---|---|---|
| `search_procedures` | `(query, k=5) -> [chunk]` | `VectorIndexPort` | returns opaque short ids `c1..cN` for citation |
| `expand_fault_graph` | `(terms[], hops=2) -> subgraph` | `GraphStorePort` | the ADR-007 traversal |
| `get_ticket_context` | `() -> payload summary` | read model | payload, triage, diagnosis; never raw media |
| `get_customer_profile` | `(customer_id) -> {segment, tier, open_tickets, prior_contacts_7d}` | DB | drives tone and priority language |
| `list_permitted_actions` | `(fault) -> [registry entry]` | `action_registry.yaml` | the agent cannot see unregistered actions at all |
| `check_compliance` | `(draft_text) -> [PolicyFinding]` | `policy.compliance` | agent may self-correct once before finishing |
| `propose_action` | `(action_id, params) -> accepted \| rejected+reason` | `policy.action_selection` | validated against the entry's JSON schema on the spot |
| `emit_draft` | `(text, citations[]) -> ok` | terminal | ends the loop |

**Control flow** (`loop.py`):

1. Build the system prompt: role, hard rules (only cite returned chunk ids; never promise
   compensation, credits, or a fixed restoration time; never invent an action), the tool schemas,
   and the ticket's diagnosis.
2. Call `TextGeneratorPort` with Ollama tool-calling (`POST /api/chat` with `tools=[…]`). Parse
   `message.tool_calls`. **If the model returns no `tool_calls` field** (common on quantised 7-8 B
   builds), fall back to a ReAct text protocol: require
   `{"thought":…, "tool":…, "args":{…}}` with `format: "json"` and parse that instead. Implement both;
   select by a `tool_protocol` setting auto-detected once at startup.
3. Dispatch, append the observation (truncated to ~800 chars per result), loop.
4. Stop on `emit_draft`, on step budget, or on the total time budget.
5. Post-conditions enforced in code, not by the prompt: citations verified against what
   `search_procedures` actually returned; compliance re-run on the final text regardless of whether
   the agent called it; the action re-validated against the registry. Any violation → drop the
   offending part, set a flag (`UNVERIFIED_CITATION`, `COMPLIANCE_EDIT`, `ACTION_REJECTED`), keep the
   rest. The agent's output is never trusted on its own claim of having checked something.
6. On exception, timeout, or budget exhaustion → `fallback.py` single-call draft, flag
   `AGENT_FALLBACK`. A ticket must always reach `READY_FOR_AGENT`.

**Persistence, `agent_trace` table** (new, owned by `response_svc`):
`id, ticket_id, step_no, role(plan|tool|observation|final), tool_name, tool_args JSONB,
observation JSONB, latency_ms, token_estimate, created_at`. Append-only. Two reasons this is
mandatory: the workspace shows the agent's reasoning to the agent-user (REQ-WKS transparency), and
without it an agent failure is undebuggable.

**Evaluation** (notebook 08): agentic vs single-call on the same 100 tickets, citation
verification rate, compliance findings per draft, action-recommendation precision, mean steps, p95
latency, fallback rate. Report both; if the agent does not beat the single call on grounding, ship
the single call and say so.

**Pitfalls**
- Infinite tool loops (the model calls `search_procedures` with the same query forever). Deduplicate
  identical `(tool, args)` calls and return `"already retrieved, see step N"` instead of re-running.
- Context blow-up: six steps × full chunk text exceeds `num_ctx` and Ollama silently truncates the
  **front** of the conversation, dropping the system rules. Truncate observations, keep the system
  message pinned, and log the estimated token count each step.
- Tool-call JSON with trailing commas or Python `True`, run every tool-arg parse through the same
  `_extract_json()` + repair path as §4.4.
- The agent proposing an action for a fault it never actually confirmed. Require `propose_action` to
  be preceded by a `list_permitted_actions` call in the same run; reject otherwise.

**Pitfalls**
- At-least-once redelivery duplicates rows unless every writer is idempotent on
  `(ticket_id, stage, attachment_id)`. Use `INSERT … ON CONFLICT DO NOTHING` (SQLite:
  `sqlite_on_conflict` / `insert().on_conflict_do_nothing()` from `sqlalchemy.dialects.sqlite`).
- The classic aggregation bug: the completion set counts *attachments*, but a failed attachment
  never produces a `done` event. Always publish a `done` event with a failure status.
- Publishing inside the DB transaction (rather than via the outbox) produces ghost events on
  rollback. Never call `broker.produce` from inside `session_scope()`.

---

## 6. Runtime wiring (`runtime/`)

- `runtime/wiring.py::build_app(settings)`, builds ports, DB, broker, subscribes every handler to
  its topic and group, starts the outbox drainer and the aggregation sweeper.
- `runtime/local.py`, single-process mode: intake API + all consumers + workspace API on one
  Uvicorn process. This is the demo entry point: `python -m runtime.local`.
- `runtime/demo_ticket.py`, posts the prototype's sample assets
  (`ingestion-pipeline-prototype/data/sample_audio/sample_call.wav`,
  `sample_images/router_red_led.png`) plus a text complaint, then polls until `READY_FOR_AGENT` and
  prints the payload, triage, diagnosis, and draft.

**Acceptance:** `APP_PROFILE=stub python -m runtime.demo_ticket` prints a ticket reaching
`READY_FOR_AGENT` in under 10 s with no network access.

---

## 7. Migrations and seed

`migrations/001_init.sql` generated from the ORM metadata (`sqlalchemy.schema.CreateTable`) and kept
forward-only. `scripts/seed.py` loads: one organization, three users (agent, lead, admin), the
routing rules, the action registry, six SOP documents, and the graph seed.

**Acceptance:** `python scripts/seed.py --reset` then `python -m runtime.local` and the workspace
queue endpoint returns an empty list rather than a 500.

---

## 8. Tests (`tests/`)

Mirror the CI gates of SAD §8.2.3:

- `tests/unit/`, policies (priority, routing, action selection, compliance, fusion), the state
  machine, `verify_citations`. Target ≥85 % on `libs/domain/policy`.
- `tests/contract/`, every payload contract round-trips against the golden example copied from SRS
  Appendix B.5 into `tests/golden/unified_payload.json`, in both directions.
- `tests/integration/test_pipeline_stub.py`, full pipeline under the `stub` profile with the
  in-process broker: ticket in → `READY_FOR_AGENT` out.
- `tests/architecture/test_imports.py`, no `services.X` imports `services.Y`; only
  `delivery_gateway` imports `MailGatewayPort`; only `action_svc` imports `ActionAdapterPort`.
- `tests/degradation/`, parametrised: for each of ASR, VLM, LLM, embedder, replace the adapter with
  one that always raises and assert the ticket still reaches `READY_FOR_AGENT` with the expected
  flag set. This is the single most valuable test suite in the project, it is what proves G7.

---

## 9. Training notebooks (`notebooks/`), real data, real checkpoints, MLflow-tracked

Nine notebooks. Every one of them obeys the same contract, so the reviewer can check them
mechanically:

1. **Cell 1 is boilerplate**: `os.chdir` to the `v1` root, `sys.path.insert(0, ".")`, read
   `MLFLOW_TRACKING_URI` from the environment (default `http://127.0.0.1:5000`), set the experiment
   name, print the resolved dataset paths. No absolute `d:\…` path anywhere, the data root is
   `Path.cwd().parent / "data"`.
2. **First markdown cell** declares: inputs, outputs, the artefact it registers, the acceptance
   metric, and the expected runtime with and without a GPU.
3. **Everything trained is logged to MLflow**: params, metrics, plots, the dataset fingerprint
   (row count + sha256 over the sorted id column), the environment (`mlflow.log_input`, pip freeze),
   and the model itself with a signature and an input example.
4. **Checkpoints land in two places**: MLflow (authoritative, versioned, aliased) and
   `models/artifacts/` (a plain-file mirror so the pipeline still starts with MLflow down).
5. **Promotion is explicit**: the last cell calls
   `promote_if_better(registered_name, run_id, metric)` and prints whether the alias `@champion`
   moved. Never promote silently.
6. Outputs cleared before commit: `jupyter nbconvert --clear-output --inplace notebooks/*.ipynb`.

Build the notebooks from `notebooks/_build_notebooks.py` (cells held as Python strings, emitted as
`.ipynb` JSON) so they are diffable and regenerable.

---

### 01_data_ingestion_and_preparation.ipynb
**Experiment** `cst/data-prep` · **Inputs** the two zips in `../data/` · **Outputs**
`data/processed/*.parquet`, `config/department_map.yaml`, `data/raw/` (extracted)

- Extract both archives to `data/raw/bitext/` and `data/raw/router_detection/`. Idempotent: skip if
  the target exists and the zip mtime is unchanged.
- **Bitext** (`Bitext_Sample_..._27K_responses-v11.csv`, columns `flags, instruction, category,
  intent, response`): load with `pandas`, assert 27k rows / 11 categories / 27 intents, and profile
  category × intent counts, text length, and the `flags` distribution.
- **Slot handling**: `instruction` and `response` contain `{{Order Number}}`-style slots. Produce two
  text columns, `instruction_clean` (slots removed) and `instruction_filled` (slots replaced with
  realistic random values from a small generator). Train on `instruction_filled`, evaluate on both;
  training on the raw braces teaches the classifier to key on `{{`.
- **Department mapping** (`config/department_map.yaml`, explicit and reviewable, not inferred):
  `REFUND, INVOICE, PAYMENT → billing`; `CANCEL → retention`;
  `ACCOUNT, SUBSCRIPTION → technical_support`; `ORDER, SHIPPING, DELIVERY → general`;
  `CONTACT, FEEDBACK → general`.
- **Telecom supplement, mandatory.** Bitext contains no telecom content, so
  `network_operations` and `field_service` would be unlearnable and the classifier would be useless
  for the actual product. Build `data/processed/telecom_supplement.csv` with 600-900 rows across
  `technical_support, network_operations, field_service, billing, retention`, each row
  `{text, department, intent, fault, priority_hint, sentiment}`. Two generation routes, use both and
  label the source column: (a) template expansion over a fault × symptom × device grid written by
  hand, deterministic and licence-clean; (b) LLM paraphrase through the local Ollama model to add
  surface variety, then a manual review pass over a 10 % sample. Record the review outcome in the
  notebook. Keep the supplement in version control; it is a project asset.
- **Splits**: stratified 80/10/10 on `(department, intent)`, seed 42, saved as Parquet. Store the
  split assignment as a column so every later notebook uses the identical split.
- **Router dataset**: parse the three `_annotations.coco.json` files, produce a summary table of the
  16 classes and their counts (verified: train 2137 images / 4630 boxes, valid 111 / 291, test
  94 / 218), and **check for augmentation leakage**, Roboflow generated 3 augmented versions per
  source image; group by the pre-`.rf.` filename stem and assert no stem appears in two splits. If
  it does, re-split by stem and save the corrected split to `data/processed/router_splits.json`.
- Log to MLflow: row counts, class distributions, both fingerprints, the leakage check result, and
  `config/department_map.yaml` as an artifact.

**Acceptance**: processed Parquet files exist; every project `Department` value has ≥200 training
rows; leakage check passes.

---

### 02_department_classifier.ipynb
**Experiment** `cst/department-classifier` · **Registers** `cst-department-classifier` ·
**Acceptance** macro-F1 ≥ 0.85 on the held-out split, and ≥0.70 F1 on each telecom class

- Features: TF-IDF word 1-2 grams + char\_wb 3-5 grams, `min_df=2`, union via `FeatureUnion`.
- Models: `LinearSVC` + `CalibratedClassifierCV` (sigmoid), `LogisticRegression(class_weight=
  "balanced")`, and, as the transformer arm, `distilbert-base-uncased` fine-tuned for 3 epochs
  (`transformers.Trainer`, lr 2e-5, bs 16, max_len 128). Log each as a separate MLflow run under the
  same experiment, with a `model_family` tag.
- Report macro-F1, per-class F1, confusion matrix (logged as a PNG), and a **calibration curve**,
  `ClassifierPort` returns confidences that the triage threshold and the workspace UI both consume,
  so a badly calibrated winner is worse than a slightly less accurate calibrated one.
- Save: `mlflow.sklearn.log_model(..., signature=…, input_example=…)` (or
  `mlflow.transformers.log_model`), mirror to `models/artifacts/department_clf.joblib` plus a
  `department_clf.json` sidecar (`model_version, trained_at, classes, macro_f1, threshold`).
- Promote the best macro-F1 run to `@champion`.

**Pitfalls**: class imbalance after the Bitext→department collapse (`general` dominates), use
`class_weight="balanced"` and report macro, never accuracy. `CalibratedClassifierCV` in
scikit-learn ≥1.6 renamed `base_estimator` to `estimator`; pin or handle both.

---

### 03_intent_classifier_and_slot_analysis.ipynb
**Experiment** `cst/intent` · **Registers** `cst-intent-classifier` · **Acceptance** top-1 ≥0.90 on
the 27 Bitext intents (they are clean and well separated; if it comes out much lower, suspect a
split or preprocessing bug rather than the model)

- Same feature pipeline as notebook 02 over `intent`, plus a nearest-centroid variant on
  sentence-transformer embeddings for comparison.
- Analyse `flags` (B/Q/Z variation tags) as a robustness axis: report accuracy per flag group, which
  is a cheap proxy for how the model handles colloquial and noisy customer text.
- This model is the fast path that the agent and the orchestrator can consult before spending an LLM
  call; log its latency so the comparison in notebook 05 is honest.

---

### 04_sentiment_priority_calibration.ipynb
**Experiment** `cst/sentiment` · **Registers** `cst-sentiment-classifier` · **Outputs**
`config/priority_weights.yaml`

- Sentiment labels do not exist in Bitext. Derive weak labels from the telecom supplement's
  `sentiment` column plus a lexicon+heuristic labeller over Bitext `instruction`, then hand-correct
  a 300-row evaluation set. Be explicit in the notebook that the evaluation set is human-labelled
  and the training set is weakly labelled.
- Train a small classifier (`LogisticRegression` over TF-IDF, or `distilbert` if the GPU is free).
- **Priority calibration**: hand-label the target band for 200 tickets, then grid-search the six
  weights of `libs/domain/policy/priority.py` (sentiment, urgency keywords, segment, outage scope,
  prior contacts, SLA age) maximising Cohen's κ against the labels. Log κ, the weight vector, and a
  band-confusion matrix; write the winner to `config/priority_weights.yaml`.
- The policy stays code; only the weights are data (ADR-010). Do not let the grid search emit code.

---

### 05_diagnosis_llm_ollama.ipynb, the LLM fine-tune
**Experiment** `cst/intent-llm` · **Registers** `cst-intent-llm` (artifacts: LoRA adapter, merged
GGUF path, `Modelfile`; tag `ollama_tag=cst-diagnosis:v1`) · **Acceptance** the fine-tune must beat
the prompt baseline on JSON validity **and** department accuracy, else the baseline ships

Run both tracks and log both to MLflow:

- **Track A, prompt baseline (no training).** Few-shot prompt over
  `llama3.1:8b-instruct-q4_K_M` through Ollama with `format: "json"`, measured on the held-out set
  from notebook 01. This is what the pipeline uses on day one and the fallback if training fails.
  Log: exact-match intent accuracy, department accuracy, JSON-validity rate, p50/p95 latency.
- **Track B, QLoRA.** Dataset in chat format:
  `{"messages":[{"role":"system", …}, {"role":"user", "content": fused_text},
  {"role":"assistant", "content": json.dumps({"intent":…, "fault":…, "department":…,
  "rationale":…})}]}`, built from the processed Bitext + telecom supplement (the supplement is what
  teaches fault vocabulary, Bitext alone cannot). Train with `peft`: 4-bit NF4, r=16, α=32,
  dropout 0.05, target modules `q,k,v,o,gate,up,down`, lr 2e-4 cosine, 2 epochs, bs 1 × grad-accum
  16, `max_seq_len` 1024, `gradient_checkpointing=True`. Log loss curves and every hyperparameter.
- **Export to Ollama**: `merge_and_unload()` → `llama.cpp/convert_hf_to_gguf.py` → quantise
  `q4_K_M` → write a `Modelfile` (`FROM ./model-q4_K_M.gguf`, `TEMPLATE`, `PARAMETER temperature
  0.2`, `SYSTEM` = the diagnosis system prompt) → `ollama create cst-diagnosis:v1 -f Modelfile`.
  Log the `Modelfile` and the quantised checksum as MLflow artifacts; the GGUF itself is large, so
  log its path and sha256 rather than the bytes unless the artifact store is on a fast disk.
- **Head-to-head cell**: base vs fine-tuned on identical prompts, same seed, table written to
  `evaluation/reports/llm_comparison.md` and logged to MLflow. Include a tool-calling check, the
  agent of §5.10 needs the model to emit usable `tool_calls`, and a LoRA on JSON-only outputs can
  *degrade* tool-calling. Test that explicitly before promoting.
- Switching the system to the fine-tune is a one-line change: `llm_model=cst-diagnosis:v1` in `.env`.

**Pitfalls**: 8B QLoRA needs ~10-12 GB VRAM, below that switch the base to
`Llama-3.2-3B-Instruct` or `Qwen2.5-3B-Instruct` and record the substitution in the docs; Llama 3.1
weights are gated (accept the licence, `huggingface-cli login`); convert the **merged** model, never
the adapter; `bitsandbytes` on Windows is fragile, if it will not install, run this notebook in
WSL2 or Colab and copy the GGUF back; a fine-tune that overfits produces perfect JSON and useless
rationales, so read ten generated samples by hand before promoting.

---

### 06_port_cable_detector.ipynb, the router dataset's real use
**Experiment** `cst/port-detector` · **Registers** `cst-port-detector` · **Acceptance**
mAP@50 ≥ 0.60 overall and ≥0.50 on `lans`, `power`, `fiber-conn`

- The Roboflow export is COCO with 16 classes covering ports, cables, and connectors, **not** LEDs.
  Train an object detector: `ultralytics` YOLOv8n/s (convert COCO → YOLO txt in the notebook) or
  `torchvision` Faster R-CNN if `ultralytics` is unwanted. 50-80 epochs, 516×516, default
  augmentation off (Roboflow already augmented).
- Use the leakage-corrected splits from notebook 01, not the raw folder split.
- Collapse the 16 classes into the five `PortObservation.port_type` values plus a `connected`
  boolean derived from co-occurrence geometry (a `*-conn` or `*-cable` box overlapping a port box
  → connected). Report both the raw 16-class mAP and the collapsed 5-class accuracy, because the
  second is what the pipeline consumes.
- Log the confusion matrix, PR curves, and 20 annotated sample predictions as images. Register the
  best checkpoint (`best.pt`) with `mlflow.pytorch`/artifact logging; mirror to
  `models/artifacts/port_detector.pt`.
- Wire-up note: `services/image_svc` runs the detector before the VLM and injects
  `"Detected ports: lan(connected), power(connected), fiber(not connected)"` into the VLM prompt.

**Pitfalls**: class imbalance is severe (`usb` 887 boxes vs `fibers` 15), report per-class AP and
do not let a high overall mAP hide a dead class; the tiny classes may be better dropped than
trained. COCO category id 0 is the Roboflow super-category `router-detection`, which is not a real
class, exclude it or every metric is inflated.

---

### 07_vlm_led_and_prompt_tuning.ipynb
**Experiment** `cst/led-vlm` · **Outputs** tuned `models/prompts/vlm/*.txt`, thresholds ·
**No registered model** (the VLM is served by Ollama; only prompts and thresholds are artefacts)

- Hand-label 40-60 router images from `data/raw/router_detection/` with their visible LED states into
  `data/processed/led_labels.jsonl` (`{image, device_hint, leds:[{label,colour,behaviour}]}`). This
  is the only manual labelling the project requires and it takes about two hours.
- Compare three extractors on field-level accuracy and JSON validity: heuristic HSV,
  `llava:7b` with the `router_led_panel` prompt, and `llava:7b` **with detector hints** from
  notebook 06. Log each prompt revision as a separate MLflow run with the prompt text as an artifact.
- Calibrate `vlm_low_confidence_threshold` so flagged extractions capture ≥80 % of wrong ones.
- Ship the winner; keep the heuristic as the `VisualExtractorPort` fallback (risk R1).

**Pitfalls**: Ollama vision wants raw base64 with no `data:` prefix; re-save PNGs as RGB (alpha
channel triggers 400s); many images in this dataset show cables and connectors rather than a
readable LED panel, filter to panel-visible images before labelling or the evaluation set is noise.

---

### 08_asr_and_retrieval.ipynb
**Experiments** `cst/asr`, `cst/retrieval` · **Registers** `cst-embedder` (the chosen embedding
model, wrapped) · **Acceptance** WER ≤0.25 on the sample calls; recall@5 ≥0.80 on the retrieval set

- **ASR**: `faster-whisper` `tiny`/`base`/`small` over
  `../ingestion-pipeline-prototype/data/sample_audio/*` plus any recorded telecom audio; WER with
  `jiwer`; per-segment confidence distribution; latency per audio-minute, CPU vs GPU. Calibrate
  `asr_low_confidence_threshold` so flagged transcripts capture ≥80 % of high-WER cases.
- **Retrieval**: chunking comparison (fixed 500/800/1200 vs heading-aware) over the seed SOP corpus;
  embedding comparison (`all-MiniLM-L6-v2` vs `BAAI/bge-small-en-v1.5`); evaluation on 40
  hand-written question→chunk pairs (recall@5, MRR); then **dense-only vs dense+graph expansion** on
  fault-prediction accuracy, this is the experiment that justifies ADR-007, so report it whichever
  way it comes out.
- Log the chosen chunking parameters to `config/settings.yaml` and register the embedder so the
  vector store's `embedding_model` guard has a version to compare against.

---

### 09_agentic_response_and_e2e_evaluation.ipynb
**Experiment** `cst/e2e` · **Outputs** `evaluation/reports/e2e_report.md`,
`evaluation/reports/agent_vs_single.md`

- Build a 100-ticket synthetic multimodal evaluation set (`evaluation/datasets/synthetic.py`):
  telecom-supplement text + a reused audio sample + a router image, with known ground-truth
  department, fault, and expected action.
- Run the harness three ways and log all three as MLflow runs under one parent run:
  (a) `stub` profile, proves the plumbing; (b) full profile, **single-call** response generation;
  (c) full profile, **agentic** response generation.
- Metrics: department accuracy/macro-F1, priority band κ, fault top-1/top-3, citation verification
  rate, compliance findings per draft, action precision, draft edit distance, JSON validity, p50/p95
  per-stage latency against the SRS §5.1 budget, agent mean steps and fallback rate.
- Degradation matrix: for each of ASR, VLM, LLM, detector, embedder, MLflow forced to fail, assert
  every ticket still reaches `READY_FOR_AGENT` and record which flags were raised.
- Conclude with an explicit recommendation: agentic or single-call, with the numbers behind it.

---

### MLflow conventions used by all notebooks

- Run naming: `{notebook}-{model_family}-{yyyymmddHHMM}`; tags `notebook`, `model_family`,
  `dataset_fingerprint`, `git_sha`, `profile`.
- One registered model per role, versions never deleted, aliases `@champion` (serving) and
  `@candidate` (under evaluation). The runtime only ever reads `@champion`.
- Metrics are logged with the same key names the evaluation harness uses, so notebook runs and
  harness runs are directly comparable in the MLflow UI.
- `promote_if_better` refuses to promote when the dataset fingerprint differs from the champion's
  unless `force=True`, otherwise you eventually promote a model that only looks better because the
  split changed.

---

## 10. Evaluation harness (`evaluation/`)

- `datasets/bitext.py`, loads the extracted CSV, applies `config/department_map.yaml`, returns the
  frozen splits from notebook 01 (never re-splits; the split column is authoritative).
- `datasets/roboflow_router.py`, COCO loader, class collapse to `PortObservation.port_type`, the
  leakage-corrected split, and an iterator yielding `(image_path, annotations)`.
- `datasets/telecom.py`, the supplement, with the `source` column preserved so template rows and
  LLM-paraphrased rows can be scored separately.
- `datasets/synthetic.py`, generates multimodal tickets by pairing a telecom text complaint, a
  reused audio sample, and a router image, with ground-truth labels attached.
- `mlflow_utils.py`, `start_run`, `log_dataset_fingerprint`, `promote_if_better`, `resolve_champion`.
- `harness/run.py`, drives the pipeline in-process (the "same code, different driver" seam of
  UC-8), collects per-stage timings from `libs/observability/metrics`, computes the metric set
  above, writes JSON + CSV + Markdown to `evaluation/reports/`, **and logs the whole run to MLflow**
  under `cst/e2e` so a pipeline evaluation is comparable with the notebook runs that produced its
  models.
- `harness/metrics.py`, department accuracy/macro-F1, priority band κ, fault top-k, citation
  verification rate, draft edit distance, JSON validity, p50/p95 stage latency.

---

## 11. Documentation to produce in `v1/docs/`

| File | Content |
|---|---|
| `00-IMPLEMENTATION-PLAN.md` | this plan |
| `01-setup.md` | prerequisites, install, Ollama setup, profiles, first run, Windows notes |
| `02-architecture-mapping.md` | SAD element → v1 module table, plus the deviations table above |
| `03-data-preparation.md` | datasets, licences, the Bitext→Department mapping and why the telecom supplement is required, split methodology |
| `04-department-classifier.md` | features, models tried, metrics, chosen artefact, retraining command |
| `05-llm-finetuning-ollama.md` | prompt baseline vs QLoRA, dataset format, hyperparameters, GGUF conversion, `ollama create`, comparison table, rollback to the base model |
| `06-vlm-and-asr.md` | prompt templates, thresholds, heuristic fallback, WER results |
| `06b-port-cable-detector.md` | the Roboflow dataset's real content, class collapse, leakage fix, mAP results, how detections reach the VLM prompt and the graph |
| `07-knowledge-graphrag.md` | chunking, embeddings, graph schema, retrieval results |
| `08-evaluation.md` | harness usage, metric definitions, current numbers, SRS §5.1 budget compliance |
| `09-operations.md` | run modes, health checks, DLQ replay, common failures, log/metric reference |
| `10-traceability.md` | REQ-* → module → test table |
| `11-troubleshooting.md` | the consolidated symptom → cause → fix table |
| `12-mlflow.md` | server setup, experiment and registry naming, the promotion gate, how the runtime resolves `@champion`, what happens when MLflow is down, how to roll a model back |
| `13-agentic-response.md` | tool catalogue, the loop, budgets, the post-condition checks, the trace table, agentic vs single-call results, how to disable the agent |

---

## 12. Suggested execution order (each line is one work session)

1. Steps 1-2 (scaffold, config) → `import libs.domain` works.
2. Step 3 (domain) + unit tests → policies green.
3. Step 4.1-4.3 (broker, DB, object store) + step 7 (migrations, seed).
4. Step 4.4-4.6 with **stubs only**, then services 1-6 → `APP_PROFILE=stub` reaches `AGGREGATED`.
5. Services 7-11 with stubs → `READY_FOR_AGENT` end to end; integration + degradation tests.
6. Real adapters: faster-whisper, Ollama LLM, Ollama vision, sentence-transformers.
7. Services 12-16 (workspace/admin/knowledge/delivery/action).
8. MLflow server up + `mlflow_registry.py` + `evaluation/mlflow_utils.py`; prove resolution and the
   MLflow-down fallback with a test before any notebook trains anything.
9. Notebook 01 (data ingestion, the department map, the telecom supplement, the leakage check).
   Nothing else can be trained until this is right, and it is the notebook most likely to need a
   second pass.
10. Notebooks 02→03→04 (department, intent, sentiment/priority) → the pipeline gets its first real
    models through the MLflow champion path.
11. Notebooks 06→07→08 (port detector, VLM prompts, ASR and retrieval).
12. Agentic response service (§5.10) on top of the working single-call path, build the fallback
    first, the agent second, so there is always something that works.
13. Notebook 05 (LLM fine-tune), late, because the prompt baseline already unblocks everything and
    this is the step most likely to be blocked by hardware.
14. Notebook 09 + evaluation report + all documents of §11.

---

## 13. Problems to expect, ranked by likelihood

| # | Symptom | Likely cause | Fix / debug |
|---|---|---|---|
| 1 | Ticket never leaves `PROCESSING` | aggregation completion set never satisfied, a failed attachment produced no `done` event | inspect `aggregation_state`; ensure failure paths still publish `done` with `status=failed`; confirm the sweeper thread is running (`log stage=aggregator event=sweep`) |
| 2 | LLM returns prose, `json.JSONDecodeError` | small quantised model ignoring `format: json` | `_extract_json()` fallback, then one repair call; lower temperature to 0.1; shorten the prompt; verify the model tag actually supports instructions (`ollama show <model>`) |
| 3 | `httpx.ReadTimeout` on the first LLM call | cold model load | pre-warm at startup; raise `llm_timeout_s`; `ollama ps` to confirm the model is resident |
| 4 | `connection refused` to 11434 | `ollama serve` not running, or bound to another host | `curl /api/tags`; on Windows check the tray service; set `OLLAMA_HOST=0.0.0.0` if calling from a container |
| 5 | Duplicate rows after a retry | non-idempotent writer | add the uniqueness constraint from SAD §9.2 and use `ON CONFLICT DO NOTHING`; the constraint is the arbiter, not the code |
| 6 | `sqlite3.OperationalError: database is locked` | concurrent writes from broker threads | WAL mode, short transactions, one session per handler, `timeout=30` in `connect_args` |
| 7 | Classifier predicts only 3 departments | Bitext has no telecom classes | the telecom supplement of notebook 01 is mandatory; also check `class_weight="balanced"` |
| 8 | Citations always unverified | chunk ids in the prompt differ from those in the retrieved context (truncation or renumbering) | print the context id list next to the model output; use short opaque ids (`c17`) in the prompt and map back |
| 9 | Retrieval quality collapses after changing the embedding model | index built with a different model | the vector store must refuse mismatched `embedding_model`, verify that guard exists and rebuild the index |
| 10 | VLM invents LEDs that are not in the image | over-permissive prompt | constrain the prompt to "report only what is visible; use `unknown`"; lower temperature; cross-check with the heuristic extractor and flag disagreement |
| 11 | WER far worse than published Whisper numbers | 8 kHz telephone audio, wrong sample rate, or the wrong language hint | resample to 16 kHz mono; pass `language="en"`; try `small`; report per-segment confidence |
| 12 | `import services.x` fails in tests | missing `__init__.py` or the package not reinstalled after adding a directory | `pip install -e .` again; run pytest from `v1/` |
| 13 | Pipeline works in the demo but hangs in tests | in-process broker worker threads not joined / not daemonised | give the broker `start()`/`stop()` and call `stop()` in a pytest fixture teardown |
| 14 | QLoRA OOM | 8B on <12 GB VRAM | 3B base, `gradient_checkpointing=True`, `max_seq_len=512`, batch 1 |
| 15 | `ollama create` fails on the GGUF | converted the adapter instead of the merged model, or an unsupported architecture | `merge_and_unload()` first, then convert; check `llama.cpp` supports the base architecture |
| 16 | Agent loops until the step budget every time | the model never calls `emit_draft`, or repeats one tool | dump the `agent_trace` rows for the ticket; deduplicate identical `(tool, args)`; make `emit_draft` the only tool described as terminal and say so in the system prompt; check whether `tool_calls` is being returned at all, else switch to the ReAct protocol |
| 17 | Agent output degrades after the LoRA fine-tune | JSON-only training destroyed tool-calling ability | test tool-calling explicitly before promoting (notebook 05); keep the base model as the agent's generator and use the fine-tune only for diagnosis if they conflict, `llm_model` and the agent's model are allowed to differ |
| 18 | Agent's system rules stop being obeyed after step 3 | conversation exceeded `num_ctx`, Ollama truncated from the front | raise `num_ctx`, truncate observations to ~800 chars, re-inject the rules in the final "now write the reply" turn |
| 19 | `mlflow.exceptions.RestException: RESOURCE_DOES_NOT_EXIST` at startup | the `@champion` alias was never set, or the registry is empty | the resolver must fall back to the local artefact and flag `MODEL_FALLBACK`, not crash, if it crashed, the fallback path is missing; set the alias with `promote_if_better(force=True)` for the first version |
| 20 | Every run logs to `Default` and metrics are unusable | `mlflow.set_experiment` missing or the tracking URI defaulted to `./mlruns` | assert the resolved tracking URI in cell 1 and fail loudly if it is a local path when the server is expected |
| 21 | Champion model silently changed and results moved | someone promoted from a run trained on a different split | `promote_if_better` compares dataset fingerprints; do not add `force=True` to make a promotion "work" |
| 22 | Port detector mAP looks excellent but the pipeline gets nothing useful | COCO category 0 (`router-detection` super-category) counted as a class, or augmented duplicates of the same source image split across train and test | exclude category 0; group by the pre-`.rf.` filename stem when splitting (notebook 01 checks this) |
| 23 | Detector finds ports on images that contain no router | the dataset is mostly close-ups; the model has no negative class | add a confidence floor, and cross-check with the VLM's own device detection before writing `ports[]` into the payload |
| 24 | Classifier confidences are all ~0.99 | `LinearSVC` decision function passed off as a probability | calibrate (`CalibratedClassifierCV`), the triage threshold is meaningless otherwise |

---

## 14. Definition of done for v1

- `APP_PROFILE=stub pytest` green, including architecture and degradation suites.
- `python -m runtime.demo_ticket` with Ollama running produces, for a text+audio+image ticket: a
  validated `UnifiedTicketPayload` with correct provenance spans, a triage result with department and
  band, a diagnosis with at least one verified citation, a compliant draft reply, and a registry-backed
  action recommendation, all persisted and visible through `GET /api/v1/tickets/{id}`.
- Approval through `workspace_api` writes an `agent_decision` and a `delivery` whose `approval_id`
  is non-null; attempting delivery without it fails.
- `evaluation/reports/e2e_report.md` exists with the metric table.
- All nine notebooks execute top to bottom on a clean checkout (given the datasets, Ollama, and a
  running MLflow server), and every document in §11 is written.
- MLflow holds a registered `@champion` version for `cst-department-classifier`,
  `cst-sentiment-classifier`, `cst-port-detector`, `cst-embedder`, and either a `cst-intent-llm`
  version or a documented decision to ship the prompt baseline; the runtime is verified to load each
  one, and verified to keep running with the MLflow server stopped.
- The agentic path produces a draft with verified citations and a registry-backed action for the demo
  ticket, its `agent_trace` is visible through the workspace API, and disabling `agent_enabled`
  falls back to the single-call path with no other change.
- `evaluation/reports/agent_vs_single.md` exists and carries an explicit recommendation.
