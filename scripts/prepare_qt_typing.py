"""Prepare shared editor/Mypy corrections without changing installed Qt files."""

import ast
import shutil
from collections import defaultdict
from importlib.metadata import distribution
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
MARKER = ".iopenpod-generated"
SUPPORTED_VERSION = "6.9.3"


def merge_stub(source: str, corrections: str) -> str:
    """Merge explicit members into existing classes, preserving other signatures."""
    lines = source.splitlines(keepends=True)
    patch_lines = corrections.splitlines(keepends=True)
    edits: list[tuple[int, int, list[str]]] = []

    def merge(
        original: ast.Module | ast.ClassDef, patch: ast.Module | ast.ClassDef
    ) -> None:
        members: dict[str, list[ast.FunctionDef | ast.ClassDef]] = defaultdict(list)
        for node in original.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                members[node.name].append(node)
        replacements: dict[str, list[ast.FunctionDef]] = defaultdict(list)
        fields: list[str] = []
        for node in patch.body:
            if isinstance(node, ast.ClassDef):
                matches = members.get(node.name, [])
                if len(matches) != 1 or not isinstance(matches[0], ast.ClassDef):
                    raise ValueError(f"Expected existing class: {node.name}")
                merge(matches[0], node)
            elif isinstance(node, ast.FunctionDef):
                replacements[node.name].append(node)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if not isinstance(original, ast.ClassDef):
                    raise ValueError("Field corrections must belong to a class")
                if any(
                    isinstance(member, ast.AnnAssign)
                    and isinstance(member.target, ast.Name)
                    and member.target.id == node.target.id
                    for member in original.body
                ):
                    raise ValueError(f"Field already declared: {node.target.id}")
                fields.append(
                    " " * (original.col_offset + 4) + ast.unparse(node) + "\n"
                )
            else:
                raise ValueError(f"Unsupported correction: {ast.dump(node)}")
        if fields:
            assert isinstance(original, ast.ClassDef)
            edits.append((original.lineno, original.lineno, fields))
        for name, nodes in replacements.items():
            old = members.get(name, [])
            if not old or not all(isinstance(node, ast.FunctionDef) for node in old):
                raise ValueError(f"Expected existing method: {name}")
            first = old[0]
            assert isinstance(first, ast.FunctionDef)
            start = (
                min([first.lineno, *(item.lineno for item in first.decorator_list)]) - 1
            )
            stop = old[-1].end_lineno
            assert stop is not None
            between = [
                member for member in original.body if start < member.lineno <= stop
            ]
            if between != old:
                raise ValueError(f"Non-contiguous overloads: {name}")
            replacement_start = (
                min(
                    [
                        nodes[0].lineno,
                        *(item.lineno for item in nodes[0].decorator_list),
                    ]
                )
                - 1
            )
            replacement_stop = nodes[-1].end_lineno
            assert replacement_stop is not None
            indent = " " * first.col_offset
            replacement = [
                indent + line[nodes[0].col_offset :]
                for line in patch_lines[replacement_start:replacement_stop]
            ]
            edits.append((start, stop, replacement))

    merge(ast.parse(source), ast.parse(corrections))
    for start, stop, replacement in sorted(edits, reverse=True):
        lines[start:stop] = replacement
    result = "".join(lines)
    ast.parse(result)
    return result


def prepare_qt_typing(root: Path = ROOT) -> bool:
    """Generate a version-specific, typing-only package; clear stale owned output."""
    target = root / "typings" / "PySide6"
    if target.exists() and not (target / MARKER).is_file():
        raise ValueError(f"Refusing to replace unrecognized stubs: {target}")
    installed = distribution("PySide6-Essentials")
    if installed.version != SUPPORTED_VERSION:
        if target.exists():
            shutil.rmtree(target)
        return False
    source = Path(str(installed.locate_file("PySide6")))
    patches = root / "typings" / "patches"
    for patch in patches.glob("*.pyi"):
        if not (source / patch.name).is_file():
            raise ValueError(f"Missing installed Qt stub: {patch.name}")
    with TemporaryDirectory(prefix=".qt-typing-", dir=target.parent) as temporary:
        staged = Path(temporary) / "PySide6"
        staged.mkdir()
        for path in source.glob("*.pyi"):
            content = path.read_text(encoding="utf-8")
            patch = patches / path.name
            if patch.is_file():
                content = merge_stub(content, patch.read_text(encoding="utf-8"))
            (staged / path.name).write_text(content, encoding="utf-8")
        # The upstream package has no __init__.pyi. A stub package must have one
        # so Mypy can resolve the overlay before site-packages.
        (staged / "__init__.pyi").write_text("__version__: str\n", encoding="utf-8")
        (staged / "py.typed").touch()
        (staged / MARKER).write_text(SUPPORTED_VERSION + "\n", encoding="utf-8")
        if target.exists():
            shutil.rmtree(target)
        staged.rename(target)
    return True


if __name__ == "__main__":
    if prepare_qt_typing():
        print("Prepared Qt 6.9.3 typing corrections for Pylance and Mypy.")
    else:
        print("Using this Qt version's bundled type information.")
