# orchestrator_svc

Implements REQ-FLT-1..14: consumes `tickets.triaged`, calls `retrieval_svc.assemble_context`,
then `TextGeneratorPort.generate_json` with `models/prompts/llm/diagnosis.txt`. Citations whose
`chunk_id` was not actually in the retrieved context are dropped (`verify_citations`); if any
were dropped, or confidence is below `diagnosis_min_confidence`, `needs_human_diagnosis` is set.
Writes `diagnosis` + `citation`, publishes `tickets.diagnosed`. Owns `diagnosis` and `citation`.
