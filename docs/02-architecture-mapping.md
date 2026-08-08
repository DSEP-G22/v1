# 02 — Architecture mapping (SAD -> v1)

## Deviations from the SAD (deliberate, for a single-host demo)

| SAD element | v1 substitute | Reason |
|---|---|---|
| Kafka | in-process broker by default (`libs/platform/broker/inprocess.py`), Kafka adapter behind the same `EventBrokerPort` (`libs/platform/broker/kafka.py`) | single-host demo, CI without Docker |
| PostgreSQL 16 | SQLAlchemy 2 over SQLite by default, Postgres by URL (`libs/platform/db/session.py::build_engine` takes any SQLAlchemy URL) | zero-setup dev; identical ORM code either way |
| Qdrant | in-memory NumPy index persisted to JSON (`libs/platform/vector/inmemory.py`) | small corpus (<10k chunks) |
| Neo4j | in-memory graph loaded from a YAML seed (`libs/platform/graph/inmemory.py`, `config/seed/graph_seed.yaml`) | graph is ~40 nodes in the demo, not ~200 — see note below |
| vLLM | **Ollama** (explicit instruction for v1) | local, no GPU-only requirement |
| MinIO | local filesystem object store (`libs/platform/objectstore/local.py`), S3/MinIO adapter behind the same `ObjectStorePort` (`libs/platform/objectstore/s3.py`) | same `ObjectStorePort` either way |

Everything above sits behind the ports of SAD §5.2.3 (`libs/domain/ports/`), so none of it changes
service code — swapping an adapter is a `libs/platform/registry.py` change, not a `services/*`
change.

**Graph seed size note:** the implementation plan's own text says "~200 nodes in the demo"; the
seed actually shipped (`config/seed/graph_seed.yaml`) has ~40 nodes (5 LedStates, 5 Symptoms, 8
Faults, 6 Procedures, 4 Documents, 4 Actions, 3 ResolverQueues) covering the 6 seeded SOPs'
fault space. 200 nodes was aspirational for a larger demo corpus; 40 is what a 6-document,
single-domain (telecom router faults + billing) knowledge base actually needs. Scale it up by
adding more Fault/Symptom/Procedure entries as more SOPs are ingested — the schema doesn't change.

## SAD class -> v1 module

| SAD domain class (Figure 4) | v1 location |
|---|---|
| `Ticket`, `Attachment` | `libs/platform/db/models.py::Ticket, Attachment` (ORM); no separate domain contract — the ORM row *is* the record; `intake_api` creates them |
| `AudioTranscript`, `VisualSummary` | `libs/domain/contracts/media.py` (domain/wire contract) + `libs/platform/db/models.py::AudioTranscriptRow, VisualSummaryRow` (persistence) |
| `UnifiedTicketPayload` | `libs/domain/contracts/payload.py` (contract, `validate_payload()`) + `UnifiedPayloadRow` (persistence); built by `libs/domain/policy/fusion.py::fuse()`, only ever called from `aggregator_svc` |
| `TriageResult` | `libs/domain/contracts/analysis.py::TriageResult` + `TriageResultRow`; produced by `triage_svc` via `libs/domain/policy/{priority,routing}.py` |
| `Diagnosis`, `Citation` | `libs/domain/contracts/analysis.py` + `DiagnosisRow`/`CitationRow`; produced by `orchestrator_svc`, citations verified against `retrieval_svc`'s retrieved context |
| `DraftResponse` | `libs/domain/contracts/analysis.py::DraftResponse` (with `.diff()`) + `DraftResponseRow`; produced by `response_svc`, edited by `workspace_api` |
| `ActionRecommendation`, `ActionRegistryEntry` | `libs/domain/policy/action_selection.py` (both the pure-function `select()` and the `ActionRegistryEntry.permits()` domain object) + `ActionRecommendationRow`/`ActionRegistryEntryRow` |
| `ActionExecution` | `ActionExecutionRow`, written by `action_svc` |
| `AgentDecision` | `AgentDecisionRow`, written by `workspace_api` |
| `Delivery` | `DeliveryRow`, written by `delivery_gateway` (only after a persisted `agent_decision.id`) |

## Ports (§5.2.3) -> adapters (`libs/platform/registry.py::build_ports`)

| Port | Stub adapter | Real adapter |
|---|---|---|
| `TranscriberPort` | `StubTranscriber` | `FasterWhisperTranscriber` |
| `VisualExtractorPort` | `StubExtractor` | `OllamaVisionExtractor`, `HeuristicLedExtractor` (offline fallback) |
| `TextGeneratorPort` | `StubGenerator` | `OllamaGenerator` (semaphore + retry + circuit breaker) |
| `EmbedderPort` | `HashEmbedder` | `SentenceTransformerEmbedder` |
| `ClassifierPort` | `RuleOnlyClassifier` | `SklearnClassifier` -> `LlmClassifier` -> `RuleOnlyClassifier` (selection order, see `registry.py::_build_classifier`) |
| `VectorIndexPort` | `InMemoryVectorIndex` (same impl in every profile) | — |
| `GraphStorePort` | `InMemoryGraphStore` (same impl in every profile) | — |
| `ObjectStorePort` | `LocalObjectStore` (same impl in every profile) | `S3ObjectStore` |
| `EventBrokerPort` | `InProcessBroker` (`stub`/`cpu`) | `KafkaBroker` (`full`) |
| `ActionAdapterPort` | `SimulatedActionAdapter` (every profile — v1 never calls a real telecom OSS/BSS) | — |
| `MailGatewayPort` | `ConsoleMailGateway` (logs instead of sending) | — |

## Topics (Figure 9) -> handlers

All eleven topics from `libs/domain/contracts/events.py::Topics` are wired in
`runtime/wiring.py::build_app`. See `services/*/README.md` for each consumer's topic, table
ownership, and the requirement it implements — that mapping is intentionally kept next to the
code, not duplicated here.

## Source tree (§8.2.1) vs what v1 actually has

The tree matches the plan's §1 scaffold with one addition and one narrowing:

- **Added:** `libs/platform/auth.py` (shared static bearer-token auth for `workspace_api` and
  `admin_api` — not in the original scaffold, added because both services need it and it isn't a
  `services/*` package).
- **Narrowed:** `frontend/` is out of scope for v1 (stated in the plan) — `workspace_api`'s REST +
  WebSocket API is the full extent of the human-agent surface; there is no bundled UI.
