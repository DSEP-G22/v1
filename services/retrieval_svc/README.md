# retrieval_svc

A library, not a broker consumer. `assemble_context()` does dense top-k retrieval (k=8) over the
vector index, graph expansion from entity-like terms extracted from the query text, and a
bounded context assembler (max ~2500 chars, deduped by chunk id) that mixes retrieved chunks with
graph-reached procedures. Called directly by `orchestrator_svc`.
