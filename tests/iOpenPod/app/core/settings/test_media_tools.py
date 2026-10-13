"""Host tool choices persist, override discovery, and reach execution consumers."""

from pathlib import Path

import pytest

from iOpenPod.app.core.settings import media_tools as configured
from iOpenPod.app.core.settings.definitions import (
    FFMPEG_PATH,
    FPCALC_PATH,
    MEDIA_TOOL_PATHS,
)
from iOpenPod.app.core.settings.media_tools import ConfiguredMediaTools
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import (
    DeviceSettingsStore,
    GlobalSettingsStore,
    JsonSettingsStore,
)
from iOpenPod.app.host_media_fingerprint import FpcalcFingerprinter
from iOpenPod.app.media.inspection import MediaInspector
from iOpenPod.app.media.transcoding import MediaTranscoder
from iOpenPod.app.services import media_tools
from iOpenPod.app.synesthesia.audio import FFmpegDecoder
from storage import AtomicHostFile, HostPath, media_processing
from storage.host_tools import HostToolEnvironment
from storage.media_processing import ToolOutput


def test_paths_persist_independently_and_never_use_ipod_overrides(
    tmp_path: Path,
) -> None:
    file = AtomicHostFile(tmp_path / "settings-v2.json")
    settings = SettingsService(JsonSettingsStore(file), DeviceSettingsStore())
    for name, definition in MEDIA_TOOL_PATHS:
        settings.set_global(definition, str(tmp_path / "custom tools" / name))
    reloaded = SettingsService(JsonSettingsStore(file), DeviceSettingsStore())
    reloaded.load_device(
        "test",
        {
            definition.key: str(tmp_path / "device" / name)
            for name, definition in MEDIA_TOOL_PATHS
        },
    )
    tools = ConfiguredMediaTools(reloaded)
    for name, definition in MEDIA_TOOL_PATHS:
        assert tools.find(name) == HostPath(tmp_path / "custom tools" / name)
        assert reloaded.get(definition) == str(tmp_path / "custom tools" / name)
        with pytest.raises(ValueError, match="not device-overridable"):
            reloaded.set_device(definition, str(tmp_path / "device" / name))


@pytest.mark.parametrize("value", ["ffmpeg", "./ffmpeg", " ", "bad\x00path"])
def test_invalid_path_syntax_is_rejected(value: str) -> None:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    for _, definition in MEDIA_TOOL_PATHS:
        with pytest.raises(ValueError):
            settings.set_global(definition, value)


def test_override_precedence_live_changes_and_clear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    automatic = HostPath(tmp_path / "automatic" / "tool")

    def discover(_name: str) -> HostPath:
        return automatic

    monkeypatch.setattr(configured, "find_media_tool", discover)
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    tools = ConfiguredMediaTools(settings)
    assert tools.find("fpcalc") == automatic
    for name, definition in MEDIA_TOOL_PATHS:
        path = tmp_path / "custom tools" / name
        settings.set_global(definition, str(path))
        assert tools.find(name) == HostPath(path)
        settings.set_global(definition, "")
        assert tools.find(name) == automatic


@pytest.mark.parametrize("kind", ["missing", "directory", "not-executable"])
def test_unusable_override_is_reported_without_fallback_or_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    selected = tmp_path / kind
    if kind == "directory":
        selected.mkdir()
    elif kind == "not-executable":
        selected.write_text("not a program")
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    tools = ConfiguredMediaTools(settings)
    for _, definition in MEDIA_TOOL_PATHS:
        settings.set_global(definition, str(selected))

    def fail_discovery(_name: str) -> HostPath | None:
        pytest.fail("Override fell back to discovery")

    monkeypatch.setattr(configured, "find_media_tool", fail_discovery)
    monkeypatch.setattr(
        media_tools,
        "inspect_tool_environment",
        lambda: HostToolEnvironment("linux", "x86_64", confined=True),
    )
    setup = media_tools.inspect_media_tools(
        checkpoint=lambda: None, find_tool=tools.find
    )
    assert not setup.ready
    assert not setup.plan.commands
    assert all(tool.path == str(selected) and tool.problem for tool in setup.tools)


def test_configured_paths_reach_checks_encoders_and_sync_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    tools = ConfiguredMediaTools(settings)
    selected = {
        name: HostPath(tmp_path / "custom tools" / name) for name, _ in MEDIA_TOOL_PATHS
    }
    for name, definition in MEDIA_TOOL_PATHS:
        settings.set_global(definition, str(selected[name]))
    calls: list[tuple[HostPath, tuple[str, ...]]] = []

    def run(
        executable: HostPath, arguments: tuple[str, ...], **_kwargs: object
    ) -> ToolOutput:
        calls.append((executable, arguments))
        if arguments == ("-hide_banner", "-encoders"):
            return ToolOutput(b" A..... aac AAC\n", b"")
        return ToolOutput(f"{executable.path.name} version test".encode(), b"")

    monkeypatch.setattr(media_tools, "run_media_tool", run)
    monkeypatch.setattr(media_processing, "run_media_tool", run)
    monkeypatch.setattr(
        media_tools,
        "inspect_tool_environment",
        lambda: HostToolEnvironment("linux", "x86_64"),
    )
    status = media_tools.inspect_media_tools(
        checkpoint=lambda: None, find_tool=tools.find
    )
    assert status.ready
    assert status.tools[0].encoders == frozenset({"aac"})
    observed = MediaTranscoder(find_tool=tools.find).preflight(checkpoint=lambda: None)
    assert (observed.ffmpeg, observed.ffprobe, observed.fpcalc) == tuple(
        selected.values()
    )
    assert (selected["ffmpeg"], ("-hide_banner", "-encoders")) in calls
    assert (selected["fpcalc"], ("-version",)) in calls
    # Long-lived consumers see the current Host selection on their next lookup.
    # Exercise lookup directly without launching external media processes.
    inspector = MediaInspector(find_tool=tools.find)
    decoder = FFmpegDecoder(find_tool=tools.find)
    assert inspector._resolve_executable() == selected["ffprobe"]  # pyright: ignore[reportPrivateUsage]
    assert decoder._resolve_executable() == str(selected["ffmpeg"])  # pyright: ignore[reportPrivateUsage]
    settings.set_global(FFMPEG_PATH, str(tmp_path / "replacement"))
    assert decoder._resolve_executable() == str(tmp_path / "replacement")  # pyright: ignore[reportPrivateUsage]


def test_fpcalc_scan_keeps_its_path_but_next_scan_uses_updated_choice(
    tmp_path: Path,
) -> None:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    tools = ConfiguredMediaTools(settings)
    settings.set_global(FPCALC_PATH, str(tmp_path / "first"))
    fingerprinter = FpcalcFingerprinter(find_tool=tools.find)
    scan = fingerprinter.for_scan()
    # Observe the scan's lazy lookup cache without invoking fpcalc.
    assert scan._resolve_executable() == HostPath(tmp_path / "first")  # pyright: ignore[reportPrivateUsage]
    settings.set_global(FPCALC_PATH, str(tmp_path / "second"))
    assert scan._resolve_executable() == HostPath(tmp_path / "first")  # pyright: ignore[reportPrivateUsage]
    assert fingerprinter.for_scan()._resolve_executable() == HostPath(  # pyright: ignore[reportPrivateUsage]
        tmp_path / "second"
    )
