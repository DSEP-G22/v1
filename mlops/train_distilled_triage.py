"""Train the distilled triage student on teacher LLM labels.

Knowledge distillation: a DistilBERT encoder learns to reproduce the triage judgements of a
Llama 3.1 8B teacher, reading the same fused multimodal payload the teacher read. The student is
roughly two orders of magnitude smaller, answers in milliseconds on CPU, and needs no model
server, so it can sit on the pipeline's hot path where the teacher cannot.

Three heads share one encoder: department, priority band, and sentiment. Sharing is deliberate.
The three judgements draw on the same evidence, a shared representation is cheaper than three
models, and multi-task training regularises each head against the others.

Two signals are learned from, and the second is what makes this distillation rather than ordinary
supervised training:

*   the teacher's hard label, as cross-entropy;
*   the teacher's stated confidence, used to weight each example, so a ticket the teacher was
    unsure about contributes less than one it was certain of.

A full soft-target KL loss over the teacher's logits would be better still, but Ollama's chat API
does not expose per-class probabilities, so the stated confidence is the strongest signal
available. That limitation is real and is recorded in docs/17-llm-triage-distillation.md rather
than glossed over.

    python -m mlops.train_distilled_triage --epochs 3
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DATASET = REPO_ROOT / "data" / "processed" / "distillation_dataset.jsonl"
ARTIFACT_DIR = REPO_ROOT / "models" / "artifacts" / "distilled_triage"

DEPARTMENTS = ["technical_support", "network_operations", "field_service",
               "billing", "retention", "sales", "general"]
BANDS = ["critical", "high", "normal", "low"]
SENTIMENTS = ["angry", "frustrated", "neutral", "satisfied"]


def load_dataset(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise ValueError(f"{path} is empty. Run mlops/llm_triage_labeller.py first.")
    return rows


def build_torch_dataset(rows: list[dict], tokenizer, max_length: int = 256):
    import torch
    from torch.utils.data import Dataset

    class TriageDataset(Dataset):
        def __init__(self, records):
            self.records = records

        def __len__(self):
            return len(self.records)

        def __getitem__(self, index):
            record = self.records[index]
            label = record["teacher_label"]
            encoded = tokenizer(
                record["fused_text"],
                truncation=True,
                max_length=max_length,
                padding="max_length",
                return_tensors="pt",
            )
            return {
                "input_ids": encoded["input_ids"].squeeze(0),
                "attention_mask": encoded["attention_mask"].squeeze(0),
                "department": torch.tensor(DEPARTMENTS.index(label["department"])),
                "band": torch.tensor(BANDS.index(label["priority_band"])),
                "sentiment": torch.tensor(SENTIMENTS.index(label["sentiment"])),
                # The teacher's confidence becomes this example's weight.
                "weight": torch.tensor(float(label.get("department_confidence", 1.0)), dtype=torch.float),
            }

    return TriageDataset(rows)


def build_model():
    import torch
    from torch import nn
    from transformers import AutoModel

    class DistilledTriageModel(nn.Module):
        """One DistilBERT encoder, three classification heads."""

        def __init__(self, encoder_name: str = "distilbert-base-uncased"):
            super().__init__()
            self.encoder = AutoModel.from_pretrained(encoder_name)
            hidden = self.encoder.config.hidden_size
            self.dropout = nn.Dropout(0.1)
            self.department_head = nn.Linear(hidden, len(DEPARTMENTS))
            self.band_head = nn.Linear(hidden, len(BANDS))
            self.sentiment_head = nn.Linear(hidden, len(SENTIMENTS))

        def forward(self, input_ids, attention_mask):
            output = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
            pooled = self.dropout(output.last_hidden_state[:, 0])  # [CLS]
            return (
                self.department_head(pooled),
                self.band_head(pooled),
                self.sentiment_head(pooled),
            )

    return DistilledTriageModel()


def evaluate(model, loader, device) -> dict:
    import torch

    model.eval()
    correct = {"department": 0, "band": 0, "sentiment": 0}
    total = 0
    dept_true, dept_pred = [], []

    with torch.no_grad():
        for batch in loader:
            input_ids = batch["input_ids"].to(device)
            mask = batch["attention_mask"].to(device)
            dept_logits, band_logits, sent_logits = model(input_ids, mask)

            for name, logits in (("department", dept_logits), ("band", band_logits), ("sentiment", sent_logits)):
                predicted = logits.argmax(dim=1).cpu()
                correct[name] += (predicted == batch[name]).sum().item()
                if name == "department":
                    dept_true.extend(batch[name].tolist())
                    dept_pred.extend(predicted.tolist())
            total += input_ids.size(0)

    from sklearn.metrics import f1_score

    return {
        "department_accuracy": correct["department"] / total,
        "department_macro_f1": float(f1_score(dept_true, dept_pred, average="macro", zero_division=0)),
        "band_accuracy": correct["band"] / total,
        "sentiment_accuracy": correct["sentiment"] / total,
        "n": total,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Train the distilled triage student")
    parser.add_argument("--dataset", default=str(DATASET))
    parser.add_argument("--encoder", default="distilbert-base-uncased")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=3e-5)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--test-fraction", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default=str(ARTIFACT_DIR))
    parser.add_argument("--register", action="store_true", help="log to MLflow and register the model")
    args = parser.parse_args()

    import random

    import torch
    from torch.utils.data import DataLoader
    from transformers import AutoTokenizer

    torch.manual_seed(args.seed)
    random.seed(args.seed)

    rows = load_dataset(Path(args.dataset))
    print(f"[1/5] {len(rows)} teacher-labelled payloads")

    multimodal = sum(1 for r in rows if r.get("is_multimodal"))
    print(f"      multimodal: {multimodal} ({multimodal / len(rows):.0%})")

    random.shuffle(rows)
    split = int(len(rows) * (1 - args.test_fraction))
    train_rows, test_rows = rows[:split], rows[split:]
    print(f"      train {len(train_rows)} | test {len(test_rows)}")

    print(f"[2/5] loading {args.encoder}")
    tokenizer = AutoTokenizer.from_pretrained(args.encoder)
    model = build_model()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    print(f"      device {device} | parameters {sum(p.numel() for p in model.parameters()) / 1e6:.1f}M")

    train_loader = DataLoader(build_torch_dataset(train_rows, tokenizer, args.max_length),
                              batch_size=args.batch_size, shuffle=True)
    test_loader = DataLoader(build_torch_dataset(test_rows, tokenizer, args.max_length),
                             batch_size=args.batch_size)

    optimiser = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
    loss_fn = torch.nn.CrossEntropyLoss(reduction="none")

    print(f"[3/5] training {args.epochs} epoch(s)")
    for epoch in range(1, args.epochs + 1):
        model.train()
        running = 0.0
        for step, batch in enumerate(train_loader, 1):
            optimiser.zero_grad()
            dept_logits, band_logits, sent_logits = model(
                batch["input_ids"].to(device), batch["attention_mask"].to(device)
            )
            weight = batch["weight"].to(device)

            # Department is the decision the routing layer acts on, so it dominates the loss.
            # Each example is scaled by the teacher's confidence in its own label.
            loss = (
                2.0 * (loss_fn(dept_logits, batch["department"].to(device)) * weight).mean()
                + 1.0 * (loss_fn(band_logits, batch["band"].to(device)) * weight).mean()
                + 0.5 * (loss_fn(sent_logits, batch["sentiment"].to(device)) * weight).mean()
            )
            loss.backward()
            optimiser.step()
            running += loss.item()
            if step % 20 == 0:
                print(f"      epoch {epoch} step {step}/{len(train_loader)} loss {running / step:.4f}")

        metrics = evaluate(model, test_loader, device)
        print(f"      epoch {epoch}: {metrics}")

    print("[4/5] final evaluation")
    metrics = evaluate(model, test_loader, device)

    # Agreement with the teacher is the distillation metric: how often the student reproduces the
    # judgement it was trained to imitate.
    metrics["teacher_agreement_department"] = metrics["department_accuracy"]
    print(f"      {json.dumps(metrics, indent=2)}")

    print("[5/5] saving")
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out / "model.pt")
    tokenizer.save_pretrained(out)
    (out / "config.json").write_text(json.dumps({
        "encoder": args.encoder,
        "departments": DEPARTMENTS,
        "bands": BANDS,
        "sentiments": SENTIMENTS,
        "max_length": args.max_length,
        "teacher_model": rows[0].get("teacher_model"),
        "trained_on": len(train_rows),
        "metrics": metrics,
    }, indent=2), encoding="utf-8")
    print(f"      wrote {out}")

    if args.register:
        import mlflow

        from libs.platform.config import get_settings

        mlflow.set_tracking_uri(get_settings().mlflow_tracking_uri)
        mlflow.set_experiment("cst/distilled-triage")
        with mlflow.start_run(run_name="distilbert-triage"):
            mlflow.log_params({
                "encoder": args.encoder,
                "epochs": args.epochs,
                "batch_size": args.batch_size,
                "learning_rate": args.learning_rate,
                "teacher_model": rows[0].get("teacher_model"),
                "train_rows": len(train_rows),
            })
            mlflow.log_metrics({k: v for k, v in metrics.items() if isinstance(v, (int, float))})
            mlflow.log_artifacts(str(out), artifact_path="model")
            print("      logged to MLflow")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
