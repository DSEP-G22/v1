"""SAD Figure 14 import rules: no services.X imports services.Y; only delivery_gateway imports
MailGatewayPort; only action_svc imports ActionAdapterPort."""

from __future__ import annotations

import ast
from pathlib import Path

_SERVICES_ROOT = Path(__file__).resolve().parents[2] / "services"


def _iter_service_files():
    if not _SERVICES_ROOT.exists():
        return
    for package_dir in sorted(_SERVICES_ROOT.iterdir()):
        if not package_dir.is_dir() or package_dir.name.startswith("__"):
            continue
        for py_file in package_dir.rglob("*.py"):
            yield package_dir.name, py_file


def _imported_names(py_file: Path) -> list[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
            names.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return names

# retrieval_svc is explicitly "a library, not a consumer" (implementation plan §5 item 8): it
# owns no table and no topic, so any service may import it directly without violating the
# single-service-boundary rule this test otherwise enforces.
#
# knowledge_ingest is the same shape: it consumes no topic and is invoked synchronously by
# scripts/seed.py and by the admin API's UI-6 onboarding upload, because ingesting a document is
# a request/response operation whose per-document report the administrator must see immediately.
# It still owns knowledge_document/knowledge_chunk exclusively, test_single_writer.py enforces
# that, so importing it does not grant anyone else write access to those tables.
# Packages under services/ that are libraries rather than broker consumers: they subscribe to no
# topic, own their tables exclusively, and are called synchronously by whoever needs them.
# feedback_svc harvests a training example in the same transaction boundary as the decision that
# produced it, deliberately: routing it through a topic would mean a dropped event silently costs
# a training label, and the label is the whole point of the continuous-learning loop.
_LIBRARY_SERVICES = {"retrieval_svc", "knowledge_ingest", "feedback_svc"}

# workspace_api is the one place a human agent acts, and REQ-WKS explicitly requires it to
# trigger delivery (approve) and action execution (execute) synchronously and to keep the queue
# projection in sync after a lock/approve/reject, so it calls those services' public functions
# directly rather than through an async topic. This is the single documented exception to "no
# service imports another service"; it does NOT grant table access (test_single_writer.py still
# enforces that each table has exactly one writer).
_ALLOWED_CROSS_SERVICE_IMPORTS: dict[str, set[str]] = {
    "workspace_api": {"action_svc", "delivery_gateway", "projector_svc"},
}


def test_no_service_imports_another_service():
    violations: list[str] = []
    for package, py_file in _iter_service_files():
        allowed = _ALLOWED_CROSS_SERVICE_IMPORTS.get(package, set())
        for name in _imported_names(py_file):
            if not name.startswith("services."):
                continue
            imported_package = name.split(".")[1]
            if imported_package == package:
                continue
            if imported_package in _LIBRARY_SERVICES or imported_package in allowed:
                continue
            violations.append(f"{py_file.relative_to(_SERVICES_ROOT.parent)}: imports {name}")

    assert not violations, "cross-service imports found:\n" + "\n".join(violations)


def test_only_delivery_gateway_imports_mail_gateway_port():
    violations: list[str] = []
    for package, py_file in _iter_service_files():
        if package == "delivery_gateway":
            continue
        if "libs.domain.ports.mail_gateway" in _imported_names(py_file) or any(
            "MailGatewayPort" in n for n in _imported_names(py_file)
        ):
            violations.append(str(py_file.relative_to(_SERVICES_ROOT.parent)))

    assert not violations, f"only delivery_gateway may import MailGatewayPort: {violations}"


def test_only_action_svc_imports_action_adapter_port():
    violations: list[str] = []
    for package, py_file in _iter_service_files():
        if package == "action_svc":
            continue
        if "libs.domain.ports.action_adapter" in _imported_names(py_file) or any(
            "ActionAdapterPort" in n for n in _imported_names(py_file)
        ):
            violations.append(str(py_file.relative_to(_SERVICES_ROOT.parent)))

    assert not violations, f"only action_svc may import ActionAdapterPort: {violations}"
