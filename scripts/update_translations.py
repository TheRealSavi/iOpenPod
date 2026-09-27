"""Extract Qt catalogs, including display copy carried by application contracts.

Run through UV, for example ``uv run python scripts/update_translations.py de``.
The application layer stays independent of Qt translation APIs. Supplemental
markers are generated from its sources, never maintained as a second copy list.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from iOpenPod.app.metadata_fields import metadata_fields
from iOpenPod.app.models.track_columns import track_column_groups

if TYPE_CHECKING:
    from collections.abc import Iterator

ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS = ROOT / "src/iOpenPod/GUI/presentation/i18n/translations"

# Position and keyword in the corresponding application display contract.
_CONTRACT_FIELDS: dict[str, tuple[tuple[int, str], ...]] = {
    "WriteProgress": ((1, "message"), (5, "unit")),
    "MediaPreparationProgress": ((1, "message"),),
    "HostMediaScanProgress": ((3, "message"),),
    "IPodMediaScanProgress": ((3, "message"),),
    "BackupProgress": ((3, "message"),),
    "ExportProgress": ((2, "message"),),
    "BackupFailure": ((1, "summary"), (2, "action")),
    "BackupDiagnostic": ((1, "summary"),),
    "WriteIssue": ((1, "message"),),
    "WriteEffect": ((3, "reason"),),
    "DeviceCandidateIssue": ((1, "detail"),),
    "DeviceDiscoveryIssue": ((1, "detail"),),
    "HostMediaScanIssue": ((1, "detail"),),
    "PlaylistExternalReference": ((3, "detail"),),
    "IPodMediaScanIssue": ((1, "detail"),),
    "PodcastIssue": ((1, "message"),),
    "PodcastOperationFailure": ((1, "message"),),
    "DeviceOperationFailure": ((1, "message"),),
    "BackupOperationFailure": ((1, "message"),),
    "ArtworkLoadFailure": ((1, "message"),),
    "PhotoLoadFailure": ((2, "message"),),
    "PodcastArtworkFailure": ((1, "message"),),
    "PlaybackFailure": ((2, "message"),),
    "DeviceEjectCompletion": ((1, "detail"),),
}

_INPUT_VALIDATION_FILES = {
    "metadata_fields.py",
    "library_workspace.py",
    "tag_normalization_controller.py",
    "smart_rules.py",
}


def _literals(node: ast.AST) -> Iterator[str]:
    """Read complete literal alternatives, never pieces of formatted messages."""

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        if node.value:
            yield node.value
    elif isinstance(node, ast.IfExp):
        yield from _literals(node.body)
        yield from _literals(node.orelse)
    elif isinstance(node, ast.BoolOp):
        for value in node.values:
            yield from _literals(value)


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    return node.func.attr if isinstance(node.func, ast.Attribute) else ""


def _forwarded_fields(
    tree: ast.Module,
) -> dict[str, tuple[tuple[int, str], ...]]:
    """Follow local helper parameters into known display-message contracts."""

    fields = dict(_CONTRACT_FIELDS)
    fields["source_text"] = ((0, "source"),)
    functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    while True:
        previous = dict(fields)
        for function in functions:
            parameters = [arg.arg for arg in function.args.args]
            if parameters and parameters[0] in {"self", "cls"}:
                parameters = parameters[1:]
            keyword_parameters = {arg.arg for arg in function.args.kwonlyargs}
            forwarded = set(fields.get(function.name, ()))
            for call in ast.walk(function):
                if not isinstance(call, ast.Call):
                    continue
                for position, keyword in fields.get(_call_name(call), ()):
                    values = [kw.value for kw in call.keywords if kw.arg == keyword]
                    if 0 <= position < len(call.args):
                        values.append(call.args[position])
                    for value in values:
                        if isinstance(value, ast.Name) and value.id in parameters:
                            forwarded.add((parameters.index(value.id), value.id))
                        elif (
                            isinstance(value, ast.Name)
                            and value.id in keyword_parameters
                        ):
                            forwarded.add((-1, value.id))
            if forwarded:
                fields[function.name] = tuple(sorted(forwarded))
        if fields == previous:
            return fields


def application_sources(path: Path) -> set[tuple[str, str]]:
    """Collect literal display fields while leaving IDs and external data alone."""

    entries: set[tuple[str, str]] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forwarded = _forwarded_fields(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Attribute) and target.attr == "message"
            for target in node.targets
        ):
            entries.update(("Workflow", source) for source in _literals(node.value))
        if (
            path.name in _INPUT_VALIDATION_FILES
            and isinstance(node, ast.Raise)
            and isinstance(node.exc, ast.Call)
            and node.exc.args
        ):
            entries.update(
                ("Workflow", source) for source in _literals(node.exc.args[0])
            )
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        fields = forwarded.get(name, ())
        for position, keyword in fields:
            values = [kw.value for kw in node.keywords if kw.arg == keyword]
            if 0 <= position < len(node.args):
                values.append(node.args[position])
            for value in values:
                for source in _literals(value):
                    entries.add(("Workflow", source))
    return entries


def supplemental_sources(root: Path = ROOT) -> set[tuple[str, str]]:
    """Materialize dynamic labels and application messages for Qt Linguist."""

    entries: set[tuple[str, str]] = set()
    for package in ("iOpenPod", "iPodDB"):
        for path in (root / "src" / package).rglob("*.py"):
            entries.update(application_sources(path))
    for field in metadata_fields():
        entries.add(("MetadataFields", field.label))
        entries.add(("MetadataEditorDialog", field.group))
    # Column groups are application presentation data used by the table menu.
    for label, _columns in track_column_groups():
        entries.add(("TrackTable", label))
    return entries


def extract_catalogs(catalogs: list[Path], *, root: Path = ROOT) -> None:
    """Update catalogs with the locked PySide6 tool and preserve translations."""

    for catalog in catalogs:
        catalog.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="iopenpod-translations-") as directory:
        marker_path = Path(directory) / "application_messages.py"
        marker_path.write_text(
            "\n".join(
                f"QT_TRANSLATE_NOOP({json.dumps(context)}, "
                f"{json.dumps(source, ensure_ascii=False)})"
                for context, source in sorted(supplemental_sources(root))
            ),
            encoding="utf-8",
        )
        sources = sorted((root / "src/iOpenPod").rglob("*.py"))
        source_list = Path(directory) / "sources.txt"
        source_list.write_text(
            "\n".join(str(path) for path in (*sources, marker_path)),
            encoding="utf-8",
        )
        # Explicit Python paths are required: directory scans silently skip .py.
        subprocess.run(
            [
                "pyside6-lupdate",
                f"@{source_list}",
                "-source-language",
                "en",
                "-locations",
                "none",
                "-ts",
                *(str(path) for path in catalogs),
            ],
            check=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "languages", nargs="+", help="Qt language tags, for example de or pt_BR"
    )
    arguments = parser.parse_args()
    languages: list[str] = arguments.languages
    if any(
        not language.replace("_", "").isalnum() or not language[0].isalpha()
        for language in languages
    ):
        parser.error("Use language tags containing letters, digits, and underscores.")
    extract_catalogs([TRANSLATIONS / f"iopenpod_{tag}.ts" for tag in languages])


if __name__ == "__main__":
    main()
