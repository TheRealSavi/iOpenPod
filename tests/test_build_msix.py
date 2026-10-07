"""Check the local MSIX build's package-specific validation."""

from __future__ import annotations

import platform
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from scripts import build_msix, package_app

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


def make_package(path: Path, executable: bytes, *, version: str) -> None:
    name, publisher, display_name = package_app.windows_store_identity()
    manifest = (
        '<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">'
        f'<Identity Name="{name}" Publisher="{publisher}" Version="{version}.0" '
        'ProcessorArchitecture="x64" />'
        f"<Properties><PublisherDisplayName>{display_name}</PublisherDisplayName></Properties>"
        '<Applications><Application Executable="app\\iOpenPod.exe" /></Applications>'
        "</Package>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("AppxManifest.xml", manifest)
        archive.writestr("app/iOpenPod.exe", executable)
        archive.writestr("Assets/StoreLogo.png", b"tile")
        archive.writestr("Assets/Square44x44Logo.png", b"tile")
        archive.writestr("Assets/Square150x150Logo.png", b"tile")
        archive.writestr("AppxBlockMap.xml", b"block map")


def test_check_msix_checks_packaged_executable_and_smoke_report(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    version = package_app.project_version()
    executable = tmp_path / "bundle.exe"
    executable.write_bytes(b"frozen app")
    package = tmp_path / "candidate.msix"
    make_package(package, executable.read_bytes(), version=version)
    checked: list[Path] = []

    def check_embedded(path: Path, actual_version: str) -> None:
        assert actual_version == version
        assert path.read_bytes() == executable.read_bytes()
        checked.append(path)

    def run(command: list[str], *, cwd: str | Path, check: bool, timeout: int) -> None:
        assert command[0] == str(checked[0])
        assert Path(cwd) == checked[0].parent
        assert check and timeout == 180
        Path(command[3]).write_text("iOpenPod packaged runtime check passed.\n")

    monkeypatch.setattr(build_msix, "check_embedded_build", check_embedded)
    monkeypatch.setattr(subprocess, "run", run)
    build_msix.check_msix(package, executable, version)
    assert len(checked) == 1


def test_check_msix_rejects_package_with_different_executable(tmp_path: Path) -> None:
    version = package_app.project_version()
    executable = tmp_path / "bundle.exe"
    executable.write_bytes(b"checked app")
    package = tmp_path / "candidate.msix"
    make_package(package, b"different app", version=version)
    with pytest.raises(ValueError, match="differs from the checked Windows bundle"):
        build_msix.check_msix(package, executable, version)


def test_check_msix_rejects_wrong_version(tmp_path: Path) -> None:
    executable = tmp_path / "bundle.exe"
    executable.write_bytes(b"checked app")
    package = tmp_path / "candidate.msix"
    make_package(package, executable.read_bytes(), version="1.0.0")
    with pytest.raises(ValueError, match="identity, version, or architecture"):
        build_msix.check_msix(package, executable, package_app.project_version())


def test_embedded_build_includes_native_audio_build_record(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    notice = tmp_path / "build/packaging/licenses/LICENSE"
    notice.parent.mkdir(parents=True)
    notice.write_bytes(b"license")
    record = tmp_path / "build/native-libs/sndfile/build-record.json"
    record.parent.mkdir(parents=True)
    record.write_bytes(b"build record")
    files = {
        "licenses\\LICENSE": b"license",
        "licenses\\libsndfile-build-record.json": b"build record",
        "updates\\installation.json": b'{"version":"2.0.7","target":"windows-x86_64"}',
    }

    class Reader:
        toc = files

        def extract(self, name: str) -> bytes:
            return files[name]

    def check_bundle(executable: Path) -> None:
        assert executable.name == "iOpenPod.exe"

    def read_archive(filename: str) -> Reader:
        assert filename.endswith("iOpenPod.exe")
        return Reader()

    def load_reader_module(name: str) -> SimpleNamespace:
        assert name == "PyInstaller.archive.readers"
        return SimpleNamespace(CArchiveReader=read_archive)

    monkeypatch.setattr(build_msix, "ROOT", tmp_path)
    monkeypatch.setattr(build_msix, "check_windows_bundle", check_bundle)
    monkeypatch.setattr(build_msix, "import_module", load_reader_module)
    build_msix.check_embedded_build(tmp_path / "iOpenPod.exe", "2.0.7")


def test_build_msix_preserves_existing_output(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    output = tmp_path / "candidate.msix"
    output.write_bytes(b"existing candidate")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(platform, "machine", lambda: "AMD64")
    with pytest.raises(FileExistsError, match="Refusing to replace"):
        build_msix.build_msix(tmp_path / "makeappx.exe", output)
    assert output.read_bytes() == b"existing candidate"
