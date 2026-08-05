"""Step 4 acceptance: stub-profile adapters work with no network access."""

import os
from pathlib import Path

os.environ["APP_PROFILE"] = "stub"

from libs.domain.enums import Department  # noqa: E402
from libs.platform.config import get_settings  # noqa: E402
from libs.platform.registry import build_ports  # noqa: E402


def test_build_ports_stub_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_PROFILE", "stub")
    monkeypatch.setenv("VECTOR_STORE_PATH", str(tmp_path / "vectors.json"))
    get_settings.cache_clear()
    settings = get_settings()
    ports = build_ports(settings)

    transcript = ports.transcriber.transcribe(Path("nonexistent.wav"), "att-1")
    assert transcript.attachment_id == "att-1"
    assert transcript.model_version.startswith("stub")

    summary = ports.visual_extractor.extract(Path("nonexistent.png"), "att-2", "generic")
    assert summary.attachment_id == "att-2"

    department, confidence, _ = ports.classifier.classify("My internet is down, no signal at all")
    assert department == Department.network_operations
    assert 0 <= confidence <= 1

    text = ports.text_generator.generate("please generate a diagnosis for this fault")
    assert text

    embeddings = ports.embedder.embed(["hello world"])
    assert len(embeddings) == 1
    assert len(embeddings[0]) == 384

    get_settings.cache_clear()
