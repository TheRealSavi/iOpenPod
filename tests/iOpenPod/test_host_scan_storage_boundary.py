"""Keep Host scanning and media ingestion on Storage-owned file access.

This structural regression guard covers direct filesystem calls and the parser
entry points that previously reopened filenames. It is not a runtime sandbox.
"""

import ast
from pathlib import Path
from textwrap import dedent

import pytest

_PROTECTED_MODULES = (
    "host_media_library.py",
    "host_media_fingerprint.py",
    "host_media_folders.py",
    "host_playlists.py",
    "host_media_controller.py",
    "library_sync_helper.py",
    "media/inspection.py",
    "media/importing.py",
    "artwork_import.py",
)
_FILESYSTEM_METHODS = frozenset(
    {
        "open",
        "stat",
        "lstat",
        "exists",
        "is_file",
        "is_dir",
        "is_symlink",
        "is_junction",
        "iterdir",
        "glob",
        "rglob",
        "resolve",
        "read_bytes",
        "read_text",
        "write_bytes",
        "write_text",
        "mkdir",
        "rmdir",
        "unlink",
        "rename",
        "touch",
    }
)
_OS_FILESYSTEM_CALLS = _FILESYSTEM_METHODS | {
    "access",
    "fstat",
    "listdir",
    "scandir",
    "walk",
    "fwalk",
    "readlink",
    "read",
    "write",
    "fdopen",
    "remove",
    "replace",
    "makedirs",
    "removedirs",
    "truncate",
    "link",
    "symlink",
    "system",
    "popen",
}
_OS_PATH_FILESYSTEM_CALLS = {
    "exists",
    "lexists",
    "isfile",
    "isdir",
    "islink",
    "isjunction",
    "ismount",
    "getsize",
    "getmtime",
    "getatime",
    "getctime",
    "samefile",
    "realpath",
}
_PROCESS_MODULES = {"subprocess", "tempfile", "shutil"}
_PARSERS = {"PIL.Image.open", "mutagen.File"}


def _violations(source: str) -> list[str]:
    tree = ast.parse(dedent(source))
    imports: dict[str, str] = {}
    problems: list[str] = []
    for node in ast.walk(tree):
        modules: tuple[str, ...]
        if isinstance(node, ast.Import):
            modules = tuple(alias.name for alias in node.names)
            for alias in node.names:
                imports[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom):
            modules = (node.module or "",)
            for alias in node.names:
                imports[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        else:
            continue
        if any(module.split(".")[0] in _PROCESS_MODULES for module in modules):
            problems.append(f"{node.lineno}: direct filesystem/process import")

    def name(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return imports.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            return f"{name(node.value)}.{node.attr}"
        if (
            isinstance(node, ast.Call)
            and name(node.func) in {"typing.cast", "cast"}
            and len(node.args) == 2
        ):
            return name(node.args[1])
        return ""

    def storage_type(node: ast.AST) -> bool:
        return any(
            name(part).startswith("storage.")
            and name(part).rsplit(".", 1)[-1] not in {"HostPath", "DevicePath"}
            for part in ast.walk(node)
            if isinstance(part, (ast.Name, ast.Attribute))
        )

    storage_values: set[str] = set()
    storage_fields: set[str] = set()
    storage_functions: set[str] = set()
    streams: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and node.annotation is not None:
            if storage_type(node.annotation):
                storage_values.add(node.arg)
            if name(node.annotation) in {"typing.BinaryIO", "BinaryIO"}:
                streams.add(node.arg)
        elif isinstance(node, ast.AnnAssign) and storage_type(node.annotation):
            storage_values.add(name(node.target))
            if isinstance(node.target, ast.Name):
                storage_fields.add(node.target.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.returns is not None and storage_type(node.returns):
                storage_functions.add(node.name)
        elif (
            isinstance(node, ast.withitem)
            and isinstance(node.context_expr, ast.Call)
            and isinstance(node.context_expr.func, ast.Attribute)
            and node.context_expr.func.attr == "open_read"
            and node.optional_vars is not None
        ):
            streams.add(name(node.optional_vars))

    def storage_value(node: ast.AST) -> bool:
        if name(node) in storage_values:
            return True
        if isinstance(node, ast.Attribute) and node.attr in storage_fields:
            return True
        return isinstance(node, ast.Call) and (
            storage_type(node.func) or name(node.func) in storage_functions
        )

    def stream_value(node: ast.AST) -> bool:
        return name(node) in streams or (
            isinstance(node, ast.Call) and name(node.func) == "io.BytesIO"
        )

    # Follow ordinary aliases and injected Storage members, without tying the
    # guard to application variable names or exact lines in these modules.
    assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)]
    for _ in range(len(assignments) + 1):
        before = (len(storage_values), len(streams))
        for node in assignments:
            for target in node.targets:
                if storage_value(node.value):
                    storage_values.add(name(target))
                if stream_value(node.value):
                    streams.add(name(target))
        if before == (len(storage_values), len(streams)):
            break

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = name(node.func)
        if called in _PARSERS:
            argument = (
                node.args[0]
                if node.args
                else next(
                    (
                        item.value
                        for item in node.keywords
                        if item.arg in {"fp", "fileobj"}
                    ),
                    None,
                )
            )
            if argument is None or not stream_value(argument):
                problems.append(
                    f"{node.lineno}: parser requires a Storage or memory stream"
                )
        elif (
            called in {"open", "builtins.open", "io.open", "io.FileIO"}
            or (
                called.removeprefix("os.") in _OS_FILESYSTEM_CALLS
                and called.startswith("os.")
            )
            or (
                called.removeprefix("os.path.") in _OS_PATH_FILESYSTEM_CALLS
                and called.startswith("os.path.")
            )
            or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in _FILESYSTEM_METHODS
                and not storage_value(node.func.value)
            )
        ):
            problems.append(f"{node.lineno}: filesystem call outside Storage: {called}")
    return problems


def test_host_scan_and_ingestion_access_files_only_through_storage() -> None:
    app_root = Path(__file__).resolve().parents[2] / "src/iOpenPod/app"
    problems = [
        f"{module}:{problem}"
        for module in _PROTECTED_MODULES
        for problem in _violations((app_root / module).read_text(encoding="utf-8"))
    ]
    assert not problems, "Host media bypasses Storage:\n" + "\n".join(problems)


@pytest.mark.parametrize(
    "source",
    [
        "from pathlib import Path; Path('song.mp3').stat()",
        "from os import scandir as entries; entries('Music')",
        "import os; os.path.getsize('song.mp3')",
        "import tempfile; tempfile.TemporaryDirectory()",
        "from subprocess import Popen; Popen(['fpcalc', 'song.mp3'])",
        "import shutil; shutil.which('ffprobe')",
        "from builtins import open as read; read('song.mp3', 'rb')",
        "from PIL import Image; Image.open(source.path)",
        'import mutagen; from typing import cast; cast("Reader", mutagen).File(filename)',
    ],
)
def test_guard_detects_filesystem_and_filename_parser_regressions(source: str) -> None:
    assert _violations(source)


def test_guard_allows_storage_reads_and_lexical_path_operations() -> None:
    assert not _violations(
        """
        import os
        import mutagen
        from io import BytesIO
        from pathlib import Path
        from PIL import Image
        from storage import AtomicHostFile, FilesystemSession, HostPath
        from storage.host_input import LocalHostFile

        def inspect(source: LocalHostFile, session: FilesystemSession,
                    cache: AtomicHostFile) -> None:
            filename = os.path.normcase(os.path.abspath(Path('music') / 'song.mp3'))
            Path(filename).is_absolute()
            observed = LocalHostFile.observe(HostPath(filename))
            with observed.open_read() as stream:
                parsed = mutagen.File(stream)
            session.stat('iPod_Control/Music/F00/AAAA.mp3')
            cache.read_bytes()
            Image.open(BytesIO(source.read_bytes(max_bytes=1024)))
        """
    )
