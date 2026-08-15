# 01, Setup

## Prerequisites

1. **Python 3.11+** (`python --version`). 3.13 works too but `faster-whisper` wheels can lag; fall
   back to 3.11 if installation fails. This repo was built and tested against **3.12.11** via
   [uv](https://docs.astral.sh/uv/).
2. **Ollama** installed and running for the `cpu`/`full` profiles:
   ```
   ollama serve
   ollama pull llama3.1:8b-instruct-q4_K_M
   ollama pull llava:7b
   curl http://localhost:11434/api/tags   # verify
   ```
   The `stub` profile (used for CI and by default in this environment) needs none of this.
3. The two datasets in `d:\DSEP22\data\` stay zipped in the repo; `notebooks/01_data_preparation.ipynb`
   extracts the Bitext CSV to `v1/data/raw/` (git-ignored). The Roboflow router-detection zip is
   read directly from the zip by `evaluation/datasets/roboflow_router.py`, never extracted in
   bulk.
4. Work from `d:\DSEP22\v1` as the working directory for every command below.

## Install

This repo uses [uv](https://docs.astral.sh/uv/) to manage the virtual environment (plain `pip`/
`venv` work identically if you prefer them, there is nothing uv-specific in the package itself).

```
uv venv --python 3.12.11 .venv
uv pip install -e ".[dev]" --python .venv
```

Add the ML dependency group when you reach notebooks 02+ or want real (non-stub) adapters:

```
uv pip install -e ".[ml]" --python .venv
```

`[train]` (torch/transformers/peft/jupyter/...) is only needed for notebook 03's LoRA track;
`[kafka]` only if you set `BROKER=kafka`.

## Profiles

`APP_PROFILE` selects a block from `config/settings.yaml` and, for `stub` specifically, forces
every `*_impl` setting to a stub regardless of what the YAML/`.env` say:

| Profile | ASR | VLM | LLM | Embedder | Broker | Use for |
|---|---|---|---|---|---|---|
| `stub` | stub | stub | stub | hash_stub | in-process | CI, this sandbox, fast local iteration |
| `cpu` | faster-whisper | ollama | ollama | sentence-transformers | in-process | local dev with Ollama running |
| `full` | faster-whisper | ollama | ollama | sentence-transformers | kafka | closer-to-production deployment |

Set it via environment variable or `.env` (copy `.env.example` to `.env` first):

```
cp .env.example .env
APP_PROFILE=stub python -c "from libs.platform.config import get_settings; print(get_settings().llm_impl)"
# -> stub
```

## First run

```
APP_PROFILE=stub pytest                       # 42 tests, ~10s, no network
python scripts/seed.py --reset                 # org, 3 users, action registry, 6 SOP docs ingested
APP_PROFILE=stub python -m runtime.demo_ticket  # text+audio+image ticket -> READY_FOR_AGENT in <10s
```

`runtime/demo_ticket.py` posts a text complaint plus the prototype's sample audio/image, polls
until the ticket reaches `READY_FOR_AGENT`, and prints the fused payload, triage result,
diagnosis, and draft reply.

To run the full single-process demo server (intake + all consumers + workspace/admin APIs on one
Uvicorn process):

```
APP_PROFILE=stub python -m runtime.local
# intake_api + workspace_api (mounted at /workspace) + admin_api (mounted at /admin) on :8000
```

Auth for `workspace_api`/`admin_api` is a static bearer token per role from `.env`
(`AUTH_TOKEN_AGENT`, `AUTH_TOKEN_LEAD`, `AUTH_TOKEN_ADMIN`), enough to exercise the authorization
checks without an IdP. Example:

```
curl -H "Authorization: Bearer dev-agent-token" http://localhost:8000/workspace/queue
```

## Agent workspace UI

The React workspace (SRS UI-1 to UI-7) is a **separate deployable** in `frontend/`, FastAPI does
not serve it. Run the two processes side by side. Node 20+ required.

Terminal 1, the API:

```
APP_PROFILE=stub python -m runtime.local        # :8000
```

Terminal 2, the UI:

```
cd frontend
npm install
npm run dev                                     # :5300
```

Open <http://127.0.0.1:5300> and sign in with `dev-agent-token`, `dev-lead-token` or
`dev-admin-token`.

In development Vite proxies `/workspace`, `/admin` and `/api` (including the WebSocket) to :8000,
so the browser sees one origin and CORS is not involved. For a deployed frontend, set
`VITE_API_BASE` to the API's URL at build time and add the frontend's origin to
`CORS_ALLOW_ORIGINS` on the API.

**Port note.** The dev server runs on 5300, not Vite's default 5173, because Windows reserves
5104-5203 for Hyper-V/WSL on this machine and binding there fails with `EACCES` even though
nothing is listening. Check your own machine with:

```
netsh interface ipv4 show excludedportrange protocol=tcp
```

Full detail in [14-ui.md](14-ui.md).

## With Ollama (`cpu` profile)

```
cp .env.example .env
# edit .env: APP_PROFILE=cpu
ollama serve &
ollama pull llama3.1:8b-instruct-q4_K_M
ollama pull llava:7b
python scripts/seed.py --reset
python -m runtime.demo_ticket
```

The first Ollama call after `ollama serve` starts loads the model and can take 30-90s, the
`OllamaGenerator`/`OllamaVisionExtractor` timeout defaults (`llm_timeout_s=60`) may need raising
for that first call; see `11-troubleshooting.md` #3.

## Windows notes

- SQLite runs in WAL mode with `check_same_thread=False`; each broker-handler invocation opens
  its own short-lived session (`libs/platform/db/session.py::session_scope`) rather than sharing
  one across threads.
- Multiple Python installs are common on Windows (Windows Store stub, MSYS/UCRT64, uv-managed).
  If `pip`/`python -m pip` fails with `ModuleNotFoundError: No module named 'encodings'` or
  similar, you've hit a broken/partial interpreter, use `uv venv --python <version>` to get a
  known-good uv-managed CPython rather than debugging the broken one.
- Long paths: keep the repo close to a drive root (e.g. `D:\DSEP22`), deeply nested checkouts
  combined with `.venv/Lib/site-packages/...` can exceed Windows' default path-length limit with
  some ML packages.
