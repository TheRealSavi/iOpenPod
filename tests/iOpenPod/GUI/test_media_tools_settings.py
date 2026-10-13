"""Media Tools settings show observed tools and encoders, and only offer missing-tool setup."""

from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
)
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.core.settings.definitions import FPCALC_PATH, MEDIA_TOOL_PATHS
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.services.media_tools import (
    MediaToolInstallPlan,
    MediaToolSetup,
    MediaToolStatus,
)
from iOpenPod.GUI.pages.settings_page import SettingsPage
from iOpenPod.GUI.widgets.media_tools_settings import MediaToolsSettings


def test_path_edits_save_check_and_clear_each_tool(tmp_path: Path) -> None:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    view = MediaToolsSettings(settings=settings)
    refreshes = QSignalSpy(view.checkRequested)
    for index, (name, definition) in enumerate(MEDIA_TOOL_PATHS):
        edit = view.findChild(QLineEdit, f"mediaToolPath_{name}")
        clear = view.findChild(QPushButton, f"clearMediaTool_{name}")
        assert edit is not None and clear is not None
        path = str(tmp_path / "my tools" / name)
        edit.setText(path)
        edit.editingFinished.emit()
        assert settings.get_global(definition) == path
        assert refreshes.count() == index * 2 + 1
        edit.editingFinished.emit()
        assert refreshes.count() == index * 2 + 1
        clear.click()
        assert not settings.get_global(definition)
        assert not edit.text()
        assert refreshes.count() == index * 2 + 2


def test_browse_saves_selection_and_cancel_preserves_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    view = MediaToolsSettings(settings=settings)
    button = view.findChild(QPushButton, "browseMediaTool_fpcalc")
    assert button is not None
    path = str(tmp_path / "my tools" / "custom-fpcalc")

    def select_file(*_args: object) -> tuple[str, str]:
        return path, ""

    def cancel_selection(*_args: object) -> tuple[str, str]:
        return "", ""

    monkeypatch.setattr(QFileDialog, "getOpenFileName", select_file)
    button.click()
    assert settings.get_global(FPCALC_PATH) == path
    monkeypatch.setattr(QFileDialog, "getOpenFileName", cancel_selection)
    button.click()
    assert settings.get_global(FPCALC_PATH) == path


def test_invalid_relative_path_keeps_saved_choice_and_shows_error(
    tmp_path: Path,
) -> None:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    saved = str(tmp_path / "fpcalc")
    settings.set_global(FPCALC_PATH, saved)
    view = MediaToolsSettings(settings=settings)
    edit = view.findChild(QLineEdit, "mediaToolPath_fpcalc")
    error = view.findChild(QLabel, "mediaToolPathError_fpcalc")
    assert edit is not None and error is not None
    assert edit.text() == saved
    edit.setText("local/fpcalc")
    edit.editingFinished.emit()
    assert settings.get_global(FPCALC_PATH) == saved
    assert not error.isHidden()
    assert "absolute" in error.text()


def test_checks_and_installation_disable_path_controls() -> None:
    view = MediaToolsSettings(
        settings=SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    )
    view.set_status(_setup(), checking=False, busy=True, message="Installing")
    for name, _ in MEDIA_TOOL_PATHS:
        edit = view.findChild(QLineEdit, f"mediaToolPath_{name}")
        browse = view.findChild(QPushButton, f"browseMediaTool_{name}")
        clear = view.findChild(QPushButton, f"clearMediaTool_{name}")
        assert edit is not None and not edit.isEnabled()
        assert browse is not None and not browse.isEnabled()
        assert clear is not None and not clear.isEnabled()


def test_failed_save_can_retry_the_same_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = GlobalSettingsStore()
    settings = SettingsService(store, DeviceSettingsStore())
    view = MediaToolsSettings(settings=settings)
    edit = view.findChild(QLineEdit, "mediaToolPath_fpcalc")
    error = view.findChild(QLabel, "mediaToolPathError_fpcalc")
    assert edit is not None and error is not None
    refreshes = QSignalSpy(view.checkRequested)

    def fail() -> None:
        raise OSError("Cannot save settings")

    monkeypatch.setattr(store, "sync", fail)
    edit.setText(str(tmp_path / "fpcalc"))
    edit.editingFinished.emit()
    assert error.text() == "Cannot save settings" and not error.isHidden()
    assert refreshes.count() == 0
    monkeypatch.setattr(store, "sync", lambda: None)
    edit.editingFinished.emit()
    assert error.isHidden()
    assert refreshes.count() == 1


def _setup(
    missing: str = "",
    *,
    broken: bool = False,
    encoders: frozenset[str] | None = frozenset({"aac", "libmp3lame"}),
    versions: dict[str, str] | None = None,
) -> MediaToolSetup:
    versions = versions or {}
    return MediaToolSetup(
        tuple(
            MediaToolStatus(
                name,
                "" if name == missing else f"/tools/{name}",
                "Cannot run" if broken else "",
                encoders if name == "ffmpeg" else None,
                "",
                versions.get(name, ""),
            )
            for name in ("ffmpeg", "ffprobe", "fpcalc")
        ),
        MediaToolInstallPlan("Test channel", ""),
    )


@pytest.mark.parametrize("missing", ["", "ffmpeg", "ffprobe", "fpcalc"])
def test_setup_visibility_depends_on_missing_executables(missing: str) -> None:
    view = MediaToolsSettings()
    view.show()
    button = view.findChild(QPushButton, "setupMediaTools")
    assert button is not None and button.isHidden()
    view.set_status(_setup(missing), checking=False, busy=False, message="")
    assert button.isVisible() is bool(missing)
    for name in ("ffmpeg", "ffprobe", "fpcalc"):
        status = view.findChild(QLabel, f"mediaToolStatus_{name}")
        assert status is not None
        assert status.text() == ("Missing" if missing == name else "Installed")
    # Installation completion updates the same view and removes the setup button.
    view.set_status(_setup(), checking=False, busy=False, message="")
    assert button.isHidden()


@pytest.mark.parametrize(
    "encoders",
    [
        frozenset[str](),
        frozenset({"aac", "libmp3lame"}),
        frozenset({"aac", "aac_at", "libfdk_aac", "libmp3lame"}),
        None,
    ],
)
def test_ffmpeg_status_shows_each_encoder_without_install_prompt(
    encoders: frozenset[str] | None,
) -> None:
    view = MediaToolsSettings()
    view.set_status(_setup(encoders=encoders), checking=False, busy=False, message="")
    for name in ("aac", "aac_at", "libfdk_aac", "libmp3lame"):
        status = view.findChild(QLabel, f"mediaEncoderStatus_{name}")
        assert status is not None
        assert status.text() == (
            "Unknown"
            if encoders is None
            else "Available"
            if name in encoders
            else "Unavailable"
        )
    button = view.findChild(QPushButton, "setupMediaTools")
    assert button is not None and button.isHidden()
    assert any(
        label.text() == "LAME (libmp3lame)" for label in view.findChildren(QLabel)
    )


def test_broken_tools_and_failed_checks_do_not_offer_install() -> None:
    view = MediaToolsSettings()
    view.set_status(
        _setup(broken=True),
        checking=False,
        busy=False,
        message="Repair the installed tools",
    )
    button = view.findChild(QPushButton, "setupMediaTools")
    assert button is not None and button.isHidden()
    status = view.findChild(QLabel, "mediaToolStatus_ffmpeg")
    assert status is not None and status.text() == "Needs attention"
    view.set_status(None, checking=False, busy=False, message="Check failed")
    assert button.isHidden()
    summary = view.findChild(QLabel, "mediaToolsStatus")
    assert summary is not None and summary.text() == "Check failed"


def test_rechecking_hides_stale_install_action_and_encoder_results() -> None:
    view = MediaToolsSettings()
    view.set_status(_setup("fpcalc"), checking=True, busy=True, message="")
    button = view.findChild(QPushButton, "setupMediaTools")
    check = view.findChild(QPushButton, "refreshMediaTools")
    status = view.findChild(QLabel, "mediaEncoderStatus_aac")
    assert button is not None and button.isHidden()
    assert check is not None and not check.isEnabled()
    assert status is not None and status.text() == "Checking…"


def test_encoder_failure_details_and_paths_are_plain_text() -> None:
    view = MediaToolsSettings()
    setup = _setup(encoders=None)
    ffmpeg = replace(
        setup.tools[0],
        path="/tools/<b>ffmpeg</b>",
        encoder_problem="Encoder check timed out",
    )
    view.set_status(
        replace(setup, tools=(ffmpeg, *setup.tools[1:])),
        checking=False,
        busy=False,
        message="",
    )
    assert any(
        "Encoder check timed out" in label.text() and "<b>ffmpeg</b>" in label.text()
        for label in view.findChildren(QLabel)
    )


def test_installed_tool_versions_are_shown() -> None:
    view = MediaToolsSettings()
    view.set_status(
        _setup(versions={"ffmpeg": "7.1.1", "ffprobe": "7.1.1", "fpcalc": "1.6.0"}),
        checking=False,
        busy=False,
        message="",
    )
    for name, _version in (
        ("ffmpeg", "7.1.1"),
        ("ffprobe", "7.1.1"),
        ("fpcalc", "1.6.0"),
    ):
        status = view.findChild(QLabel, f"mediaToolStatus_{name}")
        assert status is not None and status.text() == "Installed"


def test_settings_has_separate_media_tools_tab_and_requests_refresh() -> None:
    context = build_context()
    page = SettingsPage(context.settings, context.theme_manager, context.i18n_manager)
    page.show()
    APPLICATION.processEvents()
    try:
        tabs = page.findChild(QTabWidget, "settingsTabs")
        assert tabs is not None
        index = next(i for i in range(tabs.count()) if tabs.tabText(i) == "Media Tools")
        refreshes = QSignalSpy(page.mediaToolsCheckRequested)
        tabs.setCurrentIndex(index)
        assert refreshes.count() == 1
        tools = page.findChild(QScrollArea, "mediaToolsSettingsScroll")
        transcoding = page.findChild(QScrollArea, "transcodingSettingsScroll")
        assert tools is not None and transcoding is not None
        assert tools.findChild(QPushButton, "setupMediaTools") is not None
        assert transcoding.findChild(QPushButton, "setupMediaTools") is None
        page.set_media_tools_status(
            _setup("fpcalc"), checking=False, busy=False, message=""
        )
        button = tools.findChild(QPushButton, "setupMediaTools")
        assert button is not None and button.isVisible()
        requested = QSignalSpy(page.mediaToolsRequested)
        button.click()
        assert requested.count() == 1
    finally:
        page.close()
        context.shutdown()
