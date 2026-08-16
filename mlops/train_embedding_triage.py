"""Train triage heads on frozen sentence embeddings.

This is the second of the two triage approaches, and the cheaper one. Rather than fine-tuning a
transformer, it encodes each fused payload once with a frozen sentence-transformer and fits plain
logistic-regression heads on the resulting vectors.

    fused_text -> [frozen MiniLM encoder] -> 384-d vector -> LogisticRegression -> department
                                                          -> LogisticRegression -> priority band
                                                          -> LogisticRegression -> sentiment

Why bother, when `train_distilled_triage.py` already exists:

*   **It trains in seconds on a CPU, not minutes.** Embeddings are computed once and cached, so
    re-fitting after a labelling run costs almost nothing. That matters for the continuous-learning
    loop, where retraining is triggered by accumulated agent corrections.
*   **It is a real baseline.** Fine-tuning 66M parameters is only worth its cost if it beats a
    linear model on frozen features. Without this number, the DistilBERT accuracy has nothing to
    be compared against and "0.85" cannot be called good or bad.
*   **It reuses `EmbedderPort`.** The same encoder already serves retrieval, so serving this adds
    no new model to the deployment.

The trade-off is that the encoder never adapts to the domain. It has no way to learn that
`[AUDIO:...]` marks lower-trust evidence, or what a DSL sync failure is, because its weights are
frozen. That is exactly the gap fine-tuning is supposed to close, and the comparison measures it.

    python -m mlops.train_embedding_triage
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mlops.train_distilled_triage import (  # noqa: E402
    BANDS,
    DEPARTMENTS,
    SENTIMENTS,
    load_dataset,
    split_dataset,
)

DATASET = REPO_ROOT / "data" / "processed" / "distillation_dataset.jsonl"
ARTIFACT_DIR = REPO_ROOT / "models" / "artifacts" / "embedding_triage"
CACHE = REPO_ROOT / "data" / "processed" / "embedding_cache.npz"


def encode(texts: list[str], model_name: str, batch_size: int = 64):
    """Encode with sentence-transformers, normalised.

    Normalising makes the linear heads operate on cosine geometry, which is the space the encoder
    was actually trained to be meaningful in.
    """
    import numpy as np
    from sentence_transformers import SentenceTransformer

    encoder = SentenceTransformer(model_name)
    vectors = encoder.encode(
        texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    return np.asarray(vectors, dtype="float32")


def load_or_encode(rows: list[dict], model_name: str, cache_path: Path, use_cache: bool):
    """Encode the corpus, reusing a cache keyed on the exact texts and encoder.

    The cache key includes a hash of the texts, so a rebuilt dataset invalidates it rather than
    silently pairing new labels with stale vectors.
    """
    import hashlib

    import numpy as np

    texts = [r["fused_text"] for r in rows]
    digest = hashlib.sha256(
        (model_name + "\x00" + "\x00".join(texts)).encode("utf-8")
    ).hexdigest()

    if use_cache and cache_path.exists():
        cached = np.load(cache_path, allow_pickle=False)
        if str(cached.get("digest", "")) == digest or cached["digest"].item().decode() == digest:
            print(f"      reusing cached embeddings ({cache_path.name})")
            return cached["vectors"]
        print("      cache is stale (dataset or encoder changed); re-encoding")

    started = time.time()
    vectors = encode(texts, model_name)
    print(f"      encoded {len(texts)} texts in {time.time() - started:.1f}s -> {vectors.shape}")

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache_path, vectors=vectors, digest=np.bytes_(digest.encode()))
    return vectors


def fit_head(name: str, x_train, y_train, x_test, y_test, classes: list[str], weights, seed: int):
    """Fit one logistic-regression head and report its metrics."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, f1_score

    # `class_weight="balanced"` matters here: the department distribution is heavily skewed
    # towards general and billing, and an unweighted linear model on skewed data collapses onto
    # the majority class while still reporting a respectable accuracy.
    head = LogisticRegression(
        max_iter=2000,
        C=4.0,
        class_weight="balanced",
        random_state=seed,
        n_jobs=-1,
    )
    # The teacher's confidence weights each example, mirroring the distilled trainer so the two
    # approaches learn from the same signal and the comparison stays like for like.
    head.fit(x_train, y_train, sample_weight=weights)

    predicted = head.predict(x_test)
    metrics = {
        f"{name}_accuracy": float(accuracy_score(y_test, predicted)),
        f"{name}_macro_f1": float(f1_score(y_test, predicted, average="macro", zero_division=0)),
    }
    present = sorted(set(y_test) | set(predicted))
    print(f"      {name}: accuracy {metrics[f'{name}_accuracy']:.3f} "
          f"macro-F1 {metrics[f'{name}_macro_f1']:.3f} "
          f"({len(present)}/{len(classes)} classes seen)")
    return head, metrics


def main() -> int:
    parser = argparse.ArgumentParser(description="Train triage heads on frozen sentence embeddings")
    parser.add_argument("--dataset", default=str(DATASET))
    parser.add_argument("--encoder", default="sentence-transformers/all-MiniLM-L6-v2")
    parser.add_argument("--test-fraction", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default=str(ARTIFACT_DIR))
    parser.add_argument("--no-cache", action="store_true", help="ignore any cached embeddings")
    parser.add_argument("--register", action="store_true", help="log to MLflow")
    args = parser.parse_args()

    import joblib
    import numpy as np

    rows = load_dataset(Path(args.dataset))
    print(f"[1/5] {len(rows)} teacher-labelled payloads")
    multimodal = sum(1 for r in rows if r.get("is_multimodal"))
    print(f"      multimodal: {multimodal} ({multimodal / len(rows):.0%})")

    print(f"[2/5] encoding with {args.encoder}")
    vectors = load_or_encode(rows, args.encoder, CACHE, use_cache=not args.no_cache)

    # The same deterministic split the distilled trainer uses, so the two sets of numbers are
    # comparable. Indices are recovered by ticket id rather than by re-splitting the vectors.
    train_rows, test_rows = split_dataset(rows, args.test_fraction, args.seed)
    position = {row["ticket_id"]: i for i, row in enumerate(rows)}
    train_index = np.array([position[r["ticket_id"]] for r in train_rows])
    test_index = np.array([position[r["ticket_id"]] for r in test_rows])
    print(f"[3/5] train {len(train_index)} | test {len(test_index)} (shared split, seed {args.seed})")

    x_train, x_test = vectors[train_index], vectors[test_index]
    weights = np.array([
        float(r["teacher_label"].get("department_confidence", 1.0)) for r in train_rows
    ])

    def labels(source: list[dict], key: str, vocabulary: list[str]) -> np.ndarray:
        return np.array([vocabulary.index(r["teacher_label"][key]) for r in source])

    print("[4/5] fitting heads")
    heads, metrics = {}, {}
    for name, key, vocabulary in (
        ("department", "department", DEPARTMENTS),
        ("band", "priority_band", BANDS),
        ("sentiment", "sentiment", SENTIMENTS),
    ):
        head, head_metrics = fit_head(
            name,
            x_train, labels(train_rows, key, vocabulary),
            x_test, labels(test_rows, key, vocabulary),
            vocabulary, weights, args.seed,
        )
        heads[name] = head
        metrics.update(head_metrics)

    metrics["n"] = len(test_index)
    metrics["teacher_agreement_department"] = metrics["department_accuracy"]

    # Inference latency, measured the way it will be paid in production: encode one payload, then
    # run three heads. The encode dominates, which is the honest number to report.
    from sentence_transformers import SentenceTransformer

    encoder = SentenceTransformer(args.encoder)
    sample = rows[0]["fused_text"]
    encoder.encode([sample], normalize_embeddings=True)  # warm up
    started = time.time()
    for _ in range(20):
        vector = encoder.encode([sample], convert_to_numpy=True, normalize_embeddings=True)
        for head in heads.values():
            head.predict_proba(vector)
    metrics["latency_ms"] = round((time.time() - started) / 20 * 1000, 1)
    print(f"      latency {metrics['latency_ms']} ms per ticket (encode + 3 heads)")

    print("[5/5] saving")
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump(heads, out / "heads.joblib")
    (out / "config.json").write_text(json.dumps({
        "approach": "frozen sentence embeddings + logistic regression",
        "encoder": args.encoder,
        "departments": DEPARTMENTS,
        "bands": BANDS,
        "sentiments": SENTIMENTS,
        "teacher_model": rows[0].get("teacher_model"),
        "trained_on": len(train_index),
        "metrics": metrics,
    }, indent=2), encoding="utf-8")
    print(f"      wrote {out}")

    if args.register:
        import mlflow

        from libs.platform.config import get_settings

        mlflow.set_tracking_uri(get_settings().mlflow_tracking_uri)
        mlflow.set_experiment("cst/embedding-triage")
        with mlflow.start_run(run_name="minilm-logreg-triage"):
            mlflow.log_params({
                "encoder": args.encoder,
                "teacher_model": rows[0].get("teacher_model"),
                "train_rows": len(train_index),
                "approach": "frozen-embeddings",
            })
            mlflow.log_metrics({k: v for k, v in metrics.items() if isinstance(v, (int, float))})
            mlflow.log_artifacts(str(out), artifact_path="model")
            print("      logged to MLflow")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
