"""Platform channel selection never installs packages during inspection."""

from dataclasses import replace

import pytest

from iOpenPod.app.services import media_tools
from iOpenPod.app.services.media_tools import (
    TOOL_NAMES,
    MediaToolStatus,
    inspect_media_tools,
    plan_media_tool_install,
)
from storage import HostPath
from storage.host_tools import HostToolEnvironment
from storage.media_processing import MediaToolError, ToolOutput

MISSING = tuple(MediaToolStatus(name) for name in TOOL_NAMES)


def test_windows_uses_exact_packages_and_keeps_hash_verification() -> None:
    host = HostToolEnvironment(
        "win32", "amd64", managers=(("winget", "C:/winget.exe"),)
    )
    plan = plan_media_tool_install(host, MISSING)
    assert len(plan.commands) == 2
    for command, package in zip(
        plan.commands, ("Gyan.FFmpeg", "AcoustID.Chromaprint"), strict=True
    ):
        assert command.program == "C:/winget.exe"
        assert command.arguments[:6] == (
            "install",
            "--id",
            package,
            "--exact",
            "--source",
            "winget",
        )
        assert "--ignore-security-hash" not in command.arguments
        assert command.arguments[command.arguments.index("--scope") + 1] == "user"


@pytest.mark.parametrize(
    "missing", [("ffprobe",), ("ffmpeg",), ("ffmpeg", "ffprobe"), ("fpcalc",)]
)
def test_only_missing_tool_packages_are_requested(missing: tuple[str, ...]) -> None:
    tools = tuple(
        MediaToolStatus(name, "" if name in missing else f"C:/{name}.exe")
        for name in TOOL_NAMES
    )
    host = HostToolEnvironment(
        "win32", "amd64", managers=(("winget", "C:/winget.exe"),)
    )
    commands = plan_media_tool_install(host, tools).commands
    assert len(commands) == 1
    assert commands[0].arguments[2] == (
        "AcoustID.Chromaprint" if missing == ("fpcalc",) else "Gyan.FFmpeg"
    )


@pytest.mark.parametrize(
    ("architecture", "prefix", "flag"),
    [
        ("arm64", "/opt/homebrew", "-arm64"),
        ("x86_64", "/usr/local", "-x86_64"),
    ],
)
def test_macos_uses_architecture_specific_homebrew(
    architecture: str, prefix: str, flag: str
) -> None:
    host = HostToolEnvironment(
        "darwin", architecture, managers=(("brew", prefix + "/bin/brew"),)
    )
    (command,) = plan_media_tool_install(host, MISSING).commands
    assert command.program == "/usr/bin/arch"
    assert command.arguments == (
        flag,
        prefix + "/bin/brew",
        "install",
        "ffmpeg",
        "chromaprint",
    )


@pytest.mark.parametrize(
    ("ids", "manager", "packages"),
    [
        (
            frozenset({"ubuntu", "debian"}),
            "apt-get",
            ("ffmpeg", "libchromaprint-tools"),
        ),
        (frozenset({"fedora"}), "dnf", ("ffmpeg-free", "chromaprint-tools")),
        (frozenset({"manjaro", "arch"}), "pacman", ("ffmpeg", "chromaprint")),
        (
            frozenset({"opensuse-tumbleweed"}),
            "zypper",
            ("ffmpeg", "chromaprint-fpcalc"),
        ),
    ],
)
def test_linux_installs_native_packages_through_polkit(
    ids: frozenset[str], manager: str, packages: tuple[str, ...]
) -> None:
    host = HostToolEnvironment(
        "linux",
        "aarch64",
        ids,
        ((manager, "/usr/bin/" + manager), ("pkexec", "/usr/bin/pkexec")),
    )
    (command,) = plan_media_tool_install(host, MISSING).commands
    assert command.program == "/usr/bin/pkexec"
    assert command.arguments[0] == "/usr/bin/" + manager
    assert command.arguments[-2:] == packages
    assert "-Sy" not in command.arguments
    assert "--allowerasing" not in command.arguments
    assert "--allow-unauthenticated" not in command.arguments
    (root_command,) = plan_media_tool_install(
        replace(host, administrator=True), MISSING
    ).commands
    assert root_command.program == "/usr/bin/" + manager
    assert root_command.arguments == command.arguments[1:]


@pytest.mark.parametrize(
    "host",
    [
        HostToolEnvironment("win32", "amd64"),
        HostToolEnvironment("darwin", "arm64"),
        HostToolEnvironment("darwin", "x86_64"),
        HostToolEnvironment(
            "linux", "x86_64", frozenset({"debian"}), (("apt-get", "/usr/bin/apt-get"),)
        ),
        HostToolEnvironment("linux", "x86_64", frozenset({"unknown"})),
        HostToolEnvironment("linux", "x86_64", confined=True),
    ],
)
def test_unavailable_channels_explain_recovery(host: HostToolEnvironment) -> None:
    plan = plan_media_tool_install(host, MISSING)
    assert not plan.commands
    assert plan.explanation and plan.help_url.startswith("https://")


def test_broken_existing_tools_are_not_overwritten() -> None:
    tools = tuple(
        MediaToolStatus(name, f"/bin/{name}", "Broken") for name in TOOL_NAMES
    )
    plan = plan_media_tool_install(HostToolEnvironment("darwin", "arm64"), tools)
    assert not plan.commands
    assert "Repair" in plan.explanation


def test_inspection_verifies_execution_and_reports_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def find_tool(name: str) -> HostPath | None:
        return None if name == "fpcalc" else HostPath(f"C:/{name}.exe")

    def read_encoders(_executable: HostPath, **_kwargs: object) -> frozenset[str]:
        return frozenset({"aac"})

    monkeypatch.setattr(media_tools, "find_media_tool", find_tool)
    monkeypatch.setattr(
        media_tools,
        "inspect_tool_environment",
        lambda: HostToolEnvironment("win32", "amd64"),
    )

    def run(
        executable: HostPath, arguments: tuple[str, ...], **_kwargs: object
    ) -> ToolOutput:
        assert arguments == ("-version",)
        if "ffprobe" in str(executable):
            raise MediaToolError("media.tool_timeout", "Timed out")
        return ToolOutput(b"ffmpeg version test", b"")

    monkeypatch.setattr(media_tools, "run_media_tool", run)
    monkeypatch.setattr(media_tools, "read_media_encoders", read_encoders)
    setup = inspect_media_tools(checkpoint=lambda: None)
    assert setup.tools[0].usable
    assert setup.tools[0].version == "test"
    assert setup.tools[0].encoders == frozenset({"aac"})
    assert setup.tools[1].problem == "Timed out"
    assert not setup.tools[2].path
    assert not setup.ready


def test_inspection_rejects_an_unrelated_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def find_tool(name: str) -> HostPath:
        return HostPath(f"C:/{name}.exe")

    def run(
        _executable: HostPath, _arguments: tuple[str, ...], **_kwargs: object
    ) -> ToolOutput:
        return ToolOutput(b"another program", b"")

    monkeypatch.setattr(media_tools, "find_media_tool", find_tool)
    monkeypatch.setattr(
        media_tools,
        "inspect_tool_environment",
        lambda: HostToolEnvironment("win32", "amd64"),
    )
    monkeypatch.setattr(media_tools, "run_media_tool", run)
    assert all(
        tool.problem for tool in inspect_media_tools(checkpoint=lambda: None).tools
    )


@pytest.mark.parametrize(
    "listing",
    [
        b"Encoders:\n A..... = Audio\n A..... aac AAC\n A....D aac_at AudioToolbox AAC\n A....D libfdk_aac FDK AAC\n A....D libmp3lame MP3\n",
        b"Encoders:\n A..... = Audio\n A..... aac AAC\n A....D libshine MP3 (not libmp3lame)\n",
        b"Encoders:\n A..... = Audio\n",
    ],
)
def test_inspection_reads_encoders_from_the_selected_ffmpeg(
    monkeypatch: pytest.MonkeyPatch, listing: bytes
) -> None:
    from storage import media_processing

    calls: list[tuple[str, tuple[str, ...]]] = []

    def find_tool(name: str) -> HostPath | None:
        return HostPath("C:/tools/ffmpeg.exe") if name == "ffmpeg" else None

    def run(
        executable: HostPath, arguments: tuple[str, ...], **_kwargs: object
    ) -> ToolOutput:
        calls.append((str(executable), arguments))
        if arguments == ("-hide_banner", "-encoders"):
            return ToolOutput(listing, b"")
        return ToolOutput(b"ffmpeg version test", b"")

    monkeypatch.setattr(media_tools, "find_media_tool", find_tool)
    monkeypatch.setattr(
        media_tools,
        "inspect_tool_environment",
        lambda: HostToolEnvironment("win32", "amd64"),
    )
    monkeypatch.setattr(media_tools, "run_media_tool", run)
    monkeypatch.setattr(media_processing, "run_media_tool", run)
    ffmpeg = inspect_media_tools(checkpoint=lambda: None).tools[0]
    assert ffmpeg.usable and ffmpeg.encoders is not None
    for name in ("aac", "aac_at", "libfdk_aac", "libmp3lame"):
        assert (name in ffmpeg.encoders) == any(
            line.split()[1:2] == [name.encode()] for line in listing.splitlines()
        )
    assert calls == [
        (str(HostPath("C:/tools/ffmpeg.exe")), ("-version",)),
        (str(HostPath("C:/tools/ffmpeg.exe")), ("-hide_banner", "-encoders")),
    ]


def test_encoder_check_failure_is_not_a_missing_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def find_tool(name: str) -> HostPath:
        return HostPath(f"C:/{name}.exe")

    def run(
        _executable: HostPath, _arguments: tuple[str, ...], **_kwargs: object
    ) -> ToolOutput:
        return ToolOutput(b"ffmpeg ffprobe fpcalc version test", b"")

    def fail(*args: object, **kwargs: object) -> frozenset[str]:
        raise MediaToolError("media.tool_timeout", "Encoder check timed out")

    monkeypatch.setattr(media_tools, "find_media_tool", find_tool)
    monkeypatch.setattr(
        media_tools,
        "inspect_tool_environment",
        lambda: HostToolEnvironment("win32", "amd64"),
    )
    monkeypatch.setattr(media_tools, "run_media_tool", run)
    monkeypatch.setattr(media_tools, "read_media_encoders", fail)
    setup = inspect_media_tools(checkpoint=lambda: None)
    assert setup.ready and not setup.plan.commands
    assert setup.tools[0].encoders is None
    assert setup.tools[0].encoder_problem == "Encoder check timed out"
