import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from iopenpod.gui.auto_updater import (
    InstallMethod,
    UpdateResult,
    _resolve_install_target,
    _staging_root_for,
    _validate_staged_payload,
    _write_unix_bootstrap,
    _write_windows_bootstrap,
    build_update_guidance,
    detect_install_method,
    stage_update,
)


def test_macos_bundle_update_target_is_app_bundle_not_enclosing_folder() -> None:
    executable = Path("/Applications/essentials/iOpenPod.app/Contents/MacOS/iOpenPod")

    app_dir, exe_name = _resolve_install_target(executable, "darwin")

    assert app_dir == Path("/Applications/essentials/iOpenPod.app")
    assert exe_name == "Contents/MacOS/iOpenPod"


def test_non_bundle_update_target_is_executable_directory() -> None:
    executable = Path("/opt/iOpenPod/iOpenPod")

    app_dir, exe_name = _resolve_install_target(executable, "linux")

    assert app_dir == Path("/opt/iOpenPod")
    assert exe_name == "iOpenPod"


def test_detect_install_method_recognizes_uv_tool() -> None:
    method = detect_install_method(
        frozen=False,
        executable=Path("/home/user/.local/share/uv/tools/iopenpod/bin/python"),
        prefix=Path("/home/user/.local/share/uv/tools/iopenpod"),
        base_prefix=Path("/usr"),
        cwd=Path("/tmp"),
        environ={},
    )

    assert method.kind == "uv_tool"


def test_detect_install_method_recognizes_pipx() -> None:
    method = detect_install_method(
        frozen=False,
        executable=Path("/home/user/.local/share/pipx/venvs/iopenpod/bin/python"),
        prefix=Path("/home/user/.local/share/pipx/venvs/iopenpod"),
        base_prefix=Path("/usr"),
        cwd=Path("/tmp"),
        environ={},
    )

    assert method.kind == "pipx"


def test_detect_install_method_recognizes_source_checkout(tmp_path) -> None:
    package_main = tmp_path / "src" / "iopenpod" / "__main__.py"
    package_main.parent.mkdir(parents=True)
    package_main.write_text("print('iOpenPod')\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "iopenpod"\n',
        encoding="utf-8",
    )

    method = detect_install_method(
        frozen=False,
        executable=tmp_path / ".venv/bin/python",
        prefix=tmp_path / ".venv",
        base_prefix=Path("/usr"),
        cwd=tmp_path,
        environ={},
    )

    assert method.kind == "source_checkout"


def test_build_update_guidance_for_uv_tool_uses_uv_upgrade_command() -> None:
    result = UpdateResult(
        update_available=True,
        current_version="1.0.64",
        latest_version="1.0.65",
    )

    guidance = build_update_guidance(
        result,
        method=InstallMethod("uv_tool", "uv tool install", ""),
        platform="linux",
    )

    assert guidance.can_auto_install is False
    assert "uv tool upgrade iopenpod" in guidance.commands


def test_build_update_guidance_for_frozen_build_allows_auto_install_when_asset_exists() -> None:
    result = UpdateResult(
        update_available=True,
        current_version="1.0.64",
        latest_version="1.0.65",
        download_url="https://example.test/iOpenPod-macOS.zip",
    )

    guidance = build_update_guidance(
        result,
        method=InstallMethod("native_macos_app", "macOS app", "Native app"),
        platform="darwin",
    )

    assert guidance.can_auto_install is True
    assert guidance.release_asset_hint == "iOpenPod-macOS.zip"


def test_build_update_guidance_for_appimage_stays_manual() -> None:
    result = UpdateResult(
        update_available=True,
        current_version="1.0.64",
        latest_version="1.0.65",
        download_url="https://example.test/iOpenPod-Linux.tar.gz",
    )

    guidance = build_update_guidance(
        result,
        method=InstallMethod("native_appimage", "Linux AppImage", ""),
        platform="linux",
    )

    assert guidance.can_auto_install is False
    assert guidance.release_asset_hint == "iOpenPod-Linux-x86_64.AppImage"
    assert "chmod +x iOpenPod-Linux-x86_64.AppImage" in guidance.commands


def test_windows_bootstrap_deletes_only_runtime_payload() -> None:
    staging = Path(tempfile.mkdtemp(prefix="iopenpod-staging-"))
    script: Path | None = None
    try:
        script = _write_windows_bootstrap(
            12345,
            Path("C:/Users/example/Apps/iOpenPod"),
            staging,
            "iOpenPod.exe",
        )
        content = script.read_text(encoding="utf-8")

        assert "robocopy \"%STAGED_DIR%\" \"%APP_DIR%\" /E" in content
        assert 'robocopy "%STAGED_DIR%" "%APP_DIR%" /MIR' not in content
        assert 'del /f /q "%APP_EXE%"' in content
        assert 'rmdir /s /q "%APP_INTERNAL%"' in content
        assert 'rmdir /s /q "%APP_DIR%"' not in content
        assert ".bak" not in content
    finally:
        if script is not None:
            script.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)


def test_unix_bootstrap_overlays_without_removing_install_directory() -> None:
    staging = Path(tempfile.mkdtemp(prefix="iopenpod-staging-"))
    script: Path | None = None
    try:
        script = _write_unix_bootstrap(
            12345,
            Path("/opt/iOpenPod"),
            staging,
            "iOpenPod",
            platform="linux",
        )
        content = script.read_text(encoding="utf-8")

        assert '/bin/cp -a "$STAGED_DIR/." "$APP_DIR/"' in content
        assert 'rm -rf "$APP_DIR"' not in content
        assert ".bak" not in content
        assert "mv \"$APP_DIR\"" not in content
    finally:
        if script is not None:
            script.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)


def test_macos_bootstrap_overlays_bundle_without_backup_swap() -> None:
    staging = Path(tempfile.mkdtemp(prefix="iopenpod-staging-"))
    script: Path | None = None
    ops_script: Path | None = None
    try:
        script = _write_unix_bootstrap(
            12345,
            Path("/Applications/iOpenPod.app"),
            staging,
            "Contents/MacOS/iOpenPod",
            platform="darwin",
        )
        content = script.read_text(encoding="utf-8")
        match = re.search(r"if /bin/sh (?P<path>\S+); then", content)
        assert match is not None
        ops_script = Path(match.group("path"))
        ops_content = ops_script.read_text(encoding="utf-8")

        assert '/usr/bin/ditto "$STAGED_DIR" "$APP_DIR"' in ops_content
        assert ".bak" not in ops_content
        assert "mv \"$APP_DIR\"" not in ops_content
        assert 'rm -rf "$APP_DIR"' not in ops_content
    finally:
        if script is not None:
            script.unlink(missing_ok=True)
        if ops_script is not None:
            ops_script.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)


def test_staging_root_must_be_updater_owned_temp_directory(tmp_path: Path) -> None:
    arbitrary_dir = tmp_path / "not-iopenpod-staging"
    arbitrary_dir.mkdir()

    try:
        _staging_root_for(arbitrary_dir)
    except ValueError as exc:
        assert "updater-owned" in str(exc)
    else:
        raise AssertionError("arbitrary directory was accepted as update staging")


def test_stage_update_rejects_unexpected_windows_top_level_file(tmp_path: Path) -> None:
    archive = tmp_path / "iOpenPod-Windows.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("iOpenPod.exe", "binary")
        zf.writestr("_internal/runtime.dll", "runtime")
        zf.writestr("notes-from-user.txt", "must not be copied")

    assert stage_update(archive, platform="win32") is None


def test_validate_staged_payload_accepts_only_expected_linux_layout(tmp_path: Path) -> None:
    staged = tmp_path / "iOpenPod"
    staged.mkdir()
    executable = staged / "iOpenPod"
    executable.write_text("binary", encoding="utf-8")
    (staged / "_internal").mkdir()

    _validate_staged_payload(staged, "linux")
