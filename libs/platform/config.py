"""Application settings. Single source of truth for every *_impl selection and threshold.

APP_PROFILE (`stub | cpu | full`) selects a block from `config/settings.yaml`; the `stub`
profile additionally forces every `*_impl` field to a stub regardless of what YAML/env say,
this is the CI profile of SAD §8.2.3.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
_STUB_IMPL_FIELDS = {
    "asr_impl": "stub",
    "vlm_impl": "stub",
    "llm_impl": "stub",
    "embedder_impl": "hash_stub",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    profile: str = "cpu"

    database_url: str = "sqlite+pysqlite:///./v1_data/app.db"
    object_store_root: Path = Path("./v1_data/objects")

    broker: str = "inprocess"
    kafka_bootstrap: str = "localhost:9092"

    ollama_base_url: str = "http://localhost:11434"
    llm_model: str = "llama3.1:8b-instruct-q4_K_M"
    vlm_model: str = "llava:7b"
    llm_timeout_s: float = 60.0
    llm_num_ctx: int = 8192

    asr_impl: str = "faster_whisper"
    asr_model: str = "base"
    vlm_impl: str = "ollama"
    llm_impl: str = "ollama"
    embedder_impl: str = "sentence_transformers"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    classifier_path: Path = Path("./models/artifacts/department_clf.joblib")
    vector_store_path: Path = Path("./v1_data/vectors.json")

    aggregation_window_s: int = 120
    asr_low_confidence_threshold: float = 0.60
    vlm_low_confidence_threshold: float = 0.55
    diagnosis_min_confidence: float = 0.45
    max_retries: int = 3

    auth_token_agent: str = "dev-agent-token"
    auth_token_lead: str = "dev-lead-token"
    auth_token_admin: str = "dev-admin-token"

    # Origins allowed to call this API from a browser. The frontend is deployed separately, so
    # its origin must be listed here explicitly, never "*", because the API accepts credentials.
    # Defaults cover the Vite dev server and a local `vite preview`.
    # 5300 is the dev server port (see frontend/vite.config.ts for why it is not Vite's 5173),
    # 4173 is `vite preview`.
    cors_allow_origins: list[str] = [
        "http://localhost:5300",
        "http://127.0.0.1:5300",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ]


def _load_profile_overrides(profile: str) -> dict:
    settings_yaml = _CONFIG_DIR / "settings.yaml"
    if not settings_yaml.exists():
        return {}
    data = yaml.safe_load(settings_yaml.read_text(encoding="utf-8")) or {}
    return dict(data.get("profiles", {}).get(profile, {}))


@lru_cache
def get_settings() -> Settings:
    # Priority, low to high: Settings field defaults < config/settings.yaml profile block <
    # environment / .env (handled natively by pydantic-settings) < stub-profile force override.
    import os

    profile = os.environ.get("APP_PROFILE", os.environ.get("profile", "cpu"))
    overrides = _load_profile_overrides(profile)
    settings = Settings(profile=profile, **overrides)

    if profile == "stub":
        settings = settings.model_copy(update=_STUB_IMPL_FIELDS)

    return settings
