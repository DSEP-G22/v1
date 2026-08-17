"""Real call-centre audio from Hugging Face, for ASR evaluation and multimodal test tickets.

Uses **PolyAI/minds14** (`en-US`): 563 utterances of genuine banking-support speech recorded over
the telephone at 8 kHz, with human transcripts and 14 intent labels, CC-BY-4.0.

It was chosen over the cleaner alternatives on purpose. The system's real input is a customer
phoning about a fault, and 8 kHz telephony is the condition that actually degrades Whisper: a
model evaluated only on studio-quality read speech reports a WER that the deployed system will
never reproduce. The intent labels are a second benefit, since they let the same download serve
the ASR notebook and the intent work.

The dataset is not vendored into the repository. It downloads to the Hugging Face cache on first
use, and every entry point degrades to the local sample audio when the dataset is unavailable,
so no notebook hard-fails without network access.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

DATASET_ID = "PolyAI/minds14"
CONFIG = "en-US"
TARGET_SAMPLE_RATE = 16_000  # what faster-whisper expects, regardless of the source rate

# minds14 intents that correspond to a support contact this system would receive. The dataset is
# banking-domain, so the mapping is by intent shape (a fault report, a billing query, a cancellation)
# rather than by subject matter.
INTENT_TO_DEPARTMENT = {
    "abroad": "general",
    "address": "general",
    "app_error": "technical_support",
    "atm_limit": "billing",
    "balance": "billing",
    "business_loan": "sales",
    "card_issues": "technical_support",
    "cash_deposit": "billing",
    "direct_debit": "billing",
    "freeze": "retention",
    "high_value_payment": "billing",
    "joint_account": "general",
    "latest_transactions": "billing",
    "pay_bill": "billing",
}


@dataclass(frozen=True)
class AudioSample:
    """One utterance with everything the evaluation needs to score a transcription."""

    id: str
    audio_path: Path
    reference_text: str
    intent: str
    department: str
    sample_rate: int
    duration_s: float


def is_available() -> bool:
    try:
        import datasets  # noqa: F401

        return True
    except ImportError:
        return False


def load(split: str = "train", limit: int | None = None, cache_dir: str | None = None,
         stratify: bool = True, seed: int = 42):
    """Return the raw Hugging Face dataset, or None when `datasets` is not installed.

    minds14 publishes a single `train` split; callers subset it themselves so the choice of
    evaluation subset stays visible in the notebook rather than hidden here.

    The file order in minds14 is grouped by intent, so taking the first N rows returns N
    utterances of the *same* intent: a 6-row subset came back as six `joint_account` calls.
    `stratify` instead takes rows round-robin across intents, so a small subset still covers the
    intent space. Pass `stratify=False` for a reproducible contiguous slice.
    """
    if not is_available():
        return None
    from datasets import Audio, load_dataset

    ds = load_dataset(DATASET_ID, CONFIG, split=split, cache_dir=cache_dir, trust_remote_code=False)
    # Resample on read: minds14 is 8 kHz, Whisper expects 16 kHz, and doing it here means no
    # caller has to remember.
    ds = ds.cast_column("audio", Audio(sampling_rate=TARGET_SAMPLE_RATE))

    if limit is None or limit >= len(ds):
        return ds
    if not stratify:
        return ds.select(range(limit))

    # Round-robin over intents. Reading `intent_class` alone avoids decoding any audio here,
    # which would otherwise cost a full pass over the corpus just to build the index.
    import random as _random

    by_intent: dict[int, list[int]] = {}
    for index, intent_class in enumerate(ds["intent_class"]):
        by_intent.setdefault(intent_class, []).append(index)

    rng = _random.Random(seed)
    for indices in by_intent.values():
        rng.shuffle(indices)

    picked: list[int] = []
    cursors = {intent: 0 for intent in by_intent}
    while len(picked) < limit:
        progressed = False
        for intent, indices in sorted(by_intent.items()):
            cursor = cursors[intent]
            if cursor < len(indices):
                picked.append(indices[cursor])
                cursors[intent] = cursor + 1
                progressed = True
                if len(picked) == limit:
                    break
        if not progressed:  # corpus exhausted before the limit
            break

    return ds.select(sorted(picked))


def materialise(output_dir: Path, limit: int = 50, split: str = "train") -> list[AudioSample]:
    """Write `limit` utterances to disk as 16 kHz WAV files and return their metadata.

    The pipeline ingests files, not in-memory arrays, so evaluation needs real files on disk to
    exercise the same code path a customer upload would take.
    """
    ds = load(split=split, limit=limit)
    if ds is None:
        return []

    import soundfile as sf

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    samples: list[AudioSample] = []
    intent_names = ds.features["intent_class"].names if "intent_class" in ds.features else []

    for i, row in enumerate(ds):
        audio = row["audio"]
        intent = intent_names[row["intent_class"]] if intent_names else str(row.get("intent_class", ""))

        # The filename encodes the intent, not just the position. Naming purely by enumeration
        # index was a cache-invalidation bug: `minds14_0001.wav` meant a different utterance
        # depending on how the subset was selected, and the `path.exists()` skip below then
        # reused a stale file whose audio no longer matched the transcript and intent recorded
        # beside it. Including the intent means a changed subset writes new files instead of
        # silently reading mismatched ones.
        sample_id = f"minds14_{intent}_{i:04d}"
        path = output_dir / f"{sample_id}.wav"
        if not path.exists():
            sf.write(path, audio["array"], audio["sampling_rate"])

        samples.append(
            AudioSample(
                id=sample_id,
                audio_path=path,
                reference_text=row.get("english_transcription") or row.get("transcription", ""),
                intent=intent,
                department=INTENT_TO_DEPARTMENT.get(intent, "general"),
                sample_rate=audio["sampling_rate"],
                duration_s=len(audio["array"]) / audio["sampling_rate"],
            )
        )
    return samples


def main() -> None:
    """Write sample utterances for the submission page to `v1_data/sample_audio/`.

    One utterance per minds14 intent by default, because the point is variety: attaching the same
    clip to every test ticket makes the pipeline look deterministic when it is responding to
    identical input.

        python -m evaluation.datasets.hf_audio [--limit 14] [--out DIR]
    """
    import argparse

    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=14, help="how many utterances to write")
    parser.add_argument("--out", type=Path, default=repo_root / "v1_data" / "sample_audio")
    args = parser.parse_args()

    samples = materialise(args.out, limit=args.limit)
    if not samples:
        raise SystemExit(
            "minds14 is unavailable and nothing was written. It needs one download; after that "
            "the HuggingFace cache serves it offline."
        )
    print(f"wrote {len(samples)} utterances to {args.out}")
    for sample in samples:
        print(f"  {sample.audio_path.name:44} {sample.duration_s:5.1f}s  {sample.intent}")


def iter_local_fallback(sample_dir: Path) -> Iterator[AudioSample]:
    """Local sample audio, used when minds14 cannot be downloaded.

    These files have no reference transcript, so WER is not computable from them; they support
    latency and confidence-distribution work only. Notebook 06 states that limitation rather
    than reporting a fabricated WER.
    """
    for path in sorted(Path(sample_dir).glob("*.wav")) + sorted(Path(sample_dir).glob("*.mp3")):
        yield AudioSample(
            id=path.stem,
            audio_path=path,
            reference_text="",
            intent="unknown",
            department="general",
            sample_rate=0,
            duration_s=0.0,
        )


if __name__ == "__main__":
    main()
