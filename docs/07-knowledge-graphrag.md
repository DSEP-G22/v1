# 07 — Knowledge chunking, embeddings, and GraphRAG

Produced by `notebooks/07_knowledge_and_graphrag.ipynb` (executed for real; all numbers below are
measured, not projected).

## Chunking-strategy comparison

Fixed 500/800/1200-char sliding-window chunking vs the real heading-aware chunker
(`services/knowledge_ingest/chunk.py::heading_aware_chunks`), averaged over the 6 seeded SOPs:

| strategy | avg chunks/doc | avg chunk length (chars) |
|---|---|---|
| fixed_500 | 3.2 | 424 |
| fixed_800 | 2.0 | 659 |
| fixed_1200 | 1.7 | 831 |
| **heading_aware** | **5.7** | **232** |

Heading-aware chunking produces more, shorter chunks than every fixed strategy because it never
merges two `##` sections together even when both fit under the size threshold — a short
"Symptoms" section becomes its own chunk instead of bleeding into "Diagnosis". This is exactly
the property that makes citations precise: retrieval points at one procedure, not a mixed bag of
two.

## Embedding model comparison

**Substitution, documented rather than silent:** the plan specifies MiniLM-L6 vs BGE-small; this
environment substitutes `all-MiniLM-L12-v2` for BGE-small (both small, CPU-fast, no large/gated
download) so the comparison methodology runs end to end here. Swap in
`BAAI/bge-small-en-v1.5` for a plan-faithful run where a larger download is acceptable.

Retrieval evaluation on 40 hand-written question -> chunk pairs (recall@5, MRR), against the real
heading-aware chunks from all 6 SOPs:

| model | recall@5 | MRR |
|---|---|---|
| all-MiniLM-L6-v2 | 0.90 | 0.668 |
| all-MiniLM-L12-v2 | 0.90 | 0.658 |

Both models perform near-identically at this corpus size (34 chunks) — not surprising; embedding
model choice matters far more once the corpus is large enough for near-duplicate chunks to
compete. MRR ~0.66 means the correct chunk is usually retrieved but not always ranked #1 — worth
revisiting the QA-pair phrasing (some questions paraphrase more loosely than others) once a
larger corpus makes ranking quality more consequential.

## Dense-only vs dense+graph expansion on fault prediction

This is the ADR-007 experiment. Measured on 7 realistic customer-phrased symptom/billing queries
against the real seeded graph (`config/seed/graph_seed.yaml`) and the real 6-doc chunk set:

| method | accuracy |
|---|---|
| dense-only (top-1 retrieved doc's plausible-fault set) | 1.00 |
| dense+graph (`InMemoryGraphStore.expand` fault nodes) | 0.86 |

**Read this honestly rather than picking the number that tells a nicer story.** Dense-only scores
higher here, not graph — because the accuracy metric is document-level and lenient (does the
top-retrieved *document* plausibly contain the expected fault, out of a per-document candidate
set), and with only 6 topically well-separated SOPs, document retrieval is an easy task at that
granularity.

What graph expansion actually contributes, that dense-only does not, is **fault-level precision**:
for every symptom-shaped query it resolves, it returns a small, specific candidate set (e.g.
`{fault_power_supply, fault_firmware_crashloop}`, not "somewhere in a ~1500-character document").
Its one miss is structural, not incidental: `fault_billing_dispute` has no `LedState`/`Symptom`
node feeding it in the seed graph, so keyword-expansion from a billing query can never reach it —
dense retrieval is the *only* path to billing content. That is the real argument for ADR-007's
dense-first-then-graph-expand order: graph narrows dense's output to a precise fault when
vocabulary lines up with the seed graph, and dense is the fallback for everything the graph has
no path to — not an afterthought bolted on top.

A same-granularity metric (graph's fault candidate set vs dense's single nearest-chunk mapped to
a fault) would be a fairer head-to-head than the document-level proxy used here — worth doing
once the knowledge base is large enough that document-level retrieval stops being trivial.

## Graph seed size

`config/seed/graph_seed.yaml` has ~40 nodes (see `02-architecture-mapping.md` for the exact
breakdown), not the "~200" the implementation plan describes for a larger demo — 40 is what the 6
seeded SOPs' fault space actually needs. Scale up by adding more `Fault`/`Symptom`/`Procedure`
entries as more SOPs are ingested; the schema (`LedState -EVIDENCE_FOR-> Symptom -INDICATES->
Fault -RESOLVED_BY-> Procedure -DEFINED_IN-> Document`, `Fault -PERMITS-> Action`, `Fault
-ESCALATES_TO-> ResolverQueue`) doesn't change.

## Regenerating

```
python notebooks/_build_notebooks.py --execute --only 07_knowledge_and_graphrag.ipynb
```

Needs the `[ml]` dependency group (`sentence-transformers`) and internet access on first run to
download the two MiniLM variants (cached under `~/.cache/huggingface` after that).
