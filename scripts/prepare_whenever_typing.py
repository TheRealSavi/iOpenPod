"""Prepare version-bound Whenever annotations for strict Pylance and Mypy.

Whenever 0.11 uses typing_extensions.sentinel and singleton types from PEP 661.
The supported checkers do not yet understand that spelling. A private nominal
type models SYSTEM_TZ in the generated stub; runtime imports remain untouched.
"""

import ast
from importlib.metadata import distribution
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
MARKER = ".iopenpod-generated"
SUPPORTED_VERSION = "0.11.0"
_FILES = frozenset(
    ("__init__.pyi", "py.typed", "LICENSE", "LICENSE-THIRD-PARTY", MARKER)
)


def patch_stub(source: str) -> str:
    """Keep the installed API, changing only the unsupported singleton typing.

    Exact version and declaration checks make upstream drift fail visibly. The
    generated nominal class is type-checking-only, final and private; SYSTEM_TZ
    remains a constant accepted alongside IANA strings, never arbitrary objects.
    """
    changes = (
        (
            "from typing_extensions import Self, deprecated, sentinel",
            "from typing_extensions import Self, deprecated",
            1,
        ),
        (
            'SYSTEM_TZ = sentinel("SYSTEM_TZ")',
            "@type_check_only\n@final\nclass _SystemTimezone: ...\n\n"
            "SYSTEM_TZ: Final[_SystemTimezone]",
            1,
        ),
        ("str | SYSTEM_TZ", "str | _SystemTimezone", 13),
    )
    for old, new, count in changes:
        if source.count(old) != count:
            raise ValueError(f"Unexpected Whenever stub declaration: {old}")
        source = source.replace(old, new)
    ast.parse(source)
    return source


def _check_output(root: Path, target: Path) -> None:
    if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Typing output must stay inside the workspace: {target}")
    if not target.exists():
        return
    marker = target / MARKER
    if (
        not target.is_dir()
        or not marker.is_file()
        or marker.read_text(encoding="utf-8") != SUPPORTED_VERSION + "\n"
    ):
        raise ValueError(f"Refusing to replace unrecognized stubs: {target}")
    if any(
        path.name not in _FILES or not path.is_file() or path.is_symlink()
        for path in target.iterdir()
    ):
        raise ValueError(f"Unexpected files in generated typing output: {target}")


def _clear_output(target: Path) -> None:
    """Remove only the already-validated, explicitly owned files."""
    if target.exists():
        for path in target.iterdir():
            path.unlink()
        target.rmdir()


def prepare_whenever_typing(root: Path = ROOT) -> bool:
    """Generate a typing-only package; remove owned stale output after upgrades."""
    target = root / "typings" / "whenever"
    _check_output(root, target)
    installed = distribution("whenever")
    if installed.version != SUPPORTED_VERSION:
        _clear_output(target)
        return False
    source = Path(str(installed.locate_file("whenever/__init__.pyi")))
    corrected = patch_stub(source.read_text(encoding="utf-8"))
    licenses = {
        name: Path(
            str(
                installed.locate_file(
                    f"whenever-{SUPPORTED_VERSION}.dist-info/licenses/{name}"
                )
            )
        ).read_text(encoding="utf-8")
        for name in ("LICENSE", "LICENSE-THIRD-PARTY")
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".whenever-typing-", dir=target.parent) as temporary:
        staged = Path(temporary) / "whenever"
        staged.mkdir()
        (staged / "__init__.pyi").write_text(corrected, encoding="utf-8")
        (staged / "py.typed").touch()
        (staged / MARKER).write_text(SUPPORTED_VERSION + "\n", encoding="utf-8")
        for name, content in licenses.items():
            (staged / name).write_text(content, encoding="utf-8")
        _check_output(root, target)
        _clear_output(target)
        staged.rename(target)
    return True


if __name__ == "__main__":
    if prepare_whenever_typing():
        print("Prepared Whenever 0.11.0 typing corrections for Pylance and Mypy.")
    else:
        print("Using this Whenever version's bundled type information.")
