# v1 — reference implementation

Reference implementation of the multimodal customer-support triage system specified in
`docs/SRS_G22.md` and `docs/SAD_G22.md`. See `docs/00-IMPLEMENTATION-PLAN.md` for the full build
plan and `docs/02-architecture-mapping.md` for the SAD → v1 module mapping and deviation table.

Quick start: see `docs/01-setup.md`.

```
uv venv
uv pip install -e ".[dev]"
APP_PROFILE=stub pytest
APP_PROFILE=stub python -m runtime.demo_ticket
```
