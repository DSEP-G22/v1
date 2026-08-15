"""Loads the Roboflow "router detection" COCO dataset (`data/router detection.v38-data_video.coco.zip`).

Actual dataset content (verified by inspection, not assumed from the name): this is a
cable/port/connector detection dataset, categories are `{fiber,lan,phone,power,usb} x
{cable,conn}` plus a bare `phone`/`power`/`usb` port class, 2137 images / 4630 boxes in the train
split. It is **not** an LED-colour-state dataset. See `notebooks/05_vlm_led_extraction.ipynb` for
how this is actually used (as a port/cable-presence structured hint) versus the separate,
hand-labelled `data/processed/led_labels.jsonl` (LED colour/behaviour, which this dataset does
not cover at all).
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

_ZIP_PATH = Path(__file__).resolve().parents[2].parent / "data" / "router detection.v38-data_video.coco.zip"


@dataclass
class CocoAnnotation:
    image_id: int
    category_id: int
    bbox: tuple[float, float, float, float]


@dataclass
class CocoImage:
    id: int
    file_name: str
    width: int
    height: int


@dataclass
class CocoSplit:
    categories: dict[int, str]
    images: dict[int, CocoImage]
    annotations: list[CocoAnnotation]


def load_split(split: str = "train") -> CocoSplit:
    if split not in ("train", "valid", "test"):
        raise ValueError(f"unknown split {split!r}; expected train/valid/test")

    with zipfile.ZipFile(_ZIP_PATH) as zf:
        with zf.open(f"{split}/_annotations.coco.json") as f:
            data = json.load(f)

    categories = {c["id"]: c["name"] for c in data["categories"]}
    images = {img["id"]: CocoImage(img["id"], img["file_name"], img["width"], img["height"]) for img in data["images"]}
    annotations = [
        CocoAnnotation(a["image_id"], a["category_id"], tuple(a["bbox"])) for a in data["annotations"]
    ]
    return CocoSplit(categories=categories, images=images, annotations=annotations)


def extract_image(split: str, file_name: str, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(_ZIP_PATH) as zf:
        data = zf.read(f"{split}/{file_name}")
    out_path = dest_dir / file_name
    out_path.write_bytes(data)
    return out_path
