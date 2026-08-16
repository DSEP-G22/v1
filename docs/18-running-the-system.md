# 18, Running the whole system

Start-to-finish bringup: the app tier you need for day-to-day work, and the infrastructure tier
(MLflow, Spark, Kafka, Postgres) that only matters when you are exercising the MLOps path.

`01-setup.md` covers installing dependencies and the first run. This document covers running
everything at once, and the failures that actually occur when you do. `16-mlops.md` explains what
the MLOps components are *for*; this one explains how to get them up.

---

## Tiers

The system splits into three tiers that are started independently. Nothing forces you to run all
of them, and most work only needs the first.

| Tier | Components | Needed for |
|---|---|---|
| App | API (`:8000`), UI (`:5300`) | Everything. Submitting tickets, the agent workspace. |
| Models | Ollama (`:11434`) | Real diagnosis and draft replies. Optional on `stub`. |
| Infrastructure | MLflow, Spark, Kafka, Postgres | Retraining, experiment tracking. Not used at request time. |

The app tier does **not** depend on the infrastructure tier. A ticket flows end to end with
MLflow and Spark stopped — they are the training path, not the serving path.

---

## 1. App tier

Two processes, run from `d:\DSEP22\v1`. This is the one you need.

Terminal 1, the API:

```bash
python -m runtime.local          # :8000, intake + workspace + admin on one process
```

Terminal 2, the UI:

```bash
cd frontend && npm run dev       # :5300
```

Open <http://127.0.0.1:5300>, sign in with `dev-agent-token`.

### Before the first run

`.env` must exist and the database must be seeded, or **sign-in fails with "Sign in failed.
Check your credentials"** even when the token is correct. That message is deliberately identical
for a bad token and an empty database (UI-1 anti-enumeration), so it does not distinguish the
two — see `11-troubleshooting.md`.

```bash
cp .env.example .env             # then set APP_PROFILE (see below)
python scripts/seed.py --reset   # org, 3 users, action registry, 6 SOP documents
```

`scripts/seed.py` prints the customer ID it creates. The submission page needs it, so keep it:

```
seeded organization 01M05M32QK13J6ECST01YZPWZM, 3 users, 1 customer, 5 action registry entries
```

To recover it later:

```bash
python -c "import sqlite3;print(list(sqlite3.connect('v1_data/app.db').execute('select id,name from customer')))"
```

### Choosing a profile

`APP_PROFILE` in `.env` decides which adapters are real. The difference is not cosmetic:

| Profile | Audio | Diagnosis / reply | Needs |
|---|---|---|---|
| `stub` | **Not transcribed.** Replaced with a fixed sentence. | Rule-based | Nothing |
| `cpu` | Real Whisper transcription | Real LLM | Ollama running |
| `full` | Real Whisper transcription | Real LLM | Ollama + Kafka |

Use `stub` for tests and plumbing changes; it is hermetic and never touches the network. Use
`cpu` for anything where the *output* matters — on `stub` a voice message is discarded and
replaced by `"Stub transcript: customer reports the router's power light is red..."`, which
looks like a working pipeline while transcribing nothing.

> **Re-seed when you change profile.** The vector index is written by whichever embedder the
> profile selects (`hash_stub` on `stub`, `sentence_transformers` on `cpu`), and the loader
> refuses to mix them:
>
> ```
> EmbeddingModelMismatch: vector index at v1_data\vectors.json was built with a
> different embedding_model; rebuild it
> ```
>
> Fix: `rm v1_data/vectors.json && python scripts/seed.py --reset`.

---

## 2. Ollama

Needed by `cpu` and `full`. The API degrades loudly without it — the orchestrator logs
`diagnosis generation failed` with `WinError 10061` and tickets still reach `READY_FOR_AGENT`,
but with no diagnosis.

```bash
ollama serve
curl http://localhost:11434/api/tags     # verify
```

On Windows, `ollama` is often not on `PATH` even when the service runs. It installs to
`%LOCALAPPDATA%\Programs\Ollama\ollama.exe`; call it by full path or add that directory to
`PATH`.

The `cpu` profile sets `llm_model: gpt-oss:120b-cloud` in `config/settings.yaml` — a **cloud**
model, so `ollama list` showing no local models is not a problem as long as cloud access is
configured. To run fully offline, pull a local model and point `llm_model` at it:

```bash
ollama pull llama3.1:8b-instruct-q4_K_M   # ~4.7 GB
```

---

## 3. Infrastructure tier

Only needed for retraining and experiment tracking. Requires Docker Desktop running.

```bash
docker compose --profile mlops up -d    # MLflow + Spark master + 2 workers
docker compose --profile full up -d     # the above plus Kafka and Postgres
```

Verify, rather than trusting `Up` — a container can be running and still not serving:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:5000/health   # MLflow -> 200
curl -s http://localhost:8090/ | grep -o 'Alive Workers.\{0,20\}'       # Spark  -> 2
docker exec cst-v1-postgres-1 pg_isready -U cst                         # -> accepting connections
docker exec cst-v1-kafka-1 kafka-broker-api-versions.sh --bootstrap-server localhost:9092
```

| Service | URL |
|---|---|
| MLflow | <http://localhost:5000> |
| Spark master UI | <http://localhost:8090> (8080 is taken by the containerised UI) |
| Postgres | `localhost:5432`, user `cst` |
| Kafka | `localhost:9092` |

### Port conflict with the app tier

The `app` and `full` profiles publish the containerised API on `:8000` — the same port
`python -m runtime.local` binds. Run one or the other, not both. To keep the local API and still
get the infrastructure, start only the services you need:

```bash
docker compose --profile full up -d postgres kafka mlflow spark-master spark-worker
```

---

## Known issues

### Bitnami images no longer resolve

`bitnami/spark:3.5` and `bitnami/kafka:3.7` were removed from Docker Hub when Broadcom moved the
Bitnami catalogue in 2025:

```
failed to resolve reference "docker.io/bitnami/spark:3.5": not found
```

`docker-compose.yml` pins `bitnamilegacy/*` instead, which holds the same images and keeps the
`SPARK_MODE` / `SPARK_MASTER_URL` env-var contract. `apache/spark` is *not* a drop-in replacement:
it uses different entrypoints and would require rewriting those service definitions.

### Image pulls fail part-way

The Spark image is ~865 MB and pulls fail intermittently on a slow link:

```
short read: expected 865400792 bytes but got 629022364: unexpected EOF
failed to copy: httpReadSeeker: ... TLS handshake timeout
```

Not fatal, and not worth diagnosing — re-run the same `up -d`. Docker resumes completed layers,
so each retry starts further along.

### Local pyspark cannot drive the containerised cluster

The venv has **pyspark 4.2**; the cluster runs **Spark 3.5**. A 4.x driver cannot submit to a 3.5
master. Either run the job locally on `local[*]` (which is what `mlops/spark_retrain.py` does by
default, and is fine at this corpus size), or submit from inside the master container, where the
repo is mounted read-only at `/opt/project`.

Submitting inside the container needs three things that are easy to miss:

```bash
docker exec -u root cst-v1-spark-master-1 bash -lc '
  cd /opt/project && \
  export HOME=/tmp \
         HADOOP_USER_NAME=spark \
         MLFLOW_TRACKING_URI=http://mlflow:5000 \
         PYSPARK_PYTHON=/opt/bitnami/python/bin/python && \
  /opt/bitnami/spark/bin/spark-submit \
    --master spark://spark-master:7077 \
    --conf spark.jars.ivy=/tmp/.ivy2 \
    mlops/spark_retrain.py --task department'
```

* `spark-submit` is not on `PATH`; it lives at `/opt/bitnami/spark/bin/spark-submit`.
* `HOME` is unset under `docker exec`, so Ivy resolves `?/.ivy2` and dies with
  `basedir must be absolute`. `--conf spark.jars.ivy` alone is not enough.
* Without a passwd entry, Hadoop's `UserGroupInformation` throws
  `KerberosAuthException: failure to login ... invalid null input: name`. Hence `-u root` and
  `HADOOP_USER_NAME`.
* The Spark image has no `mlflow`. Install `mlflow-skinny` into the container first — the full
  `mlflow` package is large enough that the download times out on a slow link:

  ```bash
  docker exec -u root cst-v1-spark-master-1 \
    /opt/bitnami/python/bin/pip install --retries 10 --timeout 120 \
    mlflow-skinny pydantic pydantic-settings PyYAML
  ```

**This submit path is documented but not verified end to end.** The cluster accepts the job and
the driver starts; the run above was stopped at the Hadoop login error rather than carried to a
completed run. `local[*]` is the exercised path — see `16-mlops.md`.

### Sample audio is silent

`ingestion-pipeline-prototype/data/sample_audio/sample_call.wav` is two seconds of silence. It
transcribes to an empty string and flags `LOW_ASR_CONFIDENCE` — correct behaviour on an empty
input, not an ASR fault. `audio.mp3` in the same directory is ~11 minutes of real speech and
transcribes correctly.

---

## Teardown

```bash
docker compose --profile full down          # keep volumes
docker compose --profile full down -v       # also drop MLflow runs, Postgres and Kafka data
```

The local API and UI are foreground processes; Ctrl-C each. Nothing is left running afterwards
except Ollama, which is a background service.
