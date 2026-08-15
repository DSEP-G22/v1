"""Spark retraining job for the department classifier.

Reads human-confirmed labels from `training_example`, joins them with the original Bitext and
telecom training corpus, trains a Spark ML pipeline, and registers the result in MLflow. The
new model is promoted to `@champion` only if it beats the incumbent on a held-out split.

Why Spark for a dataset this size: the job is written against the DataFrame API and submitted
the same way whether it runs on `local[*]` or against a standalone cluster, so the retraining
path does not have to be rewritten when the feedback table outgrows one machine. Today the
corpus is ~25k rows and a single executor handles it in seconds; the point is that the code
does not change when it is 25 million.

Run locally:
    python -m mlops.spark_retrain --task department

Submit to a cluster:
    spark-submit --master spark://spark-master:7077 mlops/spark_retrain.py --task department
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_METRIC = "macro_f1"
REGISTERED_MODEL = "cst-department-classifier"


def build_spark(app_name: str = "cst-retrain"):
    from pyspark.sql import SparkSession

    master = os.environ.get("SPARK_MASTER", "local[*]")
    builder = (
        SparkSession.builder.appName(app_name)
        .master(master)
        # The driver holds the whole corpus when collecting metrics, so give it room; these are
        # ignored when a cluster manager supplies its own resource configuration.
        .config("spark.driver.memory", os.environ.get("SPARK_DRIVER_MEMORY", "2g"))
        .config("spark.sql.shuffle.partitions", os.environ.get("SPARK_SHUFFLE_PARTITIONS", "8"))
        .config("spark.ui.showConsoleProgress", "false")
    )
    return builder.getOrCreate()


def load_base_corpus(spark, path: Path):
    """The original labelled corpus produced by notebook 01."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run notebooks/01_data_preparation.ipynb first, or `dvc repro prepare`."
        )
    return (
        spark.read.option("header", True).option("multiLine", True).option("escape", '"').csv(str(path))
        .select("text", "department")
        .na.drop()
    )


def load_feedback(spark, database_url: str, task: str):
    """Human-confirmed labels harvested from agent decisions.

    Read through pandas rather than Spark's JDBC source because the operational store is SQLite
    in this configuration and has no JDBC driver on the classpath. On Postgres this becomes a
    `spark.read.jdbc(...)` call and nothing else changes.
    """
    from sqlalchemy import create_engine, text as sql_text

    engine = create_engine(database_url)
    query = sql_text(
        "SELECT id, text, corrected AS department, is_correction, created_at "
        "FROM training_example WHERE task = :task AND consumed_by_run IS NULL"
    )
    import pandas as pd

    with engine.connect() as conn:
        pdf = pd.read_sql(query, conn, params={"task": task})

    if pdf.empty:
        return None, []

    ids = pdf["id"].tolist()
    # Corrections are the expensive signal (a human took the trouble to disagree), so they carry
    # more weight than confirmations. Without this the loop learns almost nothing from rare fixes.
    pdf["weight"] = pdf["is_correction"].apply(lambda c: 3.0 if c else 1.0)
    sdf = spark.createDataFrame(pdf[["text", "department", "weight"]])
    return sdf, ids


def build_pipeline(num_features: int = 1 << 16):
    """Spark ML pipeline: tokenise, hash, IDF-weight, then multinomial logistic regression.

    Used when `--engine spark-ml` is selected and the environment can run Spark's iterative
    estimators. See `fit_sklearn_on_spark_features` for the fallback and the reason it exists.
    """
    from pyspark.ml import Pipeline
    from pyspark.ml.classification import LogisticRegression
    from pyspark.ml.feature import HashingTF, IDF, StringIndexer, Tokenizer

    tokenizer = Tokenizer(inputCol="text", outputCol="tokens")
    hashing = HashingTF(inputCol="tokens", outputCol="raw_features", numFeatures=num_features)
    idf = IDF(inputCol="raw_features", outputCol="features", minDocFreq=2)
    label_indexer = StringIndexer(inputCol="department", outputCol="label", handleInvalid="keep")
    classifier = LogisticRegression(
        featuresCol="features",
        labelCol="label",
        weightCol="weight",
        maxIter=40,
        regParam=0.02,
        elasticNetParam=0.0,
    )
    return Pipeline(stages=[tokenizer, hashing, idf, label_indexer, classifier])


def fit_sklearn_on_spark_features(training, held_out) -> tuple:
    """Distribute the ETL and feature work in Spark, then fit with scikit-learn on the driver.

    This exists because Spark ML's iterative estimators (LogisticRegression, IDF) hang on this
    machine: PySpark 4.2 on Windows with JDK 17 blocks inside the native BLAS path even on a
    hundred rows, and PySpark 3.5, which does not have that problem, cannot run Python workers
    on Python 3.12. Verified by bisection, not assumed. See docs/16-mlops.md.

    The split is deliberate rather than a workaround for its own sake. Spark still does what
    Spark is for here, which is reading, joining, cleaning and vectorising the corpus in
    parallel; only the final optimisation runs locally, and at 25k rows by 65k sparse features
    that fits comfortably in driver memory. When the corpus outgrows the driver, switch to
    `--engine spark-ml` on a Linux executor, where the native path works.
    """
    import numpy as np
    from scipy.sparse import csr_matrix
    from sklearn.linear_model import LogisticRegression as SkLogisticRegression
    from sklearn.metrics import accuracy_score, f1_score

    def to_matrix(df):
        rows = df.select("features", "department", "weight").collect()
        indptr, indices, data = [0], [], []
        labels, weights = [], []
        for row in rows:
            vec = row["features"]
            indices.extend(vec.indices.tolist())
            data.extend(vec.values.tolist())
            indptr.append(len(indices))
            labels.append(row["department"])
            weights.append(float(row["weight"]))
        size = rows[0]["features"].size if rows else 0
        matrix = csr_matrix((data, indices, indptr), shape=(len(rows), size))
        return matrix, np.array(labels), np.array(weights)

    x_train, y_train, w_train = to_matrix(training)
    x_test, y_test, _ = to_matrix(held_out)

    model = SkLogisticRegression(max_iter=400, C=10.0, class_weight="balanced", n_jobs=-1)
    model.fit(x_train, y_train, sample_weight=w_train)

    predicted = model.predict(x_test)
    metrics = {
        "macro_f1": float(f1_score(y_test, predicted, average="macro", zero_division=0)),
        "accuracy": float(accuracy_score(y_test, predicted)),
    }
    return model, metrics


def build_feature_pipeline(num_features: int = 1 << 16):
    """Spark-side feature engineering, shared by both engines."""
    from pyspark.ml import Pipeline
    from pyspark.ml.feature import HashingTF, StringIndexer, Tokenizer

    return Pipeline(stages=[
        Tokenizer(inputCol="text", outputCol="tokens"),
        HashingTF(inputCol="tokens", outputCol="features", numFeatures=num_features),
        StringIndexer(inputCol="department", outputCol="label", handleInvalid="keep"),
    ])


def evaluate(predictions) -> dict[str, float]:
    from pyspark.ml.evaluation import MulticlassClassificationEvaluator

    metrics = {}
    for name, metric in (("macro_f1", "f1"), ("accuracy", "accuracy")):
        metrics[name] = MulticlassClassificationEvaluator(
            labelCol="label", predictionCol="prediction", metricName=metric
        ).evaluate(predictions)
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description="Spark retraining for the department classifier")
    parser.add_argument("--task", default="department")
    parser.add_argument("--trigger", default="manual", choices=["manual", "scheduled", "threshold"])
    parser.add_argument("--min-new-examples", type=int, default=1,
                        help="skip the run unless at least this many unconsumed examples exist")
    parser.add_argument("--promote", action="store_true",
                        help="register and alias as @champion when the candidate wins")
    parser.add_argument("--engine", default="hybrid", choices=["hybrid", "spark-ml"],
                        help="hybrid: Spark does ETL and features, scikit-learn fits (default, works "
                             "everywhere). spark-ml: pure Spark ML, needs a working native BLAS.")
    parser.add_argument("--output", default=str(REPO_ROOT / "evaluation" / "reports" / "retrain_last.json"))
    args = parser.parse_args()

    from libs.platform.config import get_settings

    settings = get_settings()
    database_url = settings.database_url

    import mlflow

    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_experiment("cst/retrain")

    print("[1/8] starting spark session", flush=True)
    spark = build_spark()
    spark.sparkContext.setLogLevel("ERROR")
    print(f"[2/8] spark {spark.version} on {spark.sparkContext.master}", flush=True)

    base = load_base_corpus(spark, REPO_ROOT / "data" / "processed" / "train.csv")
    from pyspark.sql import functions as F

    base = base.withColumn("weight", F.lit(1.0))

    print("[3/8] reading feedback labels", flush=True)
    feedback, feedback_ids = load_feedback(spark, database_url, args.task)
    n_new = len(feedback_ids)
    print(f"[4/8] base corpus: {base.count()} rows | new human labels: {n_new}", flush=True)

    if n_new < args.min_new_examples:
        print(f"only {n_new} new example(s), threshold is {args.min_new_examples}. Nothing to do.")
        spark.stop()
        return 0

    training = base.unionByName(feedback) if feedback is not None else base

    test_path = REPO_ROOT / "data" / "processed" / "test.csv"
    held_out = load_base_corpus(spark, test_path).withColumn("weight", F.lit(1.0))

    from libs.platform.db.repositories import RetrainRunRepo, TrainingExampleRepo
    from libs.platform.db.session import build_engine, session_scope

    engine = build_engine(database_url)
    with session_scope(engine) as session:
        run_row = RetrainRunRepo(session).create(
            task=args.task,
            status="RUNNING",
            trigger=args.trigger,
            examples_total=training.count(),
            examples_new=n_new,
            metric_name=DEFAULT_METRIC,
        )
        run_id = run_row.id

    result: dict = {"run_id": run_id, "task": args.task, "examples_new": n_new}

    try:
        with mlflow.start_run(run_name=f"retrain-{args.task}-{datetime.now(timezone.utc):%Y%m%d%H%M}") as active:
            mlflow.log_params({
                "task": args.task,
                "trigger": args.trigger,
                "base_rows": base.count(),
                "feedback_rows": n_new,
                "spark_version": spark.version,
                "spark_master": spark.sparkContext.master,
            })

            mlflow.log_param("engine", args.engine)
            print(f"[5/8] fitting ({args.engine})", flush=True)

            if args.engine == "spark-ml":
                model = build_pipeline().fit(training)
                print("[6/8] evaluating", flush=True)
                metrics = evaluate(model.transform(held_out))
            else:
                # Spark vectorises both splits, then the fit happens on the driver.
                features = build_feature_pipeline().fit(training)
                model, metrics = fit_sklearn_on_spark_features(
                    features.transform(training), features.transform(held_out)
                )
                print("[6/8] evaluated", flush=True)
            mlflow.log_metrics(metrics)
            print(f"candidate: {metrics}")

            baseline = _incumbent_metric(mlflow, REGISTERED_MODEL, DEFAULT_METRIC)
            candidate = metrics[DEFAULT_METRIC]
            promoted = False

            if args.promote:
                print("[7/8] logging model to registry", flush=True)
                if args.engine == "spark-ml":
                    import mlflow.spark

                    mlflow.spark.log_model(model, name="model", registered_model_name=REGISTERED_MODEL)
                else:
                    import mlflow.sklearn

                    mlflow.sklearn.log_model(model, name="model", registered_model_name=REGISTERED_MODEL)
                # Promotion is a comparison, never automatic: a retrain that makes the model worse
                # must not reach production just because it ran more recently.
                if baseline is None or candidate > baseline:
                    promoted = _set_champion(REGISTERED_MODEL)
                    print(f"promoted to @champion ({candidate:.4f} > {baseline if baseline is not None else 'no incumbent'})")
                else:
                    print(f"NOT promoted: {candidate:.4f} does not beat incumbent {baseline:.4f}")

            mlflow.log_metric("promoted", 1.0 if promoted else 0.0)
            result.update({
                "mlflow_run_id": active.info.run_id,
                "baseline_metric": baseline,
                "candidate_metric": candidate,
                "promoted": promoted,
                **metrics,
            })

        with session_scope(engine) as session:
            RetrainRunRepo(session).finish(
                run_id,
                status="SUCCEEDED",
                baseline_metric=result.get("baseline_metric"),
                candidate_metric=result.get("candidate_metric"),
                promoted=result.get("promoted", False),
                mlflow_run_id=result.get("mlflow_run_id"),
            )
            # Examples are marked consumed only after a successful run, so a crash leaves them
            # available for the next attempt rather than silently discarding the labels.
            if feedback_ids:
                TrainingExampleRepo(session).mark_consumed(feedback_ids, run_id)

    except Exception as exc:  # noqa: BLE001 - the failure must be recorded, then re-raised
        with session_scope(engine) as session:
            RetrainRunRepo(session).finish(run_id, status="FAILED", notes=str(exc)[:500])
        spark.stop()
        raise

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"wrote {out}")

    spark.stop()
    return 0


def _incumbent_metric(mlflow, name: str, metric: str) -> float | None:
    """The champion's score on the same metric, or None when there is no champion yet."""
    try:
        client = mlflow.tracking.MlflowClient()
        version = client.get_model_version_by_alias(name, "champion")
        run = client.get_run(version.run_id)
        return run.data.metrics.get(metric)
    except Exception:  # noqa: BLE001 - no registry, no model, or no alias: all mean "no incumbent"
        return None


def _set_champion(name: str) -> bool:
    try:
        import mlflow

        client = mlflow.tracking.MlflowClient()
        versions = client.search_model_versions(f"name='{name}'")
        if not versions:
            return False
        latest = max(versions, key=lambda v: int(v.version))
        client.set_registered_model_alias(name, "champion", latest.version)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"could not set champion alias: {exc}")
        return False


if __name__ == "__main__":
    raise SystemExit(main())
