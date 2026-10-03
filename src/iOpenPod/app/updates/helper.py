"""Independent installation owner. No directory deletion, mirroring, or elevation."""

from __future__ import annotations

import json
import time
from contextlib import ExitStack
from typing import TYPE_CHECKING

from storage.host_installation import (
    durable_write,
    file_identity,
    move_owned_file,
    pin_installation,
    require_plain_path,
)
from storage.host_usage import HostInstallationLease

from .portable import Operation, read_operation, verify_linux_runtime
from .processes import ParentProcess, candidate_process, independent_process
from .releases import read_json, text_field, version_tuple

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from .processes import CandidateProcess


def _wait(predicate: Callable[[], bool], timeout: float, operation: Operation) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if operation.matches("canceled", operation.nonce):
            raise InterruptedError("Application update canceled before completion")
        if time.monotonic() >= deadline:
            raise TimeoutError("Timed out waiting for application update handoff")
        time.sleep(0.1)


def _phase(operation: Operation, phase: str) -> None:
    operation.write(
        "journal.json", json.dumps({"phase": phase, "nonce": operation.nonce})
    )


def _windows_install(operation: Operation) -> None:
    previous = operation.directory / "previous.exe"
    _phase(operation, "moving-previous")
    move_owned_file(operation.target, previous, operation.previous)
    _phase(operation, "publishing")
    move_owned_file(operation.candidate, operation.target, operation.incoming)
    _phase(operation, "awaiting-health")


def _linux_install(operation: Operation) -> None:
    pointer = require_plain_path(operation.root / "current.json")
    expected = operation.target.parent.name
    if read_json(pointer.read_bytes()) != {"version": expected}:
        raise ValueError("The Linux launch pointer changed since staging")
    _phase(operation, "publishing")
    durable_write(pointer, json.dumps({"version": operation.asset.version}).encode())
    _phase(operation, "awaiting-health")


def restore_previous(operation: Operation) -> None:
    """Idempotent recovery based on exact file identities, never journal claims."""
    if operation.asset.target.startswith("windows"):
        previous = require_plain_path(operation.directory / "previous.exe")
        if not previous.exists():
            if (
                operation.target.exists()
                and file_identity(operation.target) == operation.previous
            ):
                return
            raise ValueError("Recovery cannot locate the unchanged previous executable")
        if file_identity(previous) != operation.previous:
            raise ValueError("Recovery executable was changed; retained all files")
        if operation.target.exists():
            if file_identity(operation.target) != operation.incoming:
                raise ValueError(
                    "An unrelated file occupies the executable path; retained all files"
                )
            move_owned_file(
                operation.target, operation.directory / "failed.exe", operation.incoming
            )
        move_owned_file(previous, operation.target, operation.previous)
    else:
        pointer = require_plain_path(operation.root / "current.json")
        current = read_json(pointer.read_bytes())
        if current == {"version": operation.target.parent.name}:
            return
        if (
            current != {"version": operation.asset.version}
            or file_identity(operation.target) != operation.previous
        ):
            raise ValueError(
                "Linux recovery found changed installation state; retained all files"
            )
        durable_write(
            pointer, json.dumps({"version": operation.target.parent.name}).encode()
        )
    _phase(operation, "rolled-back")


def install(directory: Path, public_keys: tuple[str, ...]) -> None:
    operation = read_operation(directory, public_keys)
    with ExitStack() as stack:
        stack.enter_context(pin_installation(operation.root))
        stack.enter_context(pin_installation(directory))
        parents: list[ParentProcess] = []
        for pid in operation.parents:
            parent = ParentProcess(pid, operation.target)
            stack.callback(parent.close)
            parents.append(parent)
        if (
            file_identity(operation.target) != operation.previous
            or file_identity(operation.candidate) != operation.incoming
        ):
            raise ValueError("An installation payload changed after staging")
        if operation.incoming.sha256 != operation.asset.executable_sha256:
            raise ValueError("Candidate executable is not authenticated")
        if operation.asset.target.startswith("linux"):
            verify_linux_runtime(
                operation.directory / "download",
                operation.candidate.parent,
                operation.asset,
            )
        # This checks the frozen dependency graph without settings or devices.
        probe = candidate_process([str(operation.candidate), "--smoke-test"])
        try:
            result = probe.wait(timeout=120)
        except BaseException:
            probe.stop()
            raise
        finally:
            probe.release()
        if result:
            raise RuntimeError(
                "The downloaded application failed its runtime check; the installed application was preserved"
            )
        operation.write("ready", operation.nonce)
        _wait(lambda: operation.matches("authorized", operation.nonce), 180, operation)
        _wait(lambda: all(parent.exited() for parent in parents), 60, operation)
        key = (
            operation.target
            if operation.asset.target.startswith("windows")
            else operation.root
        )
        # No further instance may start until health has committed or rollback ends.
        deadline = time.monotonic() + 15
        while True:
            try:
                maintenance = HostInstallationLease(key, exclusive=True)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
        with maintenance:
            child: CandidateProcess | None = None
            committed = False
            try:
                if operation.asset.target.startswith("windows"):
                    _windows_install(operation)
                    executable = operation.target
                else:
                    _linux_install(operation)
                    executable = operation.candidate
                child = candidate_process(
                    [
                        str(executable),
                        "--update-health",
                        str(directory),
                        operation.nonce,
                    ]
                )
                _wait(
                    lambda: (
                        operation.matches("healthy", operation.nonce)
                        or child.poll() is not None
                    ),
                    120,
                    operation,
                )
                if child.poll() is not None or not operation.matches(
                    "healthy", operation.nonce
                ):
                    raise RuntimeError("The updated application did not become healthy")
                _phase(operation, "committed")
                operation.write("committed", operation.nonce)
                committed = True
                child.release()
            except BaseException:
                if not committed:
                    if child is not None:
                        # Stop the entire bootloader tree before trying rollback.
                        child.stop()
                        child.release()
                    restore_previous(operation)
                raise


def recover(directory: Path, public_keys: tuple[str, ...]) -> None:
    operation = read_operation(directory, public_keys, recovery=True)
    if operation.matches("committed", operation.nonce):
        raise ValueError("This update already committed; use a newer release instead")
    key = (
        operation.target
        if operation.asset.target.startswith("windows")
        else operation.root
    )
    with (
        pin_installation(operation.root),
        pin_installation(directory),
        HostInstallationLease(key, exclusive=True),
    ):
        restore_previous(operation)


def launch_managed(root: Path, arguments: list[str]) -> int:
    require_plain_path(root)
    with HostInstallationLease(root):
        value = read_json((root / "current.json").read_bytes())
        version = text_field(value, "version")
        version_tuple(version)
        executable = require_plain_path(root / "versions" / version / "iOpenPod")
        # Keep the shared lease for the child's whole lifetime, including startup.
        return independent_process([str(executable), *arguments]).wait()
