"""PyPI release selection and nonblocking checks for installed Python packages."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from queue import Empty, SimpleQueue
from threading import Event, Thread
from typing import TYPE_CHECKING, cast
from urllib.parse import unquote, urlsplit

from packaging.specifiers import SpecifierSet
from packaging.tags import Tag, sys_tags
from packaging.utils import (
    canonicalize_name,
    parse_sdist_filename,
    parse_wheel_filename,
)
from packaging.version import Version

from storage.host_files import AtomicHostFile

from .backend import UpdateOutcome, UpdateProgress, UpdateResult
from .python_installation import PythonInstallation, running_python_installation
from .transport import UpdateTransport, validate_url

if TYPE_CHECKING:
    from collections.abc import Callable

    from .python_helper import PythonInstaller

PYPI_URL = "https://pypi.org/project/iOpenPod/"
PYPI_INDEX = "https://pypi.org/simple/iopenpod/"
PYPI_HOSTS = frozenset({"pypi.org", "files.pythonhosted.org"})
MAX_PYPI_METADATA = 2 * 1024**2
MAX_WHEEL = 100 * 1024**2


@dataclass(frozen=True, slots=True)
class PythonWheel:
    version: str
    filename: str
    url: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class PythonRelease:
    latest_version: Version
    wheel: PythonWheel | None


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Invalid PyPI metadata object")
    return cast("dict[str, object]", value)


def select_release(
    data: bytes,
    *,
    python_version: str | None = None,
    supported_tags: frozenset[Tag] | None = None,
) -> PythonRelease:
    """Select the newest non-yanked stable wheel compatible with this runtime."""
    if len(data) > MAX_PYPI_METADATA:
        raise ValueError("PyPI metadata exceeds its size limit")
    value = _object(json.loads(data))
    if value.get("name") != "iopenpod":
        raise ValueError("PyPI returned a different project")
    api = _object(value.get("meta")).get("api-version")
    if not isinstance(api, str) or api.split(".")[0] != "1":
        raise ValueError("Unsupported PyPI index API")
    raw_files = value.get("files")
    if not isinstance(raw_files, list):
        raise ValueError("Invalid PyPI file list")
    files = cast("list[object]", raw_files)
    if len(files) > 10_000:
        raise ValueError("Invalid PyPI file list")
    tags = supported_tags if supported_tags is not None else frozenset(sys_tags())
    python = Version(python_version or ".".join(map(str, sys.version_info[:3])))
    latest: Version | None = None
    wheels: list[PythonWheel] = []
    for raw in files:
        item = _object(raw)
        filename = item.get("filename")
        yanked = item.get("yanked", False)
        if not isinstance(yanked, (bool, str)) or not isinstance(filename, str):
            raise ValueError("Invalid PyPI file identity")
        if (
            yanked is not False
        ):  # A reason may be an empty string and still mean yanked.
            continue
        wheel_tags: frozenset[Tag]
        if filename.endswith(".whl"):
            name, version, _, wheel_tags = parse_wheel_filename(filename)
        elif filename.endswith((".tar.gz", ".zip")):
            name, version = parse_sdist_filename(filename)
            wheel_tags = frozenset()
        else:
            continue
        if canonicalize_name(name) != "iopenpod":
            raise ValueError("PyPI file belongs to a different project")
        if version.is_prerelease or version.is_devrelease or version.local:
            continue
        latest = max(latest, version) if latest is not None else version
        requirement = item.get("requires-python")
        if requirement is not None and not isinstance(requirement, str):
            raise ValueError("Invalid Python compatibility requirement")
        if not (wheel_tags & tags) or python not in SpecifierSet(requirement or ""):
            continue
        url, size = item.get("url"), item.get("size")
        digest = _object(item.get("hashes")).get("sha256")
        if (
            not isinstance(url, str)
            or type(size) is not int
            or not 0 < size <= MAX_WHEEL
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise ValueError("Invalid PyPI wheel size or digest")
        validate_url(url, frozenset({"files.pythonhosted.org"}))
        parsed = urlsplit(url)
        if parsed.query or unquote(parsed.path.rsplit("/", 1)[-1]) != filename:
            raise ValueError("PyPI wheel URL does not match its filename")
        wheels.append(PythonWheel(str(version), filename, url, size, digest))
    if latest is None:
        raise ValueError("PyPI did not provide a non-yanked stable release")
    return PythonRelease(
        latest,
        max(wheels, key=lambda wheel: Version(wheel.version)) if wheels else None,
    )


class PyPIBackend:
    def __init__(
        self,
        installation: PythonInstallation,
        installer: PythonInstaller | None,
        *,
        transport: UpdateTransport | None = None,
        restriction: str = "",
    ) -> None:
        self.installation = installation
        self._installer = installer
        self._restriction = restriction or installation.restriction
        self._transport = transport or UpdateTransport(
            hosts=PYPI_HOSTS,
            metadata_limit=MAX_PYPI_METADATA,
            accept="application/vnd.pypi.simple.v1+json",
        )
        self._events: SimpleQueue[UpdateResult | UpdateProgress] = SimpleQueue()
        self._cancel = Event()
        self._thread: Thread | None = None
        self._wheel: PythonWheel | None = None
        self._closed = False
        self._read_previous_result = False

    def _work(self, action: Callable[[], UpdateResult]) -> None:
        if self._closed or (self._thread and self._thread.is_alive()):
            raise RuntimeError("The PyPI updater is closed or already busy")

        def run() -> None:
            try:
                result = action()
            except Exception as error:
                result = UpdateResult(UpdateOutcome.FAILED, str(error))
            self._thread = None
            if not self._cancel.is_set():
                self._events.put(result)

        self._thread = Thread(target=run, name="pypi-update", daemon=True)
        self._thread.start()

    def _previous_failure(self) -> str:
        if self._read_previous_result:
            return ""
        self._read_previous_result = True
        state = AtomicHostFile(self.installation.result_path)
        data = state.read_bytes()
        if data is None:
            return ""
        if len(data) > 16 * 1024:
            raise ValueError("Invalid retained Python update result")
        value = _object(json.loads(data))
        if value.get("outcome") != "failed" or value.get("reported") is True:
            return ""
        detail = value.get("detail")
        if not isinstance(detail, str):
            raise ValueError("Invalid retained Python update failure")
        state.replace_bytes(json.dumps({**value, "reported": True}).encode())
        return detail

    def check(self) -> None:
        self._wheel = None

        def check() -> UpdateResult:
            previous = self._previous_failure()
            if previous:
                return UpdateResult(UpdateOutcome.FAILED, previous)
            release = select_release(self._transport.metadata(PYPI_INDEX, self._cancel))
            installed = Version(self.installation.version)
            if release.latest_version <= installed:
                return UpdateResult(UpdateOutcome.CURRENT)
            wheel = release.wheel
            if wheel is None or Version(wheel.version) <= installed:
                return UpdateResult(
                    UpdateOutcome.MANUAL,
                    "A newer PyPI release requires a different Python runtime or has no compatible wheel.",
                    str(release.latest_version),
                    PYPI_URL,
                )
            if self._installer is None:
                return UpdateResult(
                    UpdateOutcome.MANUAL,
                    "A PyPI update is available. " + self._restriction,
                    wheel.version,
                    PYPI_URL,
                )
            self._wheel = wheel
            return UpdateResult(UpdateOutcome.AVAILABLE, version=wheel.version)

        self._work(check)

    def _selected(self) -> PythonWheel:
        if self._wheel is None or self._installer is None:
            raise RuntimeError("Check for an installable PyPI update first")
        if running_python_installation() != self.installation:
            raise ValueError("The Python installation changed; restart and check again")
        return self._wheel

    def download(self) -> None:
        def stage() -> UpdateResult:
            wheel = self._selected()
            assert self._installer is not None
            self._installer.stage(
                wheel,
                self._transport,
                self._cancel,
                lambda fraction: self._events.put(
                    UpdateProgress(wheel.filename, fraction, False)
                ),
            )
            return UpdateResult(UpdateOutcome.READY, version=wheel.version)

        self._work(stage)

    def install(self) -> None:
        # Recheck yanking and file identity immediately before handing off.
        def handoff() -> UpdateResult:
            wheel = self._selected()
            current = select_release(self._transport.metadata(PYPI_INDEX, self._cancel))
            if current.wheel != wheel:
                raise ValueError(
                    "The PyPI release changed; check and download it again"
                )
            assert self._installer is not None
            self._installer.install(wheel)
            return UpdateResult(UpdateOutcome.HANDOFF, version=wheel.version)

        self._work(handoff)

    def poll(self) -> UpdateResult | UpdateProgress | None:
        if self._closed:
            return None
        latest: UpdateResult | UpdateProgress | None = None
        while True:
            try:
                event = self._events.get_nowait()
            except Empty:
                return latest
            if isinstance(event, UpdateResult):
                return event
            latest = event

    def complete_handoff(self) -> None:
        if self._installer is None:
            raise RuntimeError("No Python installer owns this handoff")
        self._installer.complete_handoff()

    def close(self) -> None:
        self._closed = True
        self._cancel.set()
        if self._installer:
            self._installer.close()
