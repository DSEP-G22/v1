# 08, Evaluation

## Harness usage

```
APP_PROFILE=stub python -m evaluation.harness.run --n 100 --db v1_data/harness.db --report-dir evaluation/reports
```

Drives the pipeline in-process (`evaluation/harness/run.py`) over N synthetic multimodal tickets
(`evaluation/datasets/synthetic.py`), submitted through the exact same `create_ticket` entrypoint
`intake_api` uses, the "same code, different driver" seam of UC-8. Writes
`evaluation/reports/e2e_report.{json,csv,md}`. `notebooks/08_end_to_end_evaluation.ipynb` is a
thin wrapper that calls `evaluation.harness.run.run()` directly and is executed for real (not a
stub), see below for why its *numbers* still come with a load-bearing caveat.

## Metric definitions (`evaluation/harness/metrics.py`)

| Metric | Definition |
|---|---|
| `department_accuracy` / `department_macro_f1` | ticket.department vs the synthetic dataset's expected department |
| `fault_top1_accuracy` / `fault_top3_accuracy` | expected fault in the top-1 / top-3 of `[diagnosis.fault] + diagnosis.alternatives` |
| `citation_verification_rate` | mean of `citation.verified` across diagnoses that have >=1 citation |
| `json_validity_rate` | fraction of tickets that produced a `diagnosis` row at all (didn't fall back to the LLM-unavailable default) |
| stage latency p50/p95 | derived from `ticket_state_transition` timestamps, free instrumentation, no extra code needed in each service |

## Current numbers (real run, `APP_PROFILE=stub`, n=100)

From `evaluation/reports/e2e_report.md` / `metrics.jsonl`:

- **100/100 tickets completed**, wall time 4.5s, **throughput ~22 tickets/s**
- Department accuracy 0.59 (macro-F1 0.53), fault top-1/top-3 accuracy 0.23, JSON validity 1.0,
  citation verification rate NaN

**Read every one of these numbers through the stub-profile lens, or they mislead:**

- `RuleOnlyClassifier` (a small keyword table), not the notebook 02 sklearn artefact, is forced
  under `APP_PROFILE=stub` for CI determinism, 0.59 accuracy reflects the keyword table, not the
  trained classifier (which scored macro-F1 1.0 on real held-out data, see
  `04-department-classifier.md`).
- `StubGenerator` returns the **same fixed canned diagnosis** (`fault_power_supply`, citation
  `chunk_id="c1"`) for every single ticket regardless of content. Fault accuracy of 0.23 is just
  "how many of the 14 synthetic ticket templates happen to expect `fault_power_supply`", it is
  not a measurement of diagnostic quality.
- `citation_verification_rate` is NaN because the stub's canned `chunk_id="c1"` never matches a
  real retrieved chunk id, so `orchestrator_svc.verify_citations` drops it every time and no
  diagnosis ever has a *verified* citation to average over.

**What this run does validate**: pipeline reliability and throughput at 100-ticket scale, the
metrics-computation code itself (correct, tested against real DB state via
`ticket_state_transition`), and that every stage completes without deadlock/exception under
concurrent broker load. It is a systems-correctness result, not a model-quality result.

### To get model-quality numbers

Re-run with `APP_PROFILE=cpu` (or `full`), Ollama running with `llama3.1:8b-instruct` (or
`cst-diagnosis:v1` from notebook 03) pulled, and `models/artifacts/department_clf.joblib` present
(notebook 02's real output, already committed by this run). Fault accuracy and citation
verification then measure the actual LLM/retrieval pipeline.

## SRS §5.1 performance budget, what this environment can and cannot check

SRS §5.1's latency targets are explicitly GPU-referenced (REQ-PERF-2 through -7: text-only ticket
<=10s p95, image ticket <=25s p95, audio+image+text <=45s p95/90s p99; REQ-PERF-8 relaxes all of
these by 5x for CPU-only fallback). This sandbox has neither a GPU nor a running Ollama server, so
**no real REQ-PERF-2..8 measurement was possible here**, the stub-profile harness numbers above
(sub-5-second end-to-end for 100 tickets combined) reflect zero real ASR/VLM/LLM compute and
cannot be compared against those budgets; doing so would be comparing against a different
workload entirely.

What *is* verifiable without a GPU: REQ-PERF-12 (department macro-F1 >= 0.85), **met**, 1.0 on
real held-out data (`04-department-classifier.md`). REQ-PERF-14 (ASR WER <= 0.20), **not
measurable**, no labelled reference transcript exists for either sample audio file
(`06-vlm-and-asr.md`). REQ-PERF-15/16/17 (VLM field accuracy, fault macro-F1, ROUGE-L), **not
measurable** without a running Ollama server (notebooks 03/05 written, not executed).
REQ-PERF-9/10/11/18 (throughput, queue rendering, WS push latency, concurrent sessions), not
exercised by this harness at all; it drives `intake_api`/pipeline only, not `workspace_api`'s
queue-rendering path under load.

Per REQ-PERF-20, all of REQ-PERF-12..17 are explicitly provisional pending baseline measurement,
this document *is* that first end-to-end evaluation run for the pieces measurable without a GPU;
the rest needs a follow-up run with Ollama available.
