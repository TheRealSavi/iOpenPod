"""Inspect optional Host tools and plan installation through native channels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from iOpenPod.app.display_text import source_text
from storage.host_tools import HostToolEnvironment, inspect_tool_environment
from storage.media_processing import (
    MediaToolError,
    find_media_tool,
    read_media_encoders,
    run_media_tool,
)

if TYPE_CHECKING:
    from collections.abc import Callable

TOOL_NAMES = ("ffmpeg", "ffprobe", "fpcalc")
_HELP = "https://therealsavi.github.io/iOpenPod/install-help.html"


@dataclass(frozen=True, slots=True)
class MediaToolStatus:
    name: str
    path: str = ""
    problem: str = ""
    encoders: frozenset[str] | None = None
    encoder_problem: str = ""

    @property
    def usable(self) -> bool:
        return bool(self.path) and not self.problem


@dataclass(frozen=True, slots=True)
class InstallCommand:
    label: str
    program: str
    arguments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MediaToolInstallPlan:
    channel: str
    explanation: str
    commands: tuple[InstallCommand, ...] = ()
    help_url: str = _HELP


@dataclass(frozen=True, slots=True)
class MediaToolSetup:
    tools: tuple[MediaToolStatus, ...]
    plan: MediaToolInstallPlan

    @property
    def ready(self) -> bool:
        return all(tool.usable for tool in self.tools)


def inspect_media_tools(*, checkpoint: Callable[[], None]) -> MediaToolSetup:
    tools: list[MediaToolStatus] = []
    for name in TOOL_NAMES:
        checkpoint()
        executable = find_media_tool(name)
        if executable is None:
            tools.append(MediaToolStatus(name))
            continue
        problem = ""
        try:
            output = run_media_tool(
                executable,
                ("-version",),
                checkpoint=checkpoint,
                timeout_seconds=5,
                max_output_bytes=65536,
                max_stderr_bytes=65536,
            )
            # A PATH match alone does not prove the expected executable can run.
            if name.encode() not in (output.stdout + output.stderr).lower():
                problem = "The executable did not identify itself as " + name + "."
        except MediaToolError as error:
            problem = str(error)[:600]
        encoders: frozenset[str] | None = None
        encoder_problem = ""
        if name == "ffmpeg" and not problem:
            try:
                encoders = read_media_encoders(
                    executable, checkpoint=checkpoint, timeout_seconds=5
                )
            except MediaToolError as error:
                encoder_problem = str(error)[:600]
        tools.append(
            MediaToolStatus(name, str(executable), problem, encoders, encoder_problem)
        )
    statuses = tuple(tools)
    return MediaToolSetup(
        statuses, plan_media_tool_install(inspect_tool_environment(), statuses)
    )


def plan_media_tool_install(
    host: HostToolEnvironment, tools: tuple[MediaToolStatus, ...]
) -> MediaToolInstallPlan:
    """Choose fixed package IDs only for absent tools; never repair by overwriting."""
    missing = {tool.name for tool in tools if not tool.path}
    if not missing:
        return MediaToolInstallPlan(
            "Installed tools",
            "All tools are available."
            if all(t.usable for t in tools)
            else "A tool was found but could not run. Repair that installation or its PATH, then check again.",
        )
    if host.confined:
        return MediaToolInstallPlan(
            "Sandboxed application",
            "This application cannot install Host packages from its sandbox. "
            "Use a native iOpenPod installation or configure tools accessible inside this sandbox.",
        )
    need_ffmpeg = bool(missing & {"ffmpeg", "ffprobe"})
    need_fpcalc = "fpcalc" in missing
    if host.system == "win32":
        help_url = "https://learn.microsoft.com/windows/package-manager/winget/"
        winget = host.executable("winget")
        if not winget:
            return MediaToolInstallPlan(
                "WinGet",
                "Install Microsoft's App Installer (WinGet), then choose Check Again.",
                help_url=help_url,
            )
        if host.architecture not in {"amd64", "x86_64", "arm64", "aarch64"}:
            return MediaToolInstallPlan(
                "WinGet", "These packages require 64-bit Windows.", help_url=help_url
            )
        packages = (("Gyan.FFmpeg",) if need_ffmpeg else ()) + (
            ("AcoustID.Chromaprint",) if need_fpcalc else ()
        )
        commands = tuple(
            InstallCommand(
                package,
                winget,
                (
                    "install",
                    "--id",
                    package,
                    "--exact",
                    "--source",
                    "winget",
                    "--scope",
                    "user",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                    "--disable-interactivity",
                    "--silent",
                ),
            )
            for package in packages
        )
        return MediaToolInstallPlan(
            "WinGet · Gyan FFmpeg / AcoustID Chromaprint",
            "Install missing packages for your Windows account. FFmpeg includes FFprobe. "
            "Install accepts the package and WinGet source agreements. "
            "On ARM Windows these packages use x64 emulation.",
            commands,
            help_url,
        )
    if host.system == "darwin":
        brew = host.executable("brew")
        architecture = (
            "Apple Silicon" if host.architecture in {"arm64", "aarch64"} else "Intel"
        )
        if not brew:
            return MediaToolInstallPlan(
                f"Homebrew · {architecture}",
                "Install Homebrew from its official setup page, then choose Check Again. "
                "Homebrew may require Apple's Command Line Tools and an administrator password.",
                help_url="https://brew.sh/",
            )
        packages = (("ffmpeg",) if need_ffmpeg else ()) + (
            ("chromaprint",) if need_fpcalc else ()
        )
        return MediaToolInstallPlan(
            f"Homebrew · {architecture}",
            "Homebrew installs the missing packages and their dependencies. FFmpeg includes FFprobe. "
            "Older macOS and Intel systems may build from source; Homebrew's OS support differs from iOpenPod's.",
            (
                InstallCommand(
                    "Homebrew media tools",
                    "/usr/bin/arch",
                    (
                        "-arm64" if architecture == "Apple Silicon" else "-x86_64",
                        brew,
                        "install",
                        *packages,
                    ),
                ),
            ),
            "https://docs.brew.sh/Installation",
        )
    if host.system.startswith("linux"):
        return _linux_plan(host, need_ffmpeg=need_ffmpeg, need_fpcalc=need_fpcalc)
    return MediaToolInstallPlan(
        "Manual setup",
        "No automatic installation channel is available for this operating system.",
    )


def _linux_plan(
    host: HostToolEnvironment, *, need_ffmpeg: bool, need_fpcalc: bool
) -> MediaToolInstallPlan:
    ids = host.distribution_ids
    arguments: tuple[str, ...]
    if ids & {"debian", "ubuntu"}:
        manager, arguments, fingerprint, ffmpeg = (
            "apt-get",
            ("install", "--yes", "--no-remove"),
            "libchromaprint-tools",
            "ffmpeg",
        )
    elif "fedora" in ids:
        manager, arguments, fingerprint, ffmpeg = (
            "dnf",
            ("install", "--assumeyes"),
            "chromaprint-tools",
            "ffmpeg-free",
        )
    elif ids & {"arch", "manjaro"}:
        manager, arguments, fingerprint, ffmpeg = (
            "pacman",
            ("-S", "--needed", "--noconfirm"),
            "chromaprint",
            "ffmpeg",
        )
    elif "opensuse-tumbleweed" in ids:
        manager, arguments, fingerprint, ffmpeg = (
            "zypper",
            ("--non-interactive", "install"),
            "chromaprint-fpcalc",
            "ffmpeg",
        )
    else:
        return MediaToolInstallPlan(
            "Linux packages",
            "Install FFmpeg and Chromaprint's fpcalc using your distribution's package manager, then check again.",
        )
    executable = host.executable(manager)
    pkexec = host.executable("pkexec")
    if executable is None or (pkexec is None and not host.administrator):
        return MediaToolInstallPlan(
            manager,
            source_text(
                "Automatic setup needs {manager} and a graphical polkit authentication agent (pkexec). "
                "Install {ffmpeg} and {fingerprint} with your system package manager, then check again.",
                manager=manager,
                ffmpeg=ffmpeg,
                fingerprint=fingerprint,
            ),
        )
    packages = ((ffmpeg,) if need_ffmpeg else ()) + (
        (fingerprint,) if need_fpcalc else ()
    )
    command = InstallCommand(
        manager + " media tools",
        executable if host.administrator else str(pkexec),
        (*(() if host.administrator else (executable,)), *arguments, *packages),
    )
    return MediaToolInstallPlan(
        manager + " · configured distribution repositories",
        "Your system may ask for administrator approval. Installs missing packages and their dependencies. "
        "No repositories are added. Available codecs depend on the distribution's FFmpeg build.",
        (command,),
    )
