"""SAD §5.2.2 single-writer rule: each table is written by exactly one service package.
Statically greps (via ast) each services/* package for repository *write* method calls against
tables it does not own, per libs/platform/db/ownership.WRITE_METHOD_OWNERS."""

from __future__ import annotations

import ast
from pathlib import Path

from libs.platform.db.ownership import WRITE_METHOD_OWNERS

_SERVICES_ROOT = Path(__file__).resolve().parents[2] / "services"


def _repo_class_for_call(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name) and call.func.id in WRITE_METHOD_OWNERS:
        return call.func.id
    return None


def _find_violations_in_file(path: Path, package: str) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    # var_name -> RepoClassName, for `var = RepoClass(...)` assignments (module- and
    # function-scoped alike; good enough for this codebase's straight-line handler style).
    var_to_class: dict[str, str] = {}
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            repo_class = _repo_class_for_call(node.value)
            if repo_class is not None:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        var_to_class[target.id] = repo_class

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        method_name = node.func.attr
        receiver = node.func.value

        repo_class: str | None = None
        if isinstance(receiver, ast.Call):
            repo_class = _repo_class_for_call(receiver)
        elif isinstance(receiver, ast.Name) and receiver.id in var_to_class:
            repo_class = var_to_class[receiver.id]

        if repo_class is None:
            continue

        method_owners = WRITE_METHOD_OWNERS.get(repo_class, {})
        if method_name not in method_owners:
            continue  # not a tracked mutating method (or a read method) -> unrestricted

        allowed_packages = method_owners[method_name]
        if package not in allowed_packages:
            violations.append(
                f"{path.relative_to(_SERVICES_ROOT.parent)}:{node.lineno}: "
                f"{package} calls {repo_class}.{method_name}() but only {sorted(allowed_packages)} may"
            )

    return violations


def test_no_service_writes_a_table_it_does_not_own():
    all_violations: list[str] = []
    if not _SERVICES_ROOT.exists():
        return

    for package_dir in sorted(_SERVICES_ROOT.iterdir()):
        if not package_dir.is_dir() or package_dir.name.startswith("__"):
            continue
        package = package_dir.name
        for py_file in package_dir.rglob("*.py"):
            all_violations.extend(_find_violations_in_file(py_file, package))

    assert not all_violations, "single-writer violations:\n" + "\n".join(all_violations)
