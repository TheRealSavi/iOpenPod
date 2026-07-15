"""Repo-specific architecture guardrails for iOpenPod."""

from __future__ import annotations

import argparse
import ast
import json
from collections import defaultdict
from pathlib import Path

SOURCE_ROOT = Path("src")
PACKAGE_ROOT = SOURCE_ROOT / "iopenpod"
LEGACY_FIRST_PARTY_IMPORT_ROOTS = frozenset(
    {
        "ArtworkDB_Parser",
        "ArtworkDB_Shared",
        "ArtworkDB_Writer",
        "GUI",
        "PodcastManager",
        "SQLiteDB_Writer",
        "SyncEngine",
        "app_core",
        "infrastructure",
        "ipod_device",
        "iTunesDB_Analyzer",
        "iTunesDB_Parser",
        "iTunesDB_Shared",
        "iTunesDB_Writer",
        "sync_progress_stages",
    }
)
GUI_FORBIDDEN_PREFIXES = (
    "iopenpod.sync",
    "iopenpod.device",
    "iopenpod.podcasts",
    "settings",
    "iopenpod.infrastructure.settings_runtime",
)
FORBIDDEN_RUNTIME_PRIVATE_ATTRS = (
    "_device_path",
    "_is_loading",
    "_user_playlists",
)
MAIN_WINDOW_FORBIDDEN_SINGLETONS = (
    "DeviceManager",
    "iTunesDBCache",
)
RUNTIME_SINGLETONS = (
    "DeviceManager",
    "iTunesDBCache",
)
SETTINGS_RUNTIME_MODULE = "iopenpod.infrastructure.settings_runtime"
SETTINGS_RUNTIME_ALLOWED_PATHS = (
    "src/iopenpod/infrastructure/settings_runtime.py",
)
SETTINGS_RUNTIME_ALLOWED_PREFIXES = (
    "src/iopenpod/application/",
)
LEGACY_SETTINGS_RUNTIME_GLOBALS = (
    "_global_instance",
    "_effective_instance",
    "_active_device_state",
    "_active_device_root",
    "_active_device_key",
    "_active_device_use_global",
    "_settings_lock",
)
SYNC_REVIEW_FORBIDDEN_WORKERS = (
    "BackSyncWorker",
    "SyncExecuteWorker",
    "SyncWorker",
)
GUI_APP_FORBIDDEN_SYNC_SESSION_BYPASS = (
    "PodcastPlanRequest",
    "PodcastPlanWorker",
    "SyncDiffRequest",
    "SyncDiffWorker",
    "SyncExecuteWorker",
)
SYNC_EXECUTOR_PRIVATE_ATTRS = (
    "_SyncContext",
    "_build_and_evaluate_playlists",
    "_read_existing_database",
    "_track_dict_to_info",
)
SYNC_ENGINE_LOW_LEVEL_MODULES = {
    "iopenpod.sync.fingerprint_diff_engine": "FingerprintDiffEngine",
    "iopenpod.sync.sync_executor": "SyncExecutor",
}
SYNC_ENGINE_LOW_LEVEL_ALLOWED_PATHS = (
    "src/iopenpod/sync/__init__.py",
    "src/iopenpod/sync/core/engine.py",
    "src/iopenpod/sync/fingerprint_diff_engine.py",
    "src/iopenpod/sync/sync_executor.py",
)
DATABASE_COMMIT_ALLOWED_PATHS = (
    "src/iopenpod/sync/_db_io.py",
    "src/iopenpod/sync/database_commit.py",
)


def normalize_path(path: Path, repo_root: Path) -> str:
    """Return a stable forward-slash repo-relative path."""

    return path.relative_to(repo_root).as_posix()


def iter_python_files(repo_root: Path) -> list[Path]:
    """Return first-party Python files for architecture analysis."""

    package_root = repo_root / PACKAGE_ROOT
    if not package_root.exists():
        return []
    return sorted(package_root.rglob("*.py"))


def iter_namespace_consumers(repo_root: Path) -> list[Path]:
    """Return Python files that must import through the package namespace."""

    roots = (repo_root / PACKAGE_ROOT, repo_root / "scripts", repo_root / "tests")
    return sorted(path for root in roots if root.exists() for path in root.rglob("*.py"))


def parse_python(path: Path) -> ast.Module:
    """Parse a Python file using UTF-8 with graceful decoding."""

    return ast.parse(path.read_text(encoding="utf-8", errors="ignore"))


def module_matches_prefix(module: str, prefixes: tuple[str, ...]) -> bool:
    """Return whether *module* is a prefix itself or one of its children."""

    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in prefixes)


def detect_legacy_first_party_imports(repo_root: Path) -> dict[str, list[str]]:
    """Find imports that bypass the installed ``iopenpod`` namespace."""

    violations: dict[str, list[str]] = {}
    for path in iter_namespace_consumers(repo_root):
        try:
            tree = parse_python(path)
        except SyntaxError:
            continue

        hits: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if not node.level and module.split(".", 1)[0] in LEGACY_FIRST_PARTY_IMPORT_ROOTS:
                    hits.add(module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".", 1)[0] in LEGACY_FIRST_PARTY_IMPORT_ROOTS:
                        hits.add(alias.name)

        if hits:
            violations[normalize_path(path, repo_root)] = sorted(hits)
    return violations


def count_except_exception_passes(repo_root: Path) -> dict[str, int]:
    """Count `except Exception: pass` occurrences by file."""

    counts: dict[str, int] = {}
    for path in iter_python_files(repo_root):
        try:
            tree = parse_python(path)
        except SyntaxError:
            continue
        count = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if isinstance(node.type, ast.Name) and node.type.id == "Exception":
                    if any(isinstance(stmt, ast.Pass) for stmt in node.body):
                        count += 1
        if count:
            counts[normalize_path(path, repo_root)] = count
    return counts


def detect_gui_forbidden_imports(repo_root: Path) -> dict[str, list[str]]:
    """Find GUI modules that still reach directly into forbidden layers."""

    violations: dict[str, list[str]] = {}
    gui_root = repo_root / PACKAGE_ROOT / "gui"
    if not gui_root.exists():
        return violations

    for path in sorted(gui_root.rglob("*.py")):
        try:
            tree = parse_python(path)
        except SyntaxError:
            continue

        hits: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module_matches_prefix(module, GUI_FORBIDDEN_PREFIXES):
                    hits.add(module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    if module_matches_prefix(name, GUI_FORBIDDEN_PREFIXES):
                        hits.add(name)

        if hits:
            violations[normalize_path(path, repo_root)] = sorted(hits)

    return violations


def detect_forbidden_runtime_private_access(repo_root: Path) -> dict[str, list[str]]:
    """Find first-party modules that reach into runtime private state."""

    violations: dict[str, list[str]] = {}
    runtime_module = "src/iopenpod/application/runtime.py"

    for path in iter_python_files(repo_root):
        normalized = normalize_path(path, repo_root)
        if normalized == runtime_module:
            continue
        try:
            tree = parse_python(path)
        except SyntaxError:
            continue

        hits = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr in FORBIDDEN_RUNTIME_PRIVATE_ATTRS
        }
        if hits:
            violations[normalized] = sorted(hits)

    return violations


def detect_main_window_runtime_singleton_access(repo_root: Path) -> list[str]:
    """Find direct runtime singleton lookups in the main window shell."""

    path = repo_root / PACKAGE_ROOT / "gui" / "app.py"
    if not path.exists():
        return []

    try:
        tree = parse_python(path)
    except SyntaxError:
        return []

    hits: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "get_instance":
            continue
        if isinstance(func.value, ast.Name):
            name = func.value.id
            if name in MAIN_WINDOW_FORBIDDEN_SINGLETONS:
                hits.add(f"{name}.get_instance")

    return sorted(hits)


def count_runtime_singleton_access(repo_root: Path) -> dict[str, dict[str, int]]:
    """Count direct runtime singleton lookups outside the application layer."""

    counts: dict[str, dict[str, int]] = {}
    for path in iter_python_files(repo_root):
        normalized = normalize_path(path, repo_root)
        if normalized.startswith("src/iopenpod/application/"):
            continue

        try:
            tree = parse_python(path)
        except SyntaxError:
            continue

        path_counts: dict[str, int] = defaultdict(int)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "get_instance":
                continue
            if isinstance(func.value, ast.Name) and func.value.id in RUNTIME_SINGLETONS:
                path_counts[f"{func.value.id}.get_instance"] += 1

        if path_counts:
            counts[normalized] = dict(sorted(path_counts.items()))

    return counts


def detect_forbidden_settings_runtime_imports(repo_root: Path) -> dict[str, list[str]]:
    """Find modules outside the application layer importing settings runtime state."""

    violations: dict[str, list[str]] = {}
    for path in iter_python_files(repo_root):
        normalized = normalize_path(path, repo_root)
        if normalized in SETTINGS_RUNTIME_ALLOWED_PATHS:
            continue
        if normalized.startswith(SETTINGS_RUNTIME_ALLOWED_PREFIXES):
            continue

        try:
            tree = parse_python(path)
        except SyntaxError:
            continue

        hits: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == SETTINGS_RUNTIME_MODULE:
                    hits.add(module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    if name == SETTINGS_RUNTIME_MODULE:
                        hits.add(name)

        if hits:
            violations[normalized] = sorted(hits)

    return violations


def detect_legacy_settings_runtime_globals(repo_root: Path) -> list[str]:
    """Find old module-level mutable settings runtime state names."""

    path = repo_root / PACKAGE_ROOT / "infrastructure" / "settings_runtime.py"
    if not path.exists():
        return []

    try:
        tree = parse_python(path)
    except SyntaxError:
        return []

    hits: set[str] = set()
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue

        for target in targets:
            if (
                isinstance(target, ast.Name)
                and target.id in LEGACY_SETTINGS_RUNTIME_GLOBALS
            ):
                hits.add(target.id)

    return sorted(hits)


def detect_forbidden_sync_review_workers(repo_root: Path) -> list[str]:
    """Find operational workers that should not live in the sync review widget."""

    path = repo_root / PACKAGE_ROOT / "gui" / "widgets" / "syncReview.py"
    if not path.exists():
        return []

    try:
        tree = parse_python(path)
    except SyntaxError:
        return []

    return sorted(
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and node.name in SYNC_REVIEW_FORBIDDEN_WORKERS
    )


def detect_gui_app_sync_session_bypass(repo_root: Path) -> list[str]:
    """Find main-window imports that bypass the Sync Session module."""

    path = repo_root / PACKAGE_ROOT / "gui" / "app.py"
    if not path.exists():
        return []

    try:
        tree = parse_python(path)
    except SyntaxError:
        return []

    hits: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module not in {"iopenpod.application", "iopenpod.application.jobs"}:
            continue
        for alias in node.names:
            if alias.name in GUI_APP_FORBIDDEN_SYNC_SESSION_BYPASS:
                hits.add(alias.name)

    return sorted(hits)


def detect_application_sync_executor_private_usage(
    repo_root: Path,
) -> dict[str, list[str]]:
    """Find application-layer reaches into private SyncExecutor APIs."""

    violations: dict[str, list[str]] = {}
    application_root = repo_root / PACKAGE_ROOT / "application"
    if not application_root.exists():
        return violations

    for path in sorted(application_root.rglob("*.py")):
        try:
            tree = parse_python(path)
        except SyntaxError:
            continue

        hits: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "iopenpod.sync.sync_executor":
                    for alias in node.names:
                        if alias.name.startswith("_"):
                            hits.add(alias.name)
            elif (
                isinstance(node, ast.Attribute)
                and node.attr in SYNC_EXECUTOR_PRIVATE_ATTRS
            ):
                hits.add(node.attr)

        if hits:
            violations[normalize_path(path, repo_root)] = sorted(hits)

    return violations


def detect_sync_executor_private_usage(repo_root: Path) -> dict[str, list[str]]:
    """Find first-party reaches into private SyncExecutor APIs."""

    violations: dict[str, list[str]] = {}
    allowed_path = "src/iopenpod/sync/sync_executor.py"

    for path in iter_python_files(repo_root):
        normalized = normalize_path(path, repo_root)
        if normalized == allowed_path:
            continue

        try:
            tree = parse_python(path)
        except SyntaxError:
            continue

        hits: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "iopenpod.sync.sync_executor":
                    for alias in node.names:
                        if alias.name.startswith("_"):
                            hits.add(alias.name)
            elif (
                isinstance(node, ast.Attribute)
                and node.attr in SYNC_EXECUTOR_PRIVATE_ATTRS
            ):
                hits.add(node.attr)
            elif isinstance(node, ast.Name) and node.id in SYNC_EXECUTOR_PRIVATE_ATTRS:
                hits.add(node.id)

        if hits:
            violations[normalized] = sorted(hits)

    return violations


def detect_sync_engine_facade_bypass(repo_root: Path) -> dict[str, list[str]]:
    """Find production orchestration code bypassing the typed SyncEngine facade."""

    violations: dict[str, list[str]] = {}
    allowed_paths = set(SYNC_ENGINE_LOW_LEVEL_ALLOWED_PATHS)

    for path in iter_python_files(repo_root):
        normalized = normalize_path(path, repo_root)
        if normalized in allowed_paths:
            continue

        try:
            tree = parse_python(path)
        except SyntaxError:
            continue

        hits: set[str] = set()
        imported_low_level_names: set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                exported_name = SYNC_ENGINE_LOW_LEVEL_MODULES.get(module)
                if not exported_name:
                    continue
                for alias in node.names:
                    if alias.name == exported_name:
                        imported_name = alias.asname or alias.name
                        imported_low_level_names.add(imported_name)
                        hits.add(f"{module}.{alias.name}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    if name in SYNC_ENGINE_LOW_LEVEL_MODULES:
                        hits.add(name)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Name)
                and func.id in imported_low_level_names
            ):
                hits.add(func.id)
            elif (
                isinstance(func, ast.Attribute)
                and func.attr in SYNC_ENGINE_LOW_LEVEL_MODULES.values()
            ):
                module_name = _attribute_module_name(func.value)
                if module_name in SYNC_ENGINE_LOW_LEVEL_MODULES:
                    hits.add(f"{module_name}.{func.attr}")

        if hits:
            violations[normalized] = sorted(hits)

    return violations


def detect_database_commit_bypass(repo_root: Path) -> dict[str, list[str]]:
    """Find production code that bypasses the shared database commit module."""

    violations: dict[str, list[str]] = {}
    allowed_paths = set(DATABASE_COMMIT_ALLOWED_PATHS)

    for path in iter_python_files(repo_root):
        normalized = normalize_path(path, repo_root)
        if normalized in allowed_paths:
            continue

        try:
            tree = parse_python(path)
        except SyntaxError:
            continue

        hits: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module in {"iopenpod.sync._db_io", "._db_io"}:
                    for alias in node.names:
                        if alias.name == "write_database":
                            hits.add(alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "iopenpod.sync._db_io":
                        hits.add(alias.name)

        if hits:
            violations[normalized] = sorted(hits)

    return violations


def _attribute_module_name(node: ast.AST) -> str:
    parts: list[str] = []
    current: ast.AST | None = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def build_import_graph(repo_root: Path) -> dict[str, set[str]]:
    """Build the first-party import graph used for cycle detection."""

    modules: dict[str, Path] = {}
    source_root = repo_root / SOURCE_ROOT
    package_root = repo_root / PACKAGE_ROOT
    if not package_root.exists():
        return {}
    for path in package_root.rglob("*.py"):
        if path.name == "__init__.py":
            continue
        relative = path.relative_to(source_root).with_suffix("")
        parts = list(relative.parts)
        module_name = ".".join(parts)
        modules[module_name] = path

    prefix = "iopenpod"
    graph: dict[str, set[str]] = defaultdict(set)

    for module_name, path in modules.items():
        try:
            tree = parse_python(path)
        except SyntaxError:
            continue
        package = module_name.rsplit(".", 1)[0]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    if name.startswith(prefix) and name in modules:
                        graph[module_name].add(name)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = package.split(".")
                    up = node.level - 1
                    if up > 0:
                        base = base[:-up]
                    base_name = ".".join(base + ([node.module] if node.module else []))
                else:
                    base_name = node.module or ""

                if not base_name.startswith(prefix):
                    continue

                if base_name in modules:
                    graph[module_name].add(base_name)
                    continue

                for alias in node.names:
                    candidate = f"{base_name}.{alias.name}" if base_name else alias.name
                    if candidate in modules:
                        graph[module_name].add(candidate)

    return graph


def detect_import_cycles(repo_root: Path) -> list[list[str]]:
    """Return first-party import SCCs larger than size 1."""

    graph = build_import_graph(repo_root)
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def strongconnect(node: str) -> None:
        index = len(indices)
        indices[node] = index
        lowlinks[node] = index
        stack.append(node)
        on_stack.add(node)

        for neighbor in graph.get(node, ()):
            if neighbor not in indices:
                strongconnect(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif neighbor in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[neighbor])

        if lowlinks[node] == indices[node]:
            component: list[str] = []
            while True:
                item = stack.pop()
                on_stack.remove(item)
                component.append(item)
                if item == node:
                    break
            if len(component) > 1:
                components.append(sorted(component))

    for node in graph:
        if node not in indices:
            strongconnect(node)

    return sorted(components, key=lambda items: (len(items), items))


def load_rules(path: Path) -> dict:
    """Load the architecture rules JSON."""

    return json.loads(path.read_text(encoding="utf-8"))


def check_rules(repo_root: Path, rules: dict) -> list[str]:
    """Compare current repo state to the allowed architecture baseline."""

    errors: list[str] = []

    legacy_imports = detect_legacy_first_party_imports(repo_root)
    if legacy_imports:
        errors.append("Legacy first-party imports outside iopenpod detected:")
        for path, imports in sorted(legacy_imports.items()):
            errors.append(f"  - {path}: {', '.join(imports)}")

    allowed_cycles = {
        tuple(sorted(cycle))
        for cycle in rules.get("allowed_import_cycles", [])
    }
    current_cycles = [tuple(cycle) for cycle in detect_import_cycles(repo_root)]
    unexpected_cycles = [
        cycle for cycle in current_cycles if cycle not in allowed_cycles
    ]
    if unexpected_cycles:
        errors.append("Unexpected import cycles detected:")
        for cycle in unexpected_cycles:
            errors.append(f"  - {' -> '.join(cycle)}")

    allowed_gui_public_imports = set(rules.get("allowed_gui_public_imports", []))
    allowed_gui_imports = rules.get("allowed_gui_forbidden_imports", {})
    current_gui_imports = detect_gui_forbidden_imports(repo_root)
    unexpected_gui_imports: list[str] = []
    for path, imports in sorted(current_gui_imports.items()):
        allowed = allowed_gui_public_imports | set(allowed_gui_imports.get(path, []))
        unexpected = sorted(set(imports) - allowed)
        if unexpected:
            detail = ", ".join(unexpected)
            unexpected_gui_imports.append(f"  - {path}: {detail}")
    if unexpected_gui_imports:
        errors.append("Unexpected GUI cross-layer imports detected:")
        errors.extend(unexpected_gui_imports)

    current_runtime_private_access = detect_forbidden_runtime_private_access(repo_root)
    if current_runtime_private_access:
        errors.append("Unexpected access to runtime private state detected:")
        for path, attrs in sorted(current_runtime_private_access.items()):
            errors.append(f"  - {path}: {', '.join(attrs)}")

    singleton_access = detect_main_window_runtime_singleton_access(repo_root)
    if singleton_access:
        errors.append("Unexpected main-window runtime singleton access detected:")
        for name in singleton_access:
            errors.append(f"  - {name}")

    allowed_runtime_singletons = rules.get("allowed_runtime_singleton_access", {})
    current_runtime_singletons = count_runtime_singleton_access(repo_root)
    unexpected_runtime_singletons: list[str] = []
    for path, counts in sorted(current_runtime_singletons.items()):
        allowed_counts = allowed_runtime_singletons.get(path, {})
        for name, count in sorted(counts.items()):
            allowed_count = int(allowed_counts.get(name, 0))
            if count > allowed_count:
                unexpected_runtime_singletons.append(
                    f"  - {path}: {name} {count} > {allowed_count}"
                )
    if unexpected_runtime_singletons:
        errors.append("Unexpected runtime singleton access detected:")
        errors.extend(unexpected_runtime_singletons)

    settings_runtime_imports = detect_forbidden_settings_runtime_imports(repo_root)
    if settings_runtime_imports:
        errors.append("Unexpected direct settings runtime imports detected:")
        for path, imports in sorted(settings_runtime_imports.items()):
            errors.append(f"  - {path}: {', '.join(imports)}")

    legacy_settings_globals = detect_legacy_settings_runtime_globals(repo_root)
    if legacy_settings_globals:
        errors.append("Legacy module-level settings runtime globals detected:")
        errors.append(f"  - {', '.join(legacy_settings_globals)}")

    sync_review_workers = detect_forbidden_sync_review_workers(repo_root)
    if sync_review_workers:
        errors.append("Operational sync workers detected in GUI sync review:")
        errors.append(f"  - {', '.join(sync_review_workers)}")

    sync_session_bypass = detect_gui_app_sync_session_bypass(repo_root)
    if sync_session_bypass:
        errors.append("Main-window imports that bypass Sync Session detected:")
        errors.append(f"  - {', '.join(sync_session_bypass)}")

    sync_executor_private_usage = detect_sync_executor_private_usage(repo_root)
    if sync_executor_private_usage:
        errors.append("Private SyncExecutor API usage detected outside SyncEngine:")
        for path, names in sorted(sync_executor_private_usage.items()):
            errors.append(f"  - {path}: {', '.join(names)}")

    sync_engine_facade_bypass = detect_sync_engine_facade_bypass(repo_root)
    if sync_engine_facade_bypass:
        errors.append("Direct SyncEngine planner/executor orchestration detected:")
        for path, names in sorted(sync_engine_facade_bypass.items()):
            errors.append(f"  - {path}: {', '.join(names)}")

    database_commit_bypass = detect_database_commit_bypass(repo_root)
    if database_commit_bypass:
        errors.append("Raw database writer imports detected outside commit module:")
        for path, names in sorted(database_commit_bypass.items()):
            errors.append(f"  - {path}: {', '.join(names)}")

    allowed_except_pass = rules.get("allowed_except_exception_pass_counts", {})
    current_except_pass = count_except_exception_passes(repo_root)
    unexpected_except_pass: list[str] = []
    for path, count in sorted(current_except_pass.items()):
        allowed_count = int(allowed_except_pass.get(path, 0))
        if count > allowed_count:
            unexpected_except_pass.append(f"  - {path}: {count} > {allowed_count}")
    if unexpected_except_pass:
        errors.append("Unexpected growth in `except Exception: pass` usage:")
        errors.extend(unexpected_except_pass)

    return errors


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for CI and local health checks."""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root to analyze.",
    )
    parser.add_argument(
        "--rules",
        default="scripts/architecture_rules.json",
        help="Path to the architecture rules JSON.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    rules_path = (repo_root / args.rules).resolve()
    rules = load_rules(rules_path)
    errors = check_rules(repo_root, rules)
    if errors:
        raise SystemExit("\n".join(errors))

    print("ARCHITECTURE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
