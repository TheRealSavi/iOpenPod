"""macOS whole-disk safe eject through Disk Arbitration's diskutil client."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

from storage.errors import EjectError
from storage.models import EjectResult

_WHOLE_DISK = re.compile(r"^disk\d+$")


@dataclass(frozen=True, slots=True)
class _CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


_Runner = Callable[[tuple[str, ...], int], _CommandResult]


class MacOSDeviceEjector:
    """Unmount every Volume, without force, then eject the exact whole disk."""

    def __init__(self, runner: _Runner | None = None) -> None:
        self._runner = runner or _run_diskutil

    def eject(self, whole_disk: str) -> EjectResult:
        if _WHOLE_DISK.fullmatch(whole_disk) is None:
            raise EjectError(
                "macOS could not identify an exact whole disk for safe eject."
            )

        try:
            unmount = self._runner(("diskutil", "unmountDisk", whole_disk), 75)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise EjectError(
                "macOS did not finish unmounting every iPod Volume; the iPod "
                f"was not ejected ({error})."
            ) from error
        if unmount.returncode != 0:
            raise EjectError(
                "macOS could not unmount every iPod Volume. Close files and apps "
                f"using the iPod, then try again. {_command_detail(unmount)}"
            )

        try:
            ejected = self._runner(("diskutil", "eject", whole_disk), 75)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise EjectError(
                "Every iPod Volume was unmounted, but macOS did not confirm the "
                "physical eject. Do not reconnect through iOpenPod; use Finder's "
                f"Eject command before unplugging ({error}).",
                volume_unmounted=True,
            ) from error
        if ejected.returncode != 0:
            raise EjectError(
                "Every iPod Volume was unmounted, but macOS did not confirm the "
                "physical eject. Use Finder's Eject command before unplugging. "
                f"{_command_detail(ejected)}",
                volume_unmounted=True,
            )
        return EjectResult(
            "macOS Disk Arbitration confirmed that the iPod is safe to remove."
        )


def _run_diskutil(command: tuple[str, ...], timeout: int) -> _CommandResult:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return _CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _command_detail(result: _CommandResult) -> str:
    detail = (result.stderr or result.stdout).strip()
    return detail or f"diskutil exited with code {result.returncode}."


__all__ = ["MacOSDeviceEjector"]
