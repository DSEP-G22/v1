"""`build_ports(settings) -> Ports`, the only place adapters are constructed (ADR-005: no
service constructs an adapter directly). Also loads config/registry.yaml so artefacts can be
stamped with a model_version."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from libs.domain.ports import (
    ActionAdapterPort,
    ClassifierPort,
    EmbedderPort,
    EventBrokerPort,
    GraphStorePort,
    MailGatewayPort,
    ObjectStorePort,
    TextGeneratorPort,
    TranscriberPort,
    VectorIndexPort,
    VisualExtractorPort,
)
# Not re-exported from libs.domain.ports, so it is imported from its own module. The annotations
# below are lazy (`from __future__ import annotations`), which is why the missing import never
# raised at runtime — but get_type_hints() on Ports would.
from libs.domain.ports.triage_model import TriageModelPort
from libs.platform.broker.factory import build_broker
from libs.platform.config import Settings
from libs.platform.gateways import ConsoleMailGateway, SimulatedActionAdapter
from libs.platform.objectstore.local import LocalObjectStore

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GRAPH_SEED = _REPO_ROOT / "config" / "seed" / "graph_seed.yaml"


@dataclass
class Ports:
    transcriber: TranscriberPort
    visual_extractor: VisualExtractorPort
    text_generator: TextGeneratorPort
    embedder: EmbedderPort
    classifier: ClassifierPort
    # Optional: when configured, triage_svc prefers this over `classifier`, because it
    # judges department, band and sentiment from the fused payload in one pass.
    triage_model: TriageModelPort | None
    vector_index: VectorIndexPort
    graph_store: GraphStorePort
    object_store: ObjectStorePort
    event_broker: EventBrokerPort
    action_adapter: ActionAdapterPort
    mail_gateway: MailGatewayPort


def _load_registry_versions() -> dict[str, dict[str, str]]:
    registry_yaml = _REPO_ROOT / "config" / "registry.yaml"
    if not registry_yaml.exists():
        return {}
    data = yaml.safe_load(registry_yaml.read_text(encoding="utf-8")) or {}
    return dict(data.get("roles", {}))


def _build_transcriber(settings: Settings) -> TranscriberPort:
    if settings.asr_impl == "stub":
        from libs.platform.models.asr import StubTranscriber

        return StubTranscriber(low_confidence_threshold=settings.asr_low_confidence_threshold)

    from libs.platform.models.asr import FasterWhisperTranscriber

    return FasterWhisperTranscriber(
        model_size=settings.asr_model, low_confidence_threshold=settings.asr_low_confidence_threshold
    )


def _build_visual_extractor(settings: Settings) -> VisualExtractorPort:
    if settings.vlm_impl == "stub":
        from libs.platform.models.vlm import StubExtractor

        return StubExtractor(low_confidence_threshold=settings.vlm_low_confidence_threshold)

    if settings.vlm_impl == "heuristic":
        from libs.platform.models.vlm import HeuristicLedExtractor

        return HeuristicLedExtractor(low_confidence_threshold=settings.vlm_low_confidence_threshold)

    from libs.platform.models.vlm import OllamaVisionExtractor

    return OllamaVisionExtractor(
        base_url=settings.ollama_base_url,
        model=settings.vlm_model,
        timeout_s=settings.llm_timeout_s,
        low_confidence_threshold=settings.vlm_low_confidence_threshold,
    )


def _build_text_generator(settings: Settings) -> TextGeneratorPort:
    if settings.llm_impl == "stub":
        from libs.platform.models.llm import StubGenerator

        return StubGenerator()

    from libs.platform.models.llm import OllamaGenerator

    return OllamaGenerator(
        base_url=settings.ollama_base_url,
        model=settings.llm_model,
        timeout_s=settings.llm_timeout_s,
        num_ctx=settings.llm_num_ctx,
        max_attempts=settings.max_retries,
    )


def _build_embedder(settings: Settings) -> EmbedderPort:
    if settings.embedder_impl == "hash_stub":
        from libs.platform.models.embedder import HashEmbedder

        return HashEmbedder()

    from libs.platform.models.embedder import SentenceTransformerEmbedder

    return SentenceTransformerEmbedder(model_name=settings.embedding_model)


def _build_classifier(settings: Settings, text_generator: TextGeneratorPort) -> ClassifierPort:
    """Selection order: sklearn artifact if present -> LLM -> rules."""
    if settings.profile == "stub":
        # CI/stub profile: never touch the filesystem artefact, keep classification deterministic.
        from libs.platform.models.classifier import RuleOnlyClassifier

        return RuleOnlyClassifier()

    if Path(settings.classifier_path).exists():
        from libs.platform.models.classifier import SklearnClassifier

        return SklearnClassifier(artifact_path=Path(settings.classifier_path))

    if settings.llm_impl != "stub":
        from libs.platform.models.classifier import LlmClassifier

        return LlmClassifier(generator=text_generator)

    from libs.platform.models.classifier import RuleOnlyClassifier

    return RuleOnlyClassifier()


def _build_vector_index(settings: Settings, embedding_model: str) -> VectorIndexPort:
    from libs.platform.vector.inmemory import InMemoryVectorIndex

    return InMemoryVectorIndex(path=Path(settings.vector_store_path), embedding_model=embedding_model)


def _build_graph_store() -> GraphStorePort:
    from libs.platform.graph.inmemory import InMemoryGraphStore

    return InMemoryGraphStore(seed_path=_GRAPH_SEED)


def _build_triage_model(settings: Settings) -> "TriageModelPort | None":
    """Select the triage model: distilled student, teacher LLM, stub, or none.

    Returning None is a supported outcome, not a failure: triage_svc then uses the classifier
    path, which is what the rule-only profile and the degradation tests rely on.
    """
    impl = getattr(settings, "triage_model_impl", "none")

    if impl == "stub":
        from libs.platform.models.triage import StubTriageModel

        return StubTriageModel()

    if impl == "distilled":
        from libs.platform.models.triage import DistilledTriageModel

        return DistilledTriageModel(artifact_dir=Path(settings.distilled_triage_path))

    if impl == "embedding":
        from libs.platform.models.triage import EmbeddingTriageModel

        return EmbeddingTriageModel(
            artifact_dir=Path(settings.embedding_triage_path),
            encoder_name=settings.embedding_model,
        )

    if impl == "llm":
        from libs.platform.models.triage import LlmTriageModel

        return LlmTriageModel(
            base_url=settings.ollama_base_url,
            model=settings.llm_model,
            prompt_path=_REPO_ROOT / "models" / "prompts" / "llm" / "triage.txt",
            timeout=settings.llm_timeout_s,
            num_ctx=settings.llm_num_ctx,
        )

    return None


def build_ports(settings: Settings) -> Ports:
    text_generator = _build_text_generator(settings)
    embedder = _build_embedder(settings)
    embedding_model_version = getattr(embedder, "model_version", settings.embedding_model)

    return Ports(
        transcriber=_build_transcriber(settings),
        visual_extractor=_build_visual_extractor(settings),
        text_generator=text_generator,
        embedder=embedder,
        classifier=_build_classifier(settings, text_generator),
        triage_model=_build_triage_model(settings),
        vector_index=_build_vector_index(settings, embedding_model_version),
        graph_store=_build_graph_store(),
        object_store=LocalObjectStore(root=Path(settings.object_store_root)),
        event_broker=build_broker(settings),
        action_adapter=SimulatedActionAdapter(),
        mail_gateway=ConsoleMailGateway(),
    )


REGISTRY_VERSIONS = _load_registry_versions()
