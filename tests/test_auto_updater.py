from pathlib import Path

from GUI.auto_updater import _resolve_install_target


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
