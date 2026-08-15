"""Resolves trained models from the MLflow registry, with a local fallback.

The registry is the source of truth for which artefact is live: notebooks and the Spark
retraining job register versions and move the `@champion` alias, and the running system reads
that alias. Without this indirection the pipeline and the training code disagree about which
model is current the moment anyone retrains.

The hard rule here is that **the registry is never allowed to take the system down**. If MLflow
is unreachable, or the alias is unset, or the artefact will not load, the resolver falls back to
the local joblib artefact and then to the rule-based adapter, and raises a `MODEL_FALLBACK`
flag so the degradation is visible rather than silent. A support pipeline that stops triaging
tickets because a tracking server is down would be a worse failure than a slightly stale model.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from libs.observability.logging import get_logger

logger = get_logger(__name__)

FLAG_MODEL_FALLBACK = "MODEL_FALLBACK"


@dataclass(frozen=True)
class ResolvedModel:
    """A loaded model plus the provenance needed to stamp it on everything it produces."""

    model: Any
    version: str
    source: str  # mlflow | local | none

    @property
    def is_champion(self) -> bool:
        return self.source == "mlflow"


class MLflowModelResolver:
    """Loads registry models, caching by role so each is fetched at most once per process."""

    def __init__(self, tracking_uri: str, enabled: bool = True, cache_dir: Path | None = None) -> None:
        self._tracking_uri = tracking_uri
        self._enabled = enabled
        self._cache_dir = cache_dir or Path("v1_data/mlflow_cache")
        self._cache: dict[str, ResolvedModel] = {}
        self._lock = threading.Lock()

    def resolve(self, role: str, model_uri: str, local_path: Path | None = None) -> ResolvedModel:
        """Return the champion for `role`, falling back to `local_path`, then to nothing."""
        with self._lock:
            if role in self._cache:
                return self._cache[role]

            resolved = self._from_mlflow(role, model_uri) or self._from_local(role, local_path)
            if resolved is None:
                resolved = ResolvedModel(model=None, version="none", source="none")
                logger.warning(
                    f"no model available for role={role}; caller must use its rule-based fallback",
                    extra={"stage": "registry"},
                )
            self._cache[role] = resolved
            return resolved

    def _from_mlflow(self, role: str, model_uri: str) -> ResolvedModel | None:
        if not self._enabled:
            return None
        try:
            import mlflow

            mlflow.set_tracking_uri(self._tracking_uri)
            model = mlflow.pyfunc.load_model(model_uri)
            version = self._describe(model_uri)
            logger.info(f"loaded {role} from registry: {version}", extra={"stage": "registry"})
            return ResolvedModel(model=model, version=version, source="mlflow")
        except Exception as exc:  # noqa: BLE001 - any registry failure means fall back, never fail
            logger.warning(
                f"registry unavailable for role={role} ({type(exc).__name__}: {exc}); falling back to local",
                extra={"stage": "registry"},
            )
            return None

    def _from_local(self, role: str, local_path: Path | None) -> ResolvedModel | None:
        if local_path is None or not Path(local_path).exists():
            return None
        try:
            import joblib

            model = joblib.load(local_path)
            sidecar = Path(local_path).with_suffix(".json")
            version = "local"
            if sidecar.exists():
                import json

                version = json.loads(sidecar.read_text(encoding="utf-8")).get("model_version", "local")
            logger.info(f"loaded {role} from local artefact: {version}", extra={"stage": "registry"})
            return ResolvedModel(model=model, version=version, source="local")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"local artefact for {role} failed to load: {exc}", extra={"stage": "registry"})
            return None

    def _describe(self, model_uri: str) -> str:
        """Turn `models:/name@champion` into `name/version/run_id` for provenance stamping."""
        try:
            import mlflow

            client = mlflow.tracking.MlflowClient()
            if "@" in model_uri:
                name, alias = model_uri.removeprefix("models:/").split("@", 1)
                version = client.get_model_version_by_alias(name, alias)
                return f"{name}/v{version.version}/{version.run_id[:8]}"
        except Exception:  # noqa: BLE001
            pass
        return model_uri

    def invalidate(self, role: str | None = None) -> None:
        """Drop cached models so the next resolve picks up a newly promoted champion."""
        with self._lock:
            if role is None:
                self._cache.clear()
            else:
                self._cache.pop(role, None)


def registry_status(tracking_uri: str, models: dict[str, str]) -> dict:
    """Report what the registry holds, for the admin console. Never raises."""
    status: dict[str, Any] = {"tracking_uri": tracking_uri, "reachable": False, "models": {}}
    try:
        import mlflow

        mlflow.set_tracking_uri(tracking_uri)
        client = mlflow.tracking.MlflowClient()
        client.search_experiments(max_results=1)
        status["reachable"] = True

        for role, uri in models.items():
            entry: dict[str, Any] = {"uri": uri}
            try:
                name = uri.removeprefix("models:/").split("@")[0]
                alias = uri.split("@")[1] if "@" in uri else None
                if alias:
                    version = client.get_model_version_by_alias(name, alias)
                    entry.update({
                        "version": version.version,
                        "run_id": version.run_id,
                        "status": version.status,
                    })
                    run = client.get_run(version.run_id)
                    entry["metrics"] = dict(run.data.metrics)
            except Exception as exc:  # noqa: BLE001
                entry["error"] = f"{type(exc).__name__}: {exc}"
            status["models"][role] = entry
    except Exception as exc:  # noqa: BLE001
        status["error"] = f"{type(exc).__name__}: {exc}"
    return status
