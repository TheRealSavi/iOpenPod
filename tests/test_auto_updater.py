from pathlib import Path

from iopenpod.gui.auto_updater import (
    InstallMethod,
    UpdateResult,
    _resolve_install_target,
    build_update_guidance,
    detect_install_method,
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
