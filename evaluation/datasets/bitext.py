"""Loads the processed Bitext + telecom-supplement splits written by
notebooks/01_data_preparation.ipynb."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

_PROCESSED_DIR = Path(__file__).resolve().parents[2] / "data" / "processed"


def load_split(split: str) -> pd.DataFrame:
    if split not in ("train", "val", "test"):
        raise ValueError(f"unknown split {split!r}; expected train/val/test")
    path = _PROCESSED_DIR / f"{split}.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found — run notebooks/01_data_preparation.ipynb first")
    return pd.read_csv(path)
