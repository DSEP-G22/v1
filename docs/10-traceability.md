# 10 — Traceability

Family-level REQ-* -> module -> test mapping (SRS_G22.md §4.1-4.12, Appendix B.5). Individual
requirement numbers within a family (e.g. REQ-ING-1 vs REQ-ING-15) are not separately listed —
they're implemented together by the same module and exercised together by the same tests; the
`services/*/README.md` for each module states the requirement range it implements.

| REQ family | Requirement | Module(s) | Test(s) |
|---|---|---|---|
| REQ-ING-1..15 | Ticket intake, magic-byte media validation, idempotency | `services/intake_api/` | `tests/integration/test_pipeline_stub.py`, `tests/integration/test_pipeline_to_aggregated.py` (both submit via `create_ticket`) |
| REQ-ASR-1..12 | Audio transcription, confidence, low-confidence flagging | `services/audio_svc/`, `libs/platform/models/asr.py` | `tests/integration/test_pipeline_to_aggregated.py`, `tests/degradation/test_adapter_failures.py::test_asr_failure_*`, `notebooks/06_asr_evaluation.ipynb` (real faster-whisper run) |
| REQ-VLM-1..12 | Visual extraction, template selection, confidence | `services/image_svc/`, `libs/platform/models/vlm.py` | `tests/integration/test_pipeline_to_aggregated.py`, `tests/degradation/test_adapter_failures.py::test_vlm_failure_*`, `notebooks/05_vlm_led_extraction.ipynb` (written, not executed — see doc 06) |
| REQ-FUS-1..10 | Fusion statechart, aggregation window, partial payloads | `services/aggregator_svc/`, `services/routing_svc/`, `libs/domain/policy/fusion.py` | `tests/unit/test_policy_fusion.py`, `tests/integration/test_pipeline_to_aggregated.py` (both the complete-set and window-timeout paths) |
| REQ-CLS-* | Department classification | `services/triage_svc/`, `libs/platform/models/classifier.py` | `tests/unit/test_policy_routing.py`, `notebooks/02_department_classifier.ipynb` (real training run, macro-F1 1.0) |
| REQ-PRI-* | Priority scoring | `libs/domain/policy/priority.py` | `tests/unit/test_policy_priority.py`, `notebooks/04_priority_and_sentiment.ipynb` (real calibration run) |
| REQ-FLT-1..14 | Retrieval, LLM diagnosis, citation verification | `services/orchestrator_svc/`, `services/retrieval_svc/` | `tests/degradation/test_adapter_failures.py::test_llm_failure_*`, `test_embedder_failure_*`, `notebooks/07_knowledge_and_graphrag.ipynb` (real retrieval eval), `notebooks/03_intent_and_diagnosis_llm.ipynb` (written, not executed) |
| REQ-RES-1..12 | Draft generation, compliance checks, action selection | `services/response_svc/`, `libs/domain/policy/{compliance,action_selection}.py` | `tests/unit/test_policy_compliance.py`, `tests/unit/test_policy_action_selection.py`, `tests/integration/test_pipeline_stub.py` |
| REQ-WKS-1..18 | Agent workspace: queue, lock, edit, approve, reject, execute action | `services/workspace_api/` | `tests/integration/test_workspace_flow.py` (lock -> approve -> delivery, real HTTP via `TestClient`) |
| REQ-BR-1 | Delivery only after a persisted approval | `services/delivery_gateway/` | `tests/integration/test_workspace_flow.py` (asserts `delivery.approval_id` matches a real `agent_decision.id`); `libs/platform/db/repositories.py::DeliveryRepo.create` raises if `approval_id` is falsy |
| REQ-SAFE-1 | No send/execute without recorded human approval | `services/delivery_gateway/`, `services/action_svc/` | same as REQ-BR-1; `DeliveryRow.approval_id` is a NOT NULL FK to `agent_decision.id` at the schema level, not just application logic |
| REQ-SAFE-3 | Low-confidence/failure flags cannot be suppressed | `libs/domain/contracts/payload.py` (`flags` field), `services/aggregator_svc/` | `tests/degradation/test_adapter_failures.py` (asserts `PARTIAL_PAYLOAD`/`LOW_ASR_CONFIDENCE` flags are actually set, not just that the ticket completes) |
| REQ-ONB-1..10 | Knowledge ingestion: chunking, embedding, vector/graph upsert | `services/knowledge_ingest/` | `scripts/seed.py` (real run — ingests all 6 SOPs), `notebooks/07_knowledge_and_graphrag.ipynb` (real chunking-strategy comparison) |
| REQ-PERF-12 | Department classifier macro-F1 >= 0.85 | `services/triage_svc/`, notebook 02 | **Met** — 1.0 on held-out test split, see `08-evaluation.md` |
| REQ-PERF-14..17 | ASR WER, VLM field accuracy, fault macro-F1, ROUGE-L | notebooks 05/06/03 | **Not measurable in this environment** — see `08-evaluation.md` for exactly why each one isn't |
| REQ-PERF-2..8 | End-to-end latency budgets (GPU-referenced) | full pipeline | **Not measurable without a GPU/Ollama** — see `08-evaluation.md` |

## Architecture-fitness requirements (SAD, not SRS)

| Rule | Test |
|---|---|
| No `services.X` imports `services.Y` (except the documented `retrieval_svc` library exception and `workspace_api`'s orchestration calls) | `tests/architecture/test_imports.py::test_no_service_imports_another_service` |
| Only `delivery_gateway` imports `MailGatewayPort` | `tests/architecture/test_imports.py::test_only_delivery_gateway_imports_mail_gateway_port` |
| Only `action_svc` imports `ActionAdapterPort` | `tests/architecture/test_imports.py::test_only_action_svc_imports_action_adapter_port` |
| Single-writer rule (SAD §5.2.2) — one service owns each table's mutations | `tests/architecture/test_single_writer.py`, ownership table in `libs/platform/db/ownership.py` |
| Degradation (G7): a broken ASR/VLM/LLM/embedder adapter still reaches `READY_FOR_AGENT` | `tests/degradation/test_adapter_failures.py` (5 tests: baseline + 4 broken-adapter scenarios) |

## What is *not* covered by an automated test

- `admin_api`'s users/action-registry/routing-rules CRUD and DLQ replay endpoints — built and
  manually smoke-tested during development, no dedicated `tests/integration` file.
- `knowledge_ingest`'s PDF path (`_read_text`'s `pypdf` branch) — only the `.md` path is exercised
  by `scripts/seed.py` and tests.
- The Kafka broker adapter (`libs/platform/broker/kafka.py`) — untestable without a running Kafka
  cluster; the in-process broker (used by every test) implements the identical `EventBrokerPort`.
- Real (non-stub) ASR/VLM/LLM adapters end-to-end through the full pipeline — `audio_svc`'s and
  `image_svc'`s real-adapter code paths are exercised directly by notebook 06 (faster-whisper) and
  documented but not executed for VLM/LLM (notebooks 03/05); no test submits a ticket through the
  full pipeline with `APP_PROFILE=cpu` and a live Ollama server.
