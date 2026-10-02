"""Prevent database-format knowledge from returning to application consumers."""

import ast
from pathlib import Path


def test_application_imports_only_public_ipoddb_contracts() -> None:
    source_root = Path(__file__).resolve().parents[2] / "src" / "iOpenPod"
    # Preferences and captured time evidence are separate public contracts added
    # by ADR-0097/0098. Their implementation submodules remain private.
    public_modules = {"iPodDB.library", "iPodDB.preferences", "iPodDB.device_time"}
    violations: list[str] = []
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules: tuple[str, ...]
            if isinstance(node, ast.ImportFrom):
                modules = (node.module or "",)
            elif isinstance(node, ast.Import):
                modules = tuple(alias.name for alias in node.names)
            else:
                continue
            violations.extend(
                f"{path.relative_to(source_root)}:{node.lineno}: {module}"
                for module in modules
                if module.startswith("iPodDB") and module not in public_modules
            )
    assert not violations, (
        "Application bypasses public iPodDB contracts:\n" + "\n".join(violations)
    )
