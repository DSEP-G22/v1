"""Regression tests for two dataset bugs that were silent in the aggregate counts.

Both produced a dataset that looked correct in every summary statistic (row counts, modality
counts, department distribution) while being wrong row by row. Neither would have been caught by
anything except an assertion of the kind below, which is why they are tests rather than a note.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET = REPO_ROOT / "data" / "processed" / "unified_dataset.jsonl"

TELECOM_DEPARTMENTS = {"technical_support", "network_operations", "field_service"}


def _load() -> list[dict]:
    if not DATASET.exists():
        pytest.skip("unified_dataset.jsonl not built; run mlops/build_unified_dataset.py")
    return [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_audio_matches_ticket_department():
    """Audio must describe the same department as the ticket it is attached to.

    The builder originally attached any call to any ticket, on the incorrect assumption that
    minds14 was generic support speech. It is banking-domain, so that produced tickets whose text
    asked to track an order while the attached call asked to open a joint account. A teacher asked
    to triage that has to pick one topic arbitrarily, which makes the label noise.
    """
    for row in _load():
        for transcript in row["transcripts"]:
            assert transcript.get("source_department") == row["ground_truth"]["department"], (
                f"{row['ticket_id']}: {transcript.get('source_department')} audio attached to a "
                f"{row['ground_truth']['department']} ticket"
            )


def test_images_only_on_telecom_departments():
    """A router photograph on a billing query would teach the model that images are noise."""
    for row in _load():
        for visual in row["visual_summaries"]:
            assert visual["implied_department"] in TELECOM_DEPARTMENTS, (
                f"{row['ticket_id']}: image implying {visual['implied_department']}"
            )


def test_provenance_spans_resolve():
    """`fused_text[start:end]` must return the fragment the provenance entry claims.

    The workspace labels evidence by these spans, so an off-by-one here would attribute a
    customer's typed words to a machine transcript in the agent's view.
    """
    for row in _load():
        for entry in row["provenance"]:
            start, end = entry["span"]
            fragment = row["fused_text"][start:end]
            assert fragment.strip(), f"{row['ticket_id']}: empty span {entry['span']}"
            marker = {"text": "[CUSTOMER_TEXT]", "audio": "[AUDIO:", "image": "[IMAGE:"}[entry["modality"]]
            assert fragment.startswith(marker), (
                f"{row['ticket_id']}: {entry['modality']} span starts with {fragment[:20]!r}"
            )


def test_audio_subset_covers_multiple_intents():
    """minds14 is stored grouped by intent, so an unstratified subset is one intent repeated.

    A 6-row subset once came back as six `joint_account` calls: not an audio sample of a support
    line, but one question asked six ways. `hf_audio.load(stratify=True)` fixes this at the source.
    """
    rows = _load()
    intents = {r["transcripts"][0]["source_intent"] for r in rows if r["transcripts"]}
    if len(intents) <= 1:
        pytest.skip(f"dataset carries too little audio to test stratification ({intents})")
    assert len(intents) >= 3, f"audio subset covers only {intents}"


def test_audio_filenames_encode_intent():
    """Filenames must not be position-only, or a changed subset silently reuses stale WAVs.

    `materialise` originally wrote `minds14_0001.wav` and skipped files that already existed. Once
    subset selection changed, index 1 meant a different utterance but the old file was still on
    disk and was read instead, pairing one row's audio with another row's transcript and intent.
    """
    for row in _load():
        for transcript in row["transcripts"]:
            attachment_id = transcript["attachment_id"]
            assert transcript["source_intent"] in attachment_id, (
                f"{attachment_id} does not encode its intent, so it is vulnerable to the stale "
                "cache bug"
            )
