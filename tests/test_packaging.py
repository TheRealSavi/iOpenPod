"""Installed-launch and build-resource contracts for desktop distribution."""

import hashlib
import importlib
import os
import platform
import shutil
import subprocess
import sys
import textwrap
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from PIL import Image
from scripts import check_windows_bundle, package_app

import iopenpod_launcher as entrypoint
from iOpenPod.app.core import runtime


def test_smoke_test_reports_missing_gui_startup_dependency(tmp_path: Path) -> None:
    report = tmp_path / "smoke.txt"
    script = textwrap.dedent("""\
        import importlib.abc
        import sys

        sys.path.insert(0, sys.argv[1])

        class MissingCredentials(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path, target=None):
                if fullname == "iOpenPod.app.scrobbling.credentials":
                    raise ModuleNotFoundError(f"No module named '{fullname}'")

        sys.meta_path.insert(0, MissingCredentials())
        import iopenpod_launcher
        raise SystemExit(iopenpod_launcher.main([
            "--smoke-test", "--smoke-test-report", sys.argv[2],
        ]))
        """)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            script,
            str(package_app.ROOT / "src"),
            str(report),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stderr
    assert "No module named 'iOpenPod.app.scrobbling.credentials'" in report.read_text(
        encoding="utf-8"
    )


def test_version_and_smoke_test_do_not_initialize_settings_or_devices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_initialization() -> None:
        pytest.fail("Informational commands must not initialize application state")

    monkeypatch.setattr(entrypoint, "initialize_application", unexpected_initialization)
    with pytest.raises(SystemExit) as result:
        entrypoint.main(["--version"])
    assert result.value.code == 0
    calls: list[bool] = []
    monkeypatch.setattr(entrypoint, "check_runtime", lambda: calls.append(True))
    assert entrypoint.main(["--smoke-test"]) == 0
    assert calls == [True]


def test_frozen_launch_preserves_user_path_even_with_old_private_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def load_playback_libraries(_root: Path) -> tuple[()]:
        return ()

    bundle = tmp_path / "bundle"
    module = bundle / "iOpenPod/app/core/runtime.py"
    module.parent.mkdir(parents=True)
    module.touch()
    tools = bundle / "media-tools"
    tools.mkdir()
    monkeypatch.setattr(runtime, "__file__", str(module))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setattr(
        runtime, "_load_windows_playback_libraries", load_playback_libraries
    )
    monkeypatch.setenv("PATH", "existing")
    monkeypatch.delenv("NUMBA_CACHE_LOCATOR_CLASSES", raising=False)
    monkeypatch.chdir(tmp_path)
    runtime.configure_frozen_runtime()
    assert os.environ["PATH"] == "existing"
    assert os.environ["NUMBA_CACHE_LOCATOR_CLASSES"] == "UserWideCacheLocator"


def test_unfrozen_launch_preserves_user_runtime_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setenv("PATH", "existing")
    monkeypatch.delenv("NUMBA_CACHE_LOCATOR_CLASSES", raising=False)
    runtime.configure_frozen_runtime()
    assert os.environ["PATH"] == "existing"
    assert "NUMBA_CACHE_LOCATOR_CLASSES" not in os.environ


def test_legacy_runtime_configuration_name_delegates_to_current_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep an already-installed launcher from failing during an environment refresh."""
    calls: list[bool] = []
    monkeypatch.setattr(
        runtime,
        "configure_frozen_runtime",
        lambda: calls.append(True),
    )

    runtime.configure_bundled_tools()

    assert calls == [True]


def test_original_icon_is_retained_and_store_assets_have_required_sizes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = package_app.ROOT / "src/iOpenPod/assets/icons/icon-256.png"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == (
        "3cdc1d8d98c707209e415e4824793f71ed1a1c53c541161abee3def3f63a6dbe"
    )
    monkeypatch.setattr(package_app, "GENERATED", tmp_path)
    package_app.generate_assets()
    for name, size in (
        ("StoreLogo", 50),
        ("Square44x44Logo", 44),
        ("Square150x150Logo", 150),
    ):
        with Image.open(tmp_path / "Assets" / f"{name}.png") as image:
            assert image.size == (size, size)
    with Image.open(tmp_path / "iOpenPod.icns") as image:
        assert image.size == (1024, 1024)


def test_freeze_cli_needs_no_media_tools_or_special_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import package_updates

    commands: list[list[str]] = []

    def build(
        command: list[str], *, cwd: Path, env: dict[str, str], check: bool
    ) -> subprocess.CompletedProcess[bytes]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(package_app, "GENERATED", tmp_path)
    monkeypatch.setattr(subprocess, "run", build)
    embedded: list[Path] = []

    def embed_sparkle(root: Path, _generated: Path, _minimum: str) -> None:
        embedded.append(root)

    monkeypatch.setattr(package_updates, "embed_sparkle", embed_sparkle)
    monkeypatch.setattr(sys, "argv", ["package_app.py", "freeze"])
    monkeypatch.setenv("PATH", "")
    package_app.main()
    assert len(commands) == (1 if sys.platform == "darwin" else 2)
    assert bool(embedded) == (sys.platform == "darwin")
    if sys.platform != "darwin":
        assert commands[0][-1].endswith("update-helper.spec")
    assert commands[-1][-1].endswith("iOpenPod.spec")
    assert commands[0][:3] == [sys.executable, "-m", "PyInstaller"]
    assert (tmp_path / "licenses/ACKNOWLEDGEMENTS.md").is_file()


@pytest.mark.parametrize(
    "name,message",
    [
        ("ffmpeg.exe", "User-installed media tool"),
        ("tools/FFprobe.EXE", "User-installed media tool"),
        ("fpcalc.exe", "User-installed media tool"),
        ("sklearn/datasets/data/sample.csv", "sample datasets"),
        ("sklearn/cluster/tests/test_example.py", "test fixtures"),
        ("_tcl_data/init.tcl", "Tcl/Tk"),
        ("_tkinter.pyd", "Tcl/Tk"),
        ("media-tools/obsolete.txt", "Obsolete bundled"),
        ("PySide6/plugins/imageformats/qpdf.dll", "Unused Qt component"),
        ("PySide6/Qt6VirtualKeyboard.dll", "Unused Qt component"),
    ],
)
def test_windows_embedded_payload_rejects_unwanted_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, message: str
) -> None:
    writers = pytest.importorskip("PyInstaller.archive.writers")

    def read_manifest(_path: str) -> bytes:
        return (
            package_app.ROOT / "packaging/windows/iOpenPod.manifest.xml"
        ).read_bytes()

    def resource_reader(name: str) -> ModuleType | SimpleNamespace:
        if name == "PyInstaller.utils.win32.winmanifest":
            return SimpleNamespace(read_manifest_from_executable=read_manifest)
        return importlib.import_module(name)

    monkeypatch.setattr(check_windows_bundle, "import_module", resource_reader)
    monkeypatch.setattr(sys, "platform", "win32")
    executable = tmp_path / "iOpenPod.exe"
    source = tmp_path / "payload"
    source.write_bytes(b"embedded payload")
    entries = [
        ("python312.dll", str(source), True, "b"),
        ("PySide6/avcodec-61.dll", str(source), True, "b"),
    ]
    # Qt's FFmpeg playback libraries are allowed; user-installed executables are not.
    writers.CArchiveWriter(str(executable), entries, "python312.dll")
    check_windows_bundle.check_windows_bundle(executable)
    writers.CArchiveWriter(
        str(executable), [*entries, (name, str(source), True, "x")], "python312.dll"
    )
    with pytest.raises(ValueError, match=message):
        check_windows_bundle.check_windows_bundle(executable)
    writers.CArchiveWriter(str(executable), [], "python312.dll")
    with pytest.raises(ValueError, match="does not embed the Python runtime"):
        check_windows_bundle.check_windows_bundle(executable)


def test_native_notices_keep_license_grant_and_credits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(package_app, "GENERATED", tmp_path)
    package_app.collect_notices()
    notices = tmp_path / "licenses"
    for relative in (
        "LICENSE",
        "COPYING.md",
        "ACKNOWLEDGEMENTS.md",
    ):
        assert (notices / relative).read_bytes() == (
            package_app.ROOT / relative
        ).read_bytes()
    assert (notices / "calcHashAB.NOTICE").read_bytes() == (
        package_app.ROOT / "src/iPodDB/iTunesDB/writer/calcHashAB.NOTICE"
    ).read_bytes()
    assert (notices / "upstream/sources.json").read_bytes() == (
        package_app.ROOT / "packaging/third-party/sources.json"
    ).read_bytes()
    assert list((notices / "upstream/notices").glob("*-NOTICES.txt"))
    (notices / "obsolete.txt").write_text("stale material")
    package_app.collect_notices()
    assert not (notices / "obsolete.txt").exists()


@pytest.mark.parametrize(
    "arguments,expected",
    [
        (
            [],
            (
                "TheRealSavi.iOpenPod",
                "CN=FB5CD908-9397-4B6A-B014-49E83AB6CE1A",
                "TheRealSavi",
            ),
        ),
        (
            [
                "--identity",
                "Example.Test",
                "--publisher",
                "CN=Example & Co",
                "--publisher-display-name",
                "Example & Co",
            ],
            ("Example.Test", "CN=Example & Co", "Example & Co"),
        ),
    ],
)
def test_msix_cli_stages_saved_identity_and_explicit_overrides(
    arguments: list[str],
    expected: tuple[str, str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for relative in (
        "pyproject.toml",
        "packaging/windows/store-identity.toml",
        "packaging/windows/AppxManifest.xml.in",
        "src/iOpenPod/assets/icons/icon-256.png",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(package_app.ROOT / relative, destination)
    executable = tmp_path / "dist/iOpenPod.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"test bundle payload")
    stale = tmp_path / "dist/iOpenPod/_internal/obsolete.dll"
    stale.parent.mkdir(parents=True)
    stale.touch()
    monkeypatch.setattr(package_app, "ROOT", tmp_path)
    monkeypatch.setattr(package_app, "GENERATED", tmp_path / "build/packaging")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(sys, "argv", ["package_app.py", "msix-stage", *arguments])

    package_app.main()

    staged = tmp_path / "build/msix"
    manifest = ET.parse(staged / "AppxManifest.xml").getroot()
    namespace = {"m": "http://schemas.microsoft.com/appx/manifest/foundation/windows10"}
    identity = manifest.find("m:Identity", namespace)
    assert identity is not None
    assert identity.attrib == {
        "Name": expected[0],
        "Publisher": expected[1],
        "Version": package_app.project_version() + ".0",
        "ProcessorArchitecture": "x64",
    }
    assert (
        manifest.findtext("m:Properties/m:PublisherDisplayName", namespaces=namespace)
        == expected[2]
    )
    assert (staged / "app/iOpenPod.exe").read_bytes() == executable.read_bytes()
    assert list((staged / "app").iterdir()) == [staged / "app/iOpenPod.exe"]
    assert (staged / "Assets/Square150x150Logo.png").is_file()
    with pytest.raises(FileExistsError):
        package_app.main()


def test_windows_archive_contains_only_the_standalone_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutil.copy2(package_app.ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    executable = tmp_path / "dist/iOpenPod.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"standalone executable with embedded dependencies")
    stale = tmp_path / "dist/iOpenPod/_internal/obsolete.dll"
    stale.parent.mkdir(parents=True)
    stale.touch()
    monkeypatch.setattr(package_app, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "platform", "win32")

    archive = package_app.archive()

    with zipfile.ZipFile(archive) as zipped:
        assert zipped.namelist() == ["iOpenPod.exe"]
        assert zipped.read("iOpenPod.exe") == executable.read_bytes()
    assert archive.with_name(archive.name + ".sha256").read_text() == (
        f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n"
    )


def test_macos_archive_adds_a_drag_to_applications_disk_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutil.copy2(package_app.ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    artwork = tmp_path / "packaging/macos"
    artwork.mkdir(parents=True)
    for name in ("dmg-background.png", "dmg-layout.applescript"):
        shutil.copy2(package_app.ROOT / "packaging/macos" / name, artwork / name)
    app = tmp_path / "dist/iOpenPod.app"
    executable = app / "Contents/MacOS/iOpenPod"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"signed app executable")
    monkeypatch.setattr(package_app, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    calls: list[list[str]] = []

    def fake_symlink(path: Path, target: str, *, target_is_directory: bool) -> None:
        assert target_is_directory and target == "/Applications"
        path.write_text(target)

    def fake_run(command: list[str], *, check: bool) -> None:
        assert check
        calls.append(command)
        if command[:2] == ["ditto", "-c"]:
            Path(command[-1]).write_bytes(b"sparkle update archive")
        elif command[0] == "ditto":
            shutil.copytree(command[1], command[2])
        elif command[:2] == ["hdiutil", "create"]:
            staging = Path(command[command.index("-srcfolder") + 1])
            assert (staging / "iOpenPod.app/Contents/MacOS/iOpenPod").read_bytes() == (
                executable.read_bytes()
            )
            assert (staging / "Applications").read_text() == "/Applications"
            assert (staging / ".background/background.png").read_bytes() == (
                artwork / "dmg-background.png"
            ).read_bytes()
            assert command[command.index("-format") + 1] == "UDRW"
            Path(command[-1]).write_bytes(b"disk image")
        elif command[:2] == ["hdiutil", "attach"]:
            assert command[command.index("-readwrite") + 1] == "-noverify"
        elif command[:2] == ["hdiutil", "resize"]:
            assert command[command.index("-size") + 1] == "21m"
        elif command[0] == "osascript":
            assert command[1] == str(artwork / "dmg-layout.applescript")
            assert command[2] == f"iOpenPod {package_app.project_version()}"
            Path(command[3], ".DS_Store").write_bytes(b"Finder layout")
        elif command[:2] == ["hdiutil", "detach"]:
            assert Path(command[2], ".DS_Store").read_bytes() == b"Finder layout"
        elif command[:2] == ["hdiutil", "convert"]:
            assert command[command.index("-format") + 1] == "UDZO"
            Path(command[-1]).write_bytes(b"compressed disk image")
        else:
            assert command[:2] == ["hdiutil", "verify"]
            assert Path(command[-1]).is_file()

    monkeypatch.setattr(Path, "symlink_to", fake_symlink)
    monkeypatch.setattr(subprocess, "run", fake_run)
    archive = package_app.archive()
    dmg = archive.with_suffix(".dmg")

    assert archive.is_file() and dmg.is_file()
    assert [command[:2] for command in calls] == [
        ["ditto", "-c"],
        ["ditto", str(app)],
        ["hdiutil", "create"],
        ["hdiutil", "resize"],
        ["hdiutil", "attach"],
        ["osascript", str(artwork / "dmg-layout.applescript")],
        ["hdiutil", "detach"],
        ["hdiutil", "convert"],
        ["hdiutil", "verify"],
    ]
    assert dmg.with_name(dmg.name + ".sha256").read_text() == (
        f"{hashlib.sha256(dmg.read_bytes()).hexdigest()}  {dmg.name}\n"
    )


@pytest.mark.parametrize("status,expected_calls", [(15700, 1), (122, 0), (5, 0)])
def test_windows_store_identity_is_not_replaced(
    status: int,
    expected_calls: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ctypes

    from iOpenPod.app import app

    calls: list[str] = []

    def set_identity(value: str) -> int:
        calls.append(value)
        return 0

    def get_package_name_status(_length: object, _buffer: object) -> int:
        return status

    fake = SimpleNamespace(
        kernel32=SimpleNamespace(GetCurrentPackageFullName=get_package_name_status),
        shell32=SimpleNamespace(SetCurrentProcessExplicitAppUserModelID=set_identity),
    )
    monkeypatch.setattr(ctypes, "windll", fake, raising=False)
    monkeypatch.setattr(app, "sys", SimpleNamespace(platform="win32"))
    app._set_windows_app_user_model_id()  # pyright: ignore[reportPrivateUsage]
    assert len(calls) == expected_calls


def test_smoke_report_requires_smoke_mode() -> None:
    with pytest.raises(SystemExit) as result:
        entrypoint.main(["--smoke-test-report", "unused.txt"])
    assert result.value.code == 2
