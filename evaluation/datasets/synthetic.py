"""Generates synthetic multimodal tickets by pairing a text complaint with a reused audio
sample and a router image — the "same code, different driver" seam of UC-8: these tickets are
submitted through the exact same `create_ticket` entrypoint intake_api uses."""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE_AUDIO = _REPO_ROOT.parent / "ingestion-pipeline-prototype" / "data" / "sample_audio" / "sample_call.wav"
_SAMPLE_IMAGES = {
    "red": _REPO_ROOT.parent / "ingestion-pipeline-prototype" / "data" / "sample_images" / "router_red_led.png",
    "green": _REPO_ROOT.parent / "ingestion-pipeline-prototype" / "data" / "sample_images" / "router_green_led.png",
}

# (text template, expected_department, expected_fault_hint)
_TEMPLATES: list[tuple[str, str, str | None]] = [
    ("My router's power light is solid red and I have no internet at all.", "network_operations", "fault_power_supply"),
    ("The internet LED on my modem is stuck amber and never turns green.", "network_operations", "fault_line_sync"),
    ("My connection keeps dropping every few minutes throughout the day.", "network_operations", "fault_intermittent_connection"),
    ("There is no dial tone at all on my landline.", "network_operations", "fault_no_dial_tone"),
    ("I was charged twice for the same invoice this month, please refund me.", "billing", "fault_billing_dispute"),
    ("I paid my bill but it's still showing as unpaid on my account.", "billing", "fault_billing_dispute"),
    ("I want to cancel my subscription, I'm moving to another provider.", "retention", None),
    ("Please stop my service, I no longer need it.", "retention", None),
    ("Can I get a technician to come look at the damaged cabling outside my house?", "field_service", "fault_cabling"),
    ("I need someone to install internet at my new address next week.", "field_service", None),
    ("I'm interested in upgrading my plan to a faster speed, what are my options?", "sales", None),
    ("What's the pricing for a new fibre connection at my address?", "sales", None),
    ("I can't log into my account portal, it keeps rejecting my password.", "technical_support", None),
    ("How do I change the email address linked to my subscription?", "technical_support", None),
]


@dataclass
class SyntheticTicket:
    text: str
    expected_department: str
    expected_fault: str | None
    audio_path: Path | None
    image_path: Path | None


def generate_tickets(n: int, seed: int = 22, with_media_ratio: float = 0.7) -> list[SyntheticTicket]:
    rng = random.Random(seed)
    tickets: list[SyntheticTicket] = []
    for i in range(n):
        text, department, fault = rng.choice(_TEMPLATES)
        with_media = rng.random() < with_media_ratio
        audio_path = _SAMPLE_AUDIO if with_media and _SAMPLE_AUDIO.exists() else None
        image_path = None
        if with_media:
            image_key = "red" if department == "network_operations" else "green"
            candidate = _SAMPLE_IMAGES.get(image_key)
            image_path = candidate if candidate and candidate.exists() else None
        tickets.append(
            SyntheticTicket(
                text=f"{text} (ticket #{i})",
                expected_department=department,
                expected_fault=fault,
                audio_path=audio_path,
                image_path=image_path,
            )
        )
    return tickets
