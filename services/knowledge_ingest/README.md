# knowledge_ingest

Implements REQ-ONB-1..10: parses Markdown/PDF/TXT SOP documents into heading-aware chunks
(~800 chars, 100 overlap), embeds them via `EmbedderPort`, upserts the vector index, and writes
`knowledge_document`/`knowledge_chunk`. Returns a data-quality report (chunk count, average
length, too-short/too-long counts, candidate entities). Not a broker consumer — called directly
by `scripts/seed.py` and (once built) `admin_api`'s onboarding endpoint. Owns `knowledge_document`
and `knowledge_chunk`.
