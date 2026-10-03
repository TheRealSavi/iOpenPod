"""Background GitHub discovery and authenticated staging through typed installers."""

from __future__ import annotations

import json
import sys
from queue import Empty, SimpleQueue
from threading import Event, Thread
from typing import TYPE_CHECKING, Protocol

from storage import AtomicHostFile, HostResourceLease, application_config_file

from .backend import UpdateOutcome, UpdateProgress, UpdateResult
from .installation import Installation, require_supported_os
from .releases import (
    RELEASES_URL,
    REPOSITORY,
    Release,
    ReleaseAsset,
    ReleaseFloor,
    integer_field,
    read_json,
    text_field,
    verify_release,
    version_tuple,
)
from .transport import UpdateTransport

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


class ReleaseInstaller(Protocol):
    def stage(
        self,
        asset: ReleaseAsset,
        metadata: bytes,
        transport: UpdateTransport,
        cancel: Event,
        progress: Callable[[float], None],
    ) -> None: ...

    def install(self, asset: ReleaseAsset) -> None: ...

    def poll(self) -> UpdateResult | UpdateProgress | None: ...

    def complete_handoff(self) -> None: ...

    def close(self) -> None: ...


class GitHubBackend:
    def __init__(
        self,
        installation: Installation,
        installer: ReleaseInstaller | None,
        *,
        transport: UpdateTransport | None = None,
        state_path: Path | None = None,
    ) -> None:
        self.installation = installation
        self._installer = installer
        self._transport = transport or UpdateTransport()
        self._events: SimpleQueue[UpdateResult | UpdateProgress] = SimpleQueue()
        self._cancel = Event()
        self._thread: Thread | None = None
        self._release: Release | None = None
        self._metadata = b""
        self._closed = False
        platform_name = {"win32": "windows", "darwin": "macos", "linux": "linux"}[
            sys.platform
        ]
        self._state = AtomicHostFile(
            state_path
            or application_config_file(
                "iOpenPod", "update-history-v1.json", platform_name=platform_name
            )
        )

    def _work(self, action: Callable[[], UpdateResult]) -> None:
        if self._closed or (self._thread and self._thread.is_alive()):
            raise RuntimeError("The GitHub updater is closed or already busy")

        def run() -> None:
            try:
                result = action()
            except InterruptedError:
                result = UpdateResult(UpdateOutcome.CANCELED)
            except Exception as error:
                result = UpdateResult(UpdateOutcome.FAILED, str(error))
            self._thread = None
            if not self._cancel.is_set():
                self._events.put(result)

        self._thread = Thread(target=run, name="application-update", daemon=True)
        self._thread.start()

    def check(self) -> None:
        self._work(self._check)

    def _floor(self) -> ReleaseFloor:
        data = self._state.read_bytes()
        if data is None:
            return ReleaseFloor()
        value = read_json(data)
        return ReleaseFloor(
            integer_field(value, "sequence", 2**53 - 1),
            text_field(value, "version"),
            text_field(value, "digest"),
        )

    def _check(self) -> UpdateResult:
        if not self.installation.public_keys:
            value = read_json(
                self._transport.metadata(
                    f"https://api.github.com/repos/{REPOSITORY}/releases/latest",
                    self._cancel,
                )
            )
            tag = text_field(value, "tag_name")
            if not tag.startswith("v"):
                raise ValueError(
                    f"The latest GitHub release ({tag}) has no supported version tag; visit Releases"
                )
            version_tuple(tag[1:])
            if value.get("draft") is not False or value.get("prerelease") is not False:
                raise ValueError("GitHub did not return a published stable release")
            if version_tuple(tag[1:]) > version_tuple(self.installation.version):
                return UpdateResult(
                    UpdateOutcome.MANUAL,
                    "A newer GitHub release is available. This build has no configured update trust key; download it manually.",
                    tag[1:],
                    f"{RELEASES_URL}/tag/{tag}",
                )
            return UpdateResult(UpdateOutcome.CURRENT)
        data = self._transport.metadata(self.installation.feed_url, self._cancel)
        with HostResourceLease("iOpenPod update release history"):
            release = verify_release(
                data, self.installation.public_keys, floor=self._floor()
            )
            asset = release.asset(self.installation.target)
            require_supported_os(asset.minimum_os, asset.target)
            if self._cancel.is_set():
                raise InterruptedError
            self._state.replace_bytes(
                json.dumps(
                    {
                        "sequence": release.sequence,
                        "version": release.version,
                        "digest": release.digest,
                    }
                ).encode()
            )
        self._release, self._metadata = release, data
        if version_tuple(release.version) <= version_tuple(self.installation.version):
            return UpdateResult(UpdateOutcome.CURRENT)
        if self._installer is None:
            return UpdateResult(
                UpdateOutcome.MANUAL,
                "A newer release is available. Use the download page for this installation.",
                release.version,
                f"{RELEASES_URL}/tag/v{release.version}",
            )
        return UpdateResult(UpdateOutcome.AVAILABLE, version=release.version)

    def download(self) -> None:
        def stage() -> UpdateResult:
            asset = self._selected()
            assert self._installer is not None
            self._installer.stage(
                asset,
                self._metadata,
                self._transport,
                self._cancel,
                lambda fraction: self._events.put(
                    UpdateProgress(asset.filename, fraction, False)
                ),
            )
            return UpdateResult(UpdateOutcome.READY, version=asset.version)

        self._work(stage)

    def _selected(self) -> ReleaseAsset:
        if self._release is None or self._installer is None:
            raise RuntimeError("Check for an authenticated update first")
        # Expiry is checked again at download and final installation.
        release = verify_release(
            self._metadata, self.installation.public_keys, floor=self._floor()
        )
        asset = release.asset(self.installation.target)
        require_supported_os(asset.minimum_os, asset.target)
        return asset

    def install(self) -> None:
        asset = self._selected()
        assert self._installer is not None
        self._installer.install(asset)

    def poll(self) -> UpdateResult | UpdateProgress | None:
        if self._closed:
            return None
        latest = None
        while True:
            try:
                event = self._events.get_nowait()
            except Empty:
                return latest or (self._installer.poll() if self._installer else None)
            if isinstance(event, UpdateResult):
                return event
            latest = event

    def complete_handoff(self) -> None:
        if self._installer is None:
            raise RuntimeError("No installer owns this handoff")
        self._installer.complete_handoff()

    def close(self) -> None:
        self._closed = True
        self._cancel.set()
        if self._installer:
            self._installer.close()
