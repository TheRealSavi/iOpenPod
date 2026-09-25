"""Prevent database-format knowledge from returning to application consumers."""

import ast
from pathlib import Path


def test_application_imports_only_the_public_library_contract() -> None:
    source_root = Path(__file__).resolve().parents[2] / "src" / "iOpenPod"
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
                if module.startswith("iPodDB") and module != "iPodDB.library"
            )
    assert not violations, "Application bypasses the Library contract:\n" + "\n".join(
        violations
    )
