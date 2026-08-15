# 15. Continuous learning

The system improves as agents use it. Every approval, reassignment and escalation is a human
judgement about a model output, and this document describes how those judgements become training
data, how retraining consumes them, and which safeguards stop the loop from making the model
worse.

## The loop

```
agent acts in the workspace
        |
        v
agent_decision           persisted first, so a label can never exist without the decision that justified it
        |
        v
feedback_svc.harvest_decision()
        |
        v
training_example         append-only, idempotent on (decision_id, task)
        |
        v
mlops/spark_retrain.py   Spark reads the corpus and the new labels, trains, evaluates
        |
        v
MLflow registry          candidate registered; @champion moves only if it wins
        |
        v
libs/platform/mlflow_registry.py resolves @champion at inference time
```

## Which decisions produce which labels

The mapping is deliberately conservative. A decision only produces a label when it states
unambiguously what the correct answer was.

| Decision | Labels produced | Reasoning |
|---|---|---|
| `REASSIGN` | department, as a correction | The agent named the correct department. This is the strongest signal in the system. |
| `ESCALATE` | priority, as a correction | Says the band was too low. Says nothing about the department, so no department label. |
| `APPROVE_SEND` | department, priority, fault, all as confirmations | The human accepted the routing and the diagnosis. |
| `APPROVE_SEND` with an edited draft | draft pair, retained but not trained on | See below. |
| `REJECT` | none | A rejection says the output was wrong without saying what was right. Training on "not this" needs a target the reason code does not supply. |

Three consequences of that table are worth stating plainly.

**Confirmations are recorded, not just corrections.** A dataset built only from corrections would
teach the model that its confident, correct predictions are the exception. `is_correction`
distinguishes them, and the retraining job weights corrections at 3.0 against 1.0 for
confirmations, because a human bothering to disagree is the more informative event.

**Draft edits are captured but not used as supervised targets.** The pairs are stored under task
`draft` and feed the edit-distance metric. Treating a lightly reworded reply as ground truth
would train the model toward one agent's prose style rather than toward correctness. They exist
for a future preference-tuning run, which is a different training objective.

**Rejections deliberately produce nothing.** This is the most likely thing to be asked about in
review. A reason code of `wrong_department` tells you the prediction was wrong but not what the
right department is; harvesting that as a label would require inventing a target.

## Safeguards

Each of these exists because its absence is a specific, known failure mode of feedback loops.

1. **Promotion is a comparison, never a schedule.** `spark_retrain.py` reads the incumbent
   champion's metric from MLflow and promotes only when the candidate beats it on the held-out
   split. A retrain that makes the model worse cannot reach production by virtue of being newer.
   This is demonstrated in the verification below: the second run scored identically and was
   correctly refused.

2. **Examples are consumed only after a successful run.** `consumed_by_run` is stamped inside the
   success path. A crashed run leaves labels available for the next attempt rather than silently
   discarding them.

3. **Harvesting cannot break the agent's action.** `workspace_api._harvest` swallows exceptions
   and logs them. The decision and the delivery are already committed by the time it runs, and
   losing one training example matters far less than a failed Approve and Send.

4. **Idempotency at the database level.** `UNIQUE (decision_id, task)` means a replayed decision
   cannot duplicate a label. The constraint is the arbiter, not the code.

5. **The held-out split is never contaminated.** Feedback rows join the training set only. The
   evaluation split stays fixed across runs, so metrics remain comparable over time.

## Running a retrain

```bash
# Spark does the ETL and feature engineering; promotion happens only on a win.
python -m mlops.spark_retrain --task department --promote

# Through the tracked pipeline, which records data and parameter versions.
dvc repro retrain
```

The admin console at **Administration, Learning** shows pending label counts, the current
champion with its metrics, and the history of previous runs, including ones that were not
promoted.

`retrain_min_new_examples` (default 25) is the threshold at which the console reports a retrain as
due. It is a prompt for an operator, not an automatic trigger: starting a Spark job that can move
the production model is a deliberate act.

## Verified behaviour

Run on 2026-08-16 against the `stub` profile.

Four tickets were submitted and reassigned to the department the agent judged correct:

```
harvested 4 department labels:
   general       -> network_operations  (correction=True)
   field_service -> field_service       (correction=True)
   general       -> network_operations  (correction=True)
   general       -> field_service       (correction=True)
```

The retraining job consumed exactly those four:

```
[4/8] base corpus: 21825 rows | new human labels: 4
[5/8] fitting (hybrid)
[6/8] evaluated
candidate: {'macro_f1': 0.9982434987591997, 'accuracy': 0.9981678270428729}
[7/8] logging model to registry
NOT promoted: 0.9982 does not beat incumbent 0.9982
```

```
SUCCEEDED task=department trigger=threshold new=4 cand=0.9982 promoted=False
unconsumed after run: 0
```

Both halves of that result matter. The labels were harvested, consumed and marked; and the
promotion gate refused a candidate that did not improve on the incumbent, which is the behaviour
that keeps the loop safe.

## An honest caveat about the metric

The 0.9982 macro-F1 is not a credible generalisation estimate, and the loop's mechanics should
not be read as evidence that the model is that good. The training and test splits share 289 of
2,660 texts verbatim, and Bitext phrasings are templated, so held-out rows are near-duplicates of
training rows. Deduplicate by text before splitting to obtain a trustworthy figure. The
continuous-learning machinery is verified; the accuracy number is inflated by the dataset.

Four human labels against 21,825 base rows also cannot move a metric measurably. The loop is
demonstrated end to end, not shown to improve accuracy, and demonstrating the latter needs a
volume of real agent interaction this project has not yet collected.
