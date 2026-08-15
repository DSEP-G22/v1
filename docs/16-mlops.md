# 16. MLOps: Spark, DVC, MLflow

Three tools with three distinct jobs. Keeping them separate matters, because their
responsibilities overlap in conversation and not in practice.

| Tool | Job here | Not its job |
|---|---|---|
| **Spark** | Distributed ETL and feature engineering for retraining | Serving. No inference path touches Spark. |
| **DVC** | Versioning data and pipeline stages so a result is reproducible | Storing models. That is the registry. |
| **MLflow** | Experiment tracking and the model registry that the runtime reads | Orchestration. DVC drives the stages. |

## MLflow

### Running it

```bash
mlflow server --host 127.0.0.1 --port 5000 \
  --backend-store-uri sqlite:///v1_data/mlflow.db \
  --serve-artifacts \
  --artifacts-destination file:///D:/DSEP22/v1/v1_data/mlruns
```

`--serve-artifacts` is required. Without it the tracking API accepts runs but every artifact
upload returns HTTP 500, which surfaces as `too many 500 error responses` partway through
`log_model` and is easy to misread as the server being down. It is not; only the artifact proxy
is missing.

### Registry conventions

- One registered model per role: `cst-department-classifier`, and later `cst-sentiment-classifier`,
  `cst-port-detector`, `cst-embedder`.
- Aliases: `@champion` is what the runtime serves, `@candidate` is under evaluation. Versions are
  never deleted, so a rollback is an alias move rather than a retrain.
- Every run records the engine, the row counts, the Spark version and the number of human labels
  it consumed, so a model version can be traced to the interactions that produced it.

### How the runtime resolves a model

`libs/platform/mlflow_registry.py` resolves `models:/cst-department-classifier@champion`, caches
it per process, and stamps `name/version/run_id` on everything the model produces.

The resolver never takes the system down. If MLflow is unreachable, the alias is unset, or the
artefact will not load, it falls back to the local joblib artefact, then to the rule-based
classifier, and raises `MODEL_FALLBACK` so the degradation is visible. A support pipeline that
stopped triaging tickets because a tracking server was down would be the worse failure.

## DVC

`dvc.yaml` defines three stages: `prepare` builds the splits, `retrain` runs the Spark job, and
`evaluate` runs the end-to-end harness. `params.yaml` holds every tunable value, so changing a
parameter marks the dependent stages stale and an experiment is always attributable to the
parameters that produced it.

```bash
dvc repro              # rerun whatever is out of date
dvc repro retrain      # just the retrain
dvc dag                # show the stage graph
dvc metrics diff       # metrics against the previous commit
```

DVC tracks data and metrics; MLflow tracks runs and models. The overlap is deliberate: `dvc.lock`
records which data version produced a result, and the MLflow run records which model came out of
it.

## Spark

### What it does

`mlops/spark_retrain.py` reads the base corpus and the human-confirmed labels, tokenises and
vectorises them, fits a classifier, evaluates against a held-out split, and registers the result.

It is written against the DataFrame API and submitted identically whether the master is
`local[*]` or a standalone cluster, so the retraining path does not need rewriting when the
feedback table outgrows one machine.

```bash
# local
python -m mlops.spark_retrain --task department --promote

# cluster
docker compose --profile mlops up -d
spark-submit --master spark://spark-master:7077 mlops/spark_retrain.py --task department --promote
```

### The two engines, and why the default is not pure Spark ML

`--engine hybrid` (default) uses Spark for reading, joining, cleaning and vectorising, then fits
with scikit-learn on the driver. `--engine spark-ml` uses Spark ML end to end.

The default is hybrid because **Spark ML's iterative estimators do not work in this environment**.
This was established by bisection rather than assumed:

| Test | Result |
|---|---|
| Spark 4.2 on JDK 26 | Fails immediately: `ClassNotFoundException: jdk.internal.ref.Cleaner` |
| Spark 4.2 on JDK 17, CSV read and count | Works, 21,825 rows |
| Spark 4.2 on JDK 17, `groupBy` shuffle | Works, 12s |
| Spark 4.2 on JDK 17, `Tokenizer` and `HashingTF` | Work |
| Spark 4.2 on JDK 17, `StringIndexer.fit` | Works |
| Spark 4.2 on JDK 17, `LogisticRegression.fit` on **100 rows** | **Hangs indefinitely**, 54s CPU across 20 minutes wall clock |
| Adding `winutils.exe` and `HADOOP_HOME` | No change |
| Spark 3.5.3 (no such hang) on Python 3.12 | `Python worker exited unexpectedly (crashed)`; PySpark 3.5 predates 3.12 |

So the environment offers a choice between a Spark version whose ML estimators hang and one whose
Python workers will not start. The hybrid engine sidesteps both: Spark still does the distributed
work, and only the final optimisation, which at 25k rows by 65k sparse features fits comfortably
in driver memory, runs locally. On a Linux executor where the native BLAS path works,
`--engine spark-ml` is the better choice and needs no other change.

This is a genuine limitation, not a design preference. It is recorded here rather than hidden
because anyone reading `spark_retrain.py` will otherwise wonder why a Spark job calls
scikit-learn.

### Environment requirements

```bash
# Spark 4.x needs Java 17 or 21. Java 22+ fails with ClassNotFoundException on jdk.internal.ref.Cleaner.
export JAVA_HOME=/c/Users/<you>/AppData/Local/jdk17/jdk-17.0.20+8
export PATH="$JAVA_HOME/bin:$PATH"
```

The `winutils.exe` warning on Windows is noisy but harmless for this workload; it matters for
HDFS paths, which this job does not use.

## Docker

`docker-compose.yml` provides profiles rather than one monolithic stack:

```bash
docker compose --profile app up      # API and UI only
docker compose --profile mlops up    # MLflow, Spark master, 2 workers
docker compose --profile full up     # everything, plus Kafka and Postgres
```

The Spark services are a real standalone cluster, not a `local[*]` shim. Ollama is deliberately
not containerised: it needs the host GPU, so the API reaches it at `host.docker.internal:11434`.

**Docker was not exercised on this machine.** `com.docker.service` is stopped and starting it
requires elevation this session did not have, so the compose file and both Dockerfiles are written
and reviewed but unbuilt. Everything else in this document was run and verified.
