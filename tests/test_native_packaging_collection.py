"""Exercise native resource collection without running a platform freezer."""

import json
import runpy
import struct
from importlib import metadata
from pathlib import Path
from typing import Any

import pytest
from scripts import package_app


@pytest.mark.parametrize(
    "license_name", ["LICENSE.txt", "COPYING", "COPYING.LESSER", "NOTICE.rst"]
)
def test_notices_exclude_pyobjc_copying_test_and_debug_binary(
    license_name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = tmp_path / "installed"
    dist_info = installed / "pyobjc_core-12.1.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text("Name: pyobjc-core\nVersion: 12.1\n")
    license_path = f"pyobjc_core-12.1.dist-info/licenses/{license_name}"
    copying_path = "PyObjCTest/copying.cpython-312-darwin.so"
    debug_path = (
        copying_path + ".dSYM/Contents/Resources/DWARF/copying.cpython-312-darwin.so"
    )
    # A debug Mach-O header has no deployment command, matching the CI failure.
    debug_macho = struct.pack("<8I", 0xFEEDFACF, 0x01000007, 3, 10, 0, 0, 0, 0)
    entries = {
        license_path: b"License grant and credits\n",
        "PyObjCTest/test_copying.py": b"# Tests, not license material\n",
        copying_path: debug_macho,
        debug_path: debug_macho,
        "PyObjCTest/copying.dSYM/Contents/Resources/DWARF/copying": debug_macho,
    }
    for relative, content in entries.items():
        path = installed / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    (dist_info / "RECORD").write_text(
        "".join(f"{relative},,\n" for relative in entries)
    )
    distribution = metadata.PathDistribution(dist_info)

    def installed_distribution(_name: str) -> metadata.PathDistribution:
        return distribution

    monkeypatch.setattr(metadata, "distribution", installed_distribution)
    generated = tmp_path / "generated"
    monkeypatch.setattr(package_app, "GENERATED", generated)

    package_app.collect_notices()

    notices = generated / "licenses/pyobjc-core"
    assert {path.name for path in notices.iterdir()} == {license_path.replace("/", "_")}
    assert next(notices.iterdir()).read_bytes() == entries[license_path]
    inventory = json.loads((generated / "licenses/inventory.json").read_text())
    assert inventory[0]["license_files"] == [license_path.replace("/", "_")]


@pytest.mark.parametrize(
    "relative",
    [
        "linux-x86_64/_libwasmtime.so",
        "macos-x86_64/_libwasmtime.dylib",
        "win32-x86_64/_wasmtime.dll",
    ],
)
def test_spec_collects_wasmtime_at_its_runtime_relative_path(
    relative: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hooks = pytest.importorskip(
        "PyInstaller.utils.hooks", reason="Requires the packaging dependency group"
    )
    package = tmp_path / "wasmtime"
    package.mkdir()
    (package / "__init__.py").touch()
    library = package / relative
    library.parent.mkdir(parents=True)
    library.write_bytes(b"native library fixture")
    collect_dynamic_libs = hooks.collect_dynamic_libs

    def package_paths(_name: str) -> list[str]:
        return [str(package)]

    def is_package(_name: str) -> bool:
        return True

    def collect_libraries(name: str, **kwargs: Any) -> list[tuple[str, str]]:
        if name != "wasmtime":
            return []
        libraries: list[tuple[str, str]] = collect_dynamic_libs(name, **kwargs)
        return libraries

    def no_files(*args: object, **kwargs: object) -> list[tuple[str, str]]:
        return []

    def no_submodules(*args: object, **kwargs: object) -> list[str]:
        return []

    monkeypatch.setattr(hooks, "get_all_package_paths", package_paths)
    monkeypatch.setattr(hooks, "is_package", is_package)
    monkeypatch.setattr(hooks, "collect_dynamic_libs", collect_libraries)
    monkeypatch.setattr(hooks, "collect_data_files", no_files)
    monkeypatch.setattr(hooks, "collect_submodules", no_submodules)
    monkeypatch.setattr(hooks, "copy_metadata", no_files)

    class CollectionCompleteError(Exception):
        pass

    def inspect_analysis(*args: object, **kwargs: Any) -> None:
        expected = (str(library), str(Path("wasmtime") / Path(relative).parent))
        assert expected in kwargs["binaries"], "Wasmtime's runtime library is missing"
        raise CollectionCompleteError

    with pytest.raises(CollectionCompleteError):
        runpy.run_path(
            str(package_app.ROOT / "packaging/iOpenPod.spec"),
            init_globals={
                "SPECPATH": str(package_app.ROOT / "packaging"),
                "Analysis": inspect_analysis,
            },
        )
