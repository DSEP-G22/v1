# 05 — LLM fine-tuning (Ollama)

Produced by `notebooks/03_intent_and_diagnosis_llm.ipynb`.

**Status: written, not executed.** This sandbox has no running Ollama server, no GPU, and no
Hugging Face authorization for the gated `meta-llama/Meta-Llama-3.1-8B-Instruct` weights Track B
needs. The notebook's code is complete and intended to run as-is on a machine that has those
three things — nothing in it is a stub. This document describes what it does and what running it
should produce; none of the metrics below are real measurements.

## Two tracks

### Track A — prompt engineering + few-shot, no training

Six few-shot examples sampled from the training split (`random_state=22`), formatted as
`Ticket: ... \n JSON: {"intent": ..., "department": ...}` pairs prepended to each classification
prompt, sent to `llama3.1:8b-instruct-q4_K_M` via `/api/chat` with `format: json`, `temperature:
0.1`. Evaluated on a 200-row sample of the notebook-01 validation split for intent accuracy,
department accuracy, and JSON-validity rate. This is the baseline v1 ships with — `llm_model` in
`.env` defaults to `llama3.1:8b-instruct-q4_K_M`, so a fresh install gets Track A behaviour with
zero extra steps beyond pulling the base model.

### Track B — QLoRA fine-tune

Instruction dataset built from `data/processed/{train,val}.csv` (notebook 01) in chat format:

```json
{"messages": [
  {"role": "system", "content": "You are a telecom customer-support intent and fault classifier. Respond as JSON: {\"intent\": str, \"fault\": str|null, \"department\": str}"},
  {"role": "user", "content": "<ticket text>"},
  {"role": "assistant", "content": "{\"intent\": \"...\", \"fault\": \"...\", \"department\": \"...\"}"}
]}
```

`fault` is populated only for telecom-supplement rows, via a fixed
`intent -> fault` lookup (`_TELECOM_INTENT_TO_FAULT` in the notebook) — Bitext rows get
`fault: null` since Bitext has no fault concept at all.

Hyperparameters (fixed, per the implementation plan): 4-bit QLoRA, `r=16, alpha=32, lr=2e-4`, 2
epochs, batch size 1 x grad-accum 16, `max_seq_len=1024`, base model
`meta-llama/Meta-Llama-3.1-8B-Instruct`.

Pipeline: `transformers` + `peft` (`prepare_model_for_kbit_training`, `LoraConfig`,
`get_peft_model`) -> `trl.SFTTrainer` -> `merge_and_unload()` (merged model, **not** the bare
adapter) -> `llama.cpp/convert_hf_to_gguf.py` -> `llama-quantize ... q4_K_M` -> a `Modelfile`
(`FROM <gguf>` + chat template + `PARAMETER temperature 0.2` + the system prompt) -> `ollama
create cst-diagnosis:v1 -f Modelfile`.

## Evaluation (what the notebook computes, once run)

Exact-match intent accuracy, department accuracy, and JSON-validity rate, Track A vs Track B, on
the same 200-row held-out sample, written to `evaluation/reports/llm_comparison.md`.

## Rollback

Set `llm_model=llama3.1:8b-instruct-q4_K_M` in `.env` (back to Track A) if Track B underperforms
or `cst-diagnosis:v1` was never successfully registered with `ollama create`. Nothing else in the
system depends on which model is configured — `libs/platform/models/llm.py::OllamaGenerator`
takes the model name from settings.

## Pitfalls (from the implementation plan, still accurate)

- 8B QLoRA needs ~10-12 GB VRAM — on a smaller GPU, swap `BASE_MODEL_ID` to
  `Qwen/Qwen2.5-3B-Instruct` or `meta-llama/Llama-3.2-3B-Instruct` and enable
  `gradient_checkpointing=True`.
- Llama 3.1 weights are gated on Hugging Face — `huggingface-cli login` and accept the licence
  before `AutoModelForCausalLM.from_pretrained` will succeed.
- GGUF conversion **must** use the merged model (`merge_and_unload()` output), not the raw
  adapter directory — converting the adapter alone produces a broken/incomplete GGUF.
- `bitsandbytes` on Windows needs a recent wheel; if it won't install, run this notebook in WSL2
  or Colab and copy the resulting GGUF back into `models/artifacts/`.
- `ollama create` failing on the GGUF almost always means either an unmerged adapter (see above)
  or an architecture `llama.cpp` doesn't support yet — check `llama.cpp`'s supported-architectures
  list against the base model.
