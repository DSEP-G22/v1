# LLM Model Decision — RAG-Paired Diagnosis & Response Module

**Chosen model:** `qwen2.5:7b-instruct-q4_K_M` (Apache 2.0)
**Fallback (CPU-only / low resource):** `phi4-mini` (3.8B, MIT)

## Comparison of models

| Model | Params | License | JSON reliability | General quality | Verdict |
|---|---|---|---|---|---|
| **Qwen2.5-7B-Instruct** | 7B | Apache 2.0 | High | Best in mid tier (~74 MMLU) | **Chosen** — best balance |
| Llama 3.1 8B (old default) | 8B | Meta Community License | High (strongest schema compliance) | Adequate | Not wrong, just unjustified & unvalidated on this machine |
| Phi-4-mini-instruct | 3.8B | MIT | Good | Best reasoning-per-parameter at SLM scale | **Fallback** for CPU-only/no-GPU runs |
| Gemma 3 4B-IT | 4B | Gemma Terms | Best at SLM scale (100% JSON parse) | Trails Qwen2.5 at similar size | Good alternative fallback |
| Llama 3.2 3B | 3B | Meta Community License | Weak (47.8–56.5% JSON parse) | — | Rejected for this call site |
| SmolLM2 1.7B | 1.7B | Apache 2.0 | Unusable (26–56% parse, worse schema) | — | Rejected outright |

## Why Qwen2.5-7B-Instruct

Qwen2.5-7B-Instruct was selected against this project's specific call site (generate_json() in orchestrator_svc/response_svc, parsed against a Pydantic schema, behind a 60s timeout, with a CPU-only fallback path required by REQ-PERF-8):
Strong JSON schema reliability — scores well in independent Q4_K_M structured-output benchmarks, which matters most since the pipeline depends entirely on valid, schema-conformant JSON at this call site.
Strong general reasoning and multilingual quality — ~74 MMLU, the best in the mid (7–8B) tier evaluated.
Clean license — Apache 2.0, fully permissive for self-hosted redistribution.
Runs on the existing serving setup — works directly through the OllamaGenerator adapter, so no code changes are needed beyond the model tag.
Rejected candidates: SmolLM2 and other sub-2B models collapse on JSON schema compliance (as low as 26% parse rate), making them unusable for this call site regardless of general quality. Llama 3.2 3B has the same problem at a smaller scale (47.8–56.5% parse rate) — usable for lighter tasks elsewhere in the pipeline, but not for diagnosis/response generation.
