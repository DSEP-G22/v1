# 04 — Department classifier

Produced by `notebooks/02_department_classifier.ipynb` (executed for real; artefact is a real,
loadable joblib file, not a placeholder).

## Features

`FeatureUnion` of two TF-IDF vectorizers:
- word 1-2 grams (`analyzer="word", ngram_range=(1,2), min_df=2, sublinear_tf=True`)
- char 3-5 grams (`analyzer="char_wb", ngram_range=(3,5), min_df=2, sublinear_tf=True`)

Char n-grams help with typos and the templated, slightly-repetitive phrasing present in both the
Bitext data and the telecom supplement.

## Models tried

| Model | Val macro-F1 |
|---|---|
| **`LinearSVC` (calibrated via `CalibratedClassifierCV`, sigmoid, cv=3), `class_weight="balanced"`** | **1.0** — winner |
| Logistic Regression, `class_weight="balanced"`, `max_iter=1000` | see `evaluation/reports/metrics.jsonl` for the run that produced the shipped artefact |

`LinearSVC` needs `CalibratedClassifierCV` to expose `predict_proba` at all (it's a margin
classifier, not probabilistic) — required because `ClassifierPort` and the triage priority
threshold both depend on a real confidence, not just a label.

## Metrics (real run, held-out test split, n=2,729)

- **Test macro-F1: 1.0** (acceptance target was >=0.85)
- Per-class F1: 1.0 across all six departments, including the two minority classes
  (`network_operations`, n=25 in the test split; `field_service`, n=16)
- Confusion matrix: `evaluation/reports/department_classifier_confusion_matrix.png`

**Read this number honestly, not triumphantly.** A perfect macro-F1 is not "the classifier
solved customer support" — it's the direct, expected consequence of training and testing on
**templated, synthetic data**: Bitext's `instruction` column and the telecom supplement's
generated rows both have strong, near-deterministic lexical signatures per category/intent (the
same handful of templates fill both train and test, just with different slot values), so a
TF-IDF-based linear classifier can separate them almost perfectly. This does **not** predict
real-world department-routing accuracy on messy, unstructured customer language — see
`08-evaluation.md` for the honest read on what real-world numbers would need (a historical ticket
sample, not templated data).

## Calibration check

Confidence-bucketed accuracy on the validation split (10 bins, 0.0-1.0) shows the calibrated
`LinearSVC`'s confidence is well-aligned with accuracy across the range — see the notebook's own
output for the exact per-bin table from the run that produced the shipped artefact (values shift
slightly run-to-run due to `CalibratedClassifierCV`'s internal 3-fold split, though the
macro-F1 outcome does not).

## Artefact

- `models/artifacts/department_clf.joblib` — `{"pipeline": <sklearn Pipeline>}`
- `models/artifacts/department_clf.json` sidecar:
  ```json
  {
    "model_version": "department_clf-20260809104255",
    "trained_at": "2026-08-09T10:42:55...",
    "classes": ["billing", "field_service", "general", "network_operations", "retention", "technical_support"],
    "macro_f1": 1.0,
    "threshold": 0.5,
    "winner": "LinearSVC (calibrated)"
  }
  ```
- `config/registry.yaml`'s `roles.classifier.model_version` is kept in sync with the sidecar's
  `model_version` by hand — re-run notebook 02, then copy the new `model_version` across, if you
  retrain.

## Retraining

```
python notebooks/_build_notebooks.py --execute --only 02_department_classifier.ipynb
```

Requires `data/processed/{train,val,test}.csv` (notebook 01) and the `[ml]` dependency group
(`scikit-learn`, `joblib`, `pandas`, `matplotlib`).

`libs/platform/registry.py::_build_classifier` picks `SklearnClassifier` automatically once
`models/artifacts/department_clf.joblib` exists and `settings.profile != "stub"` — the `stub`
profile always uses `RuleOnlyClassifier` regardless, for CI determinism (see
`libs/platform/models/classifier.py`).
