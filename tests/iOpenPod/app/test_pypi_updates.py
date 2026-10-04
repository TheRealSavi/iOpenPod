"""PyPI discovery excludes incompatible/yanked files and separates check from install."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event
from time import monotonic, sleep

import pytest
from packaging.tags import Tag
from packaging.version import Version
from tests.iOpenPod.app.test_python_installation import (
    python_installation_fixture as python_installation_fixture,
)

from iOpenPod.app.updates import pypi
from iOpenPod.app.updates.backend import UpdateOutcome, UpdateResult
from iOpenPod.app.updates.python_helper import PythonInstaller
from iOpenPod.app.updates.python_installation import PythonInstallation
from iOpenPod.app.updates.transport import UpdateTransport, validate_url


def file(version: str = "2.0.5", /, **overrides: object) -> dict[str, object]:
    filename = f"iopenpod-{version}-py3-none-any.whl"
    return {
        "filename": filename,
        "url": f"https://files.pythonhosted.org/packages/{filename}",
        "hashes": {"sha256": hashlib.sha256(b"wheel").hexdigest()},
        "size": 5,
        "yanked": False,
        "requires-python": ">=3.12,<3.13",
        **overrides,
    }


def index(*files: dict[str, object]) -> bytes:
    return json.dumps(
        {"name": "iopenpod", "meta": {"api-version": "1.4"}, "files": list(files)}
    ).encode()


def selected(data: bytes) -> pypi.PythonRelease:
    return pypi.select_release(
        data,
        python_version="3.12.14",
        supported_tags=frozenset({Tag("py3", "none", "any")}),
    )


def test_selects_newest_compatible_stable_non_yanked_wheel() -> None:
    result = selected(
        index(
            file("2.0.4"),
            file("2.0.5"),
            file("2.0.6", yanked=""),
            file("2.0.7", yanked=True),
            file("2.0.8rc1"),
            file("2.1.0", **{"requires-python": ">=3.13"}),
        )
    )
    assert result.latest_version == Version("2.1.0")
    assert result.wheel is not None and result.wheel.version == "2.0.5"


@pytest.mark.parametrize(
    "fields",
    [
        {"hashes": {"sha256": "bad"}},
        {"size": 0},
        {"size": True},
        {
            "url": "http://files.pythonhosted.org/packages/iopenpod-2.0.5-py3-none-any.whl"
        },
        {"url": "https://evil.test/iopenpod-2.0.5-py3-none-any.whl"},
        {"url": "https://files.pythonhosted.org/not-the-wheel.whl"},
        {
            "url": "https://user:password@files.pythonhosted.org/iopenpod-2.0.5-py3-none-any.whl"
        },
        {"requires-python": "not a specifier"},
        {"yanked": None},
    ],
)
def test_invalid_release_metadata_never_becomes_installable(
    fields: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        selected(index(file(**fields)))


def test_no_sdist_execution_or_downgrade_selection() -> None:
    result = selected(index(file(filename="iopenpod-2.0.5.tar.gz")))
    assert result.latest_version == Version("2.0.5") and result.wheel is None
    with pytest.raises(ValueError, match="non-yanked"):
        selected(index(file(yanked=True)))


def test_transport_origin_sets_stay_separate() -> None:
    validate_url("https://pypi.org/simple/iopenpod/", pypi.PYPI_HOSTS)
    with pytest.raises(ValueError):
        validate_url("https://pypi.org/simple/iopenpod/")
    with pytest.raises(ValueError):
        validate_url("https://github.com/anything", pypi.PYPI_HOSTS)


class Transport(UpdateTransport):
    def __init__(self, data: bytes) -> None:
        self.data = data

    def metadata(self, url: str, cancel: Event) -> bytes:
        assert url == pypi.PYPI_INDEX
        return self.data


class Installer(PythonInstaller):
    def __init__(self) -> None:
        self.downloads = 0
        self.installs = 0
        self.handoffs = 0

    def stage(
        self,
        wheel: pypi.PythonWheel,
        transport: UpdateTransport,
        cancel: Event,
        progress: Callable[[float], None],
    ) -> None:
        self.downloads += 1
        progress(1)

    def install(self, wheel: pypi.PythonWheel) -> None:
        self.installs += 1

    def complete_handoff(self) -> None:
        self.handoffs += 1

    def close(self) -> None:
        pass


def result(backend: pypi.PyPIBackend) -> UpdateResult:
    deadline = monotonic() + 3
    while monotonic() < deadline:
        event = backend.poll()
        if isinstance(event, UpdateResult):
            return event
        sleep(0.005)
    raise AssertionError("No PyPI result")


@pytest.fixture(autouse=True)
def result_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        PythonInstallation,
        "result_path",
        property(lambda _self: tmp_path / "result.json"),
    )


def test_check_download_and_install_are_separate_requests(
    installed_python: PythonInstallation,
) -> None:
    installer = Installer()
    backend = pypi.PyPIBackend(
        installed_python, installer, transport=Transport(index(file()))
    )
    try:
        backend.check()
        assert result(backend).outcome is UpdateOutcome.AVAILABLE
        assert installer.downloads == installer.installs == 0
        backend.download()
        assert result(backend).outcome is UpdateOutcome.READY
        assert installer.downloads == 1 and installer.installs == 0
        backend.install()
        assert result(backend).outcome is UpdateOutcome.HANDOFF
        assert installer.installs == 1 and installer.handoffs == 0
        backend.complete_handoff()
        assert installer.handoffs == 1
    finally:
        backend.close()


@pytest.mark.parametrize("version", ["2.0.3", "2.0.4"])
def test_current_or_older_never_offers_an_install(
    installed_python: PythonInstallation, version: str
) -> None:
    backend = pypi.PyPIBackend(
        installed_python, Installer(), transport=Transport(index(file(version)))
    )
    backend.check()
    assert result(backend).outcome is UpdateOutcome.CURRENT
    backend.install()
    assert result(backend).outcome is UpdateOutcome.FAILED
    backend.close()


def test_newer_python_requirement_is_not_reported_as_current(
    installed_python: PythonInstallation,
) -> None:
    backend = pypi.PyPIBackend(
        installed_python,
        Installer(),
        transport=Transport(index(file(**{"requires-python": ">=4"}))),
    )
    backend.check()
    assert result(backend).outcome is UpdateOutcome.MANUAL
    backend.close()


def test_managed_environment_gets_update_notice_without_installer(
    installed_python: PythonInstallation,
) -> None:
    backend = pypi.PyPIBackend(
        replace(installed_python, restriction="Use the tool manager"),
        None,
        transport=Transport(index(file())),
    )
    backend.check()
    response = result(backend)
    assert (
        response.outcome is UpdateOutcome.MANUAL and "tool manager" in response.detail
    )
    backend.close()


def test_release_change_after_download_prevents_handoff(
    installed_python: PythonInstallation,
) -> None:
    transport, installer = Transport(index(file())), Installer()
    backend = pypi.PyPIBackend(installed_python, installer, transport=transport)
    backend.check()
    assert result(backend).outcome is UpdateOutcome.AVAILABLE
    backend.download()
    assert result(backend).outcome is UpdateOutcome.READY
    transport.data = index(file(hashes={"sha256": "f" * 64}))
    backend.install()
    assert result(backend).outcome is UpdateOutcome.FAILED
    assert installer.installs == 0
    backend.close()


def test_network_metadata_errors_do_not_claim_up_to_date(
    installed_python: PythonInstallation,
) -> None:
    backend = pypi.PyPIBackend(
        installed_python, Installer(), transport=Transport(b"not JSON")
    )
    backend.check()
    assert result(backend).outcome is UpdateOutcome.FAILED
    backend.close()


def test_post_restart_failure_is_reported_once_then_checks_again(
    installed_python: PythonInstallation,
) -> None:
    installed_python.result_path.write_text(
        json.dumps(
            {
                "outcome": "failed",
                "detail": "Installation failed; retained logs",
                "reported": False,
            }
        )
    )
    backend = pypi.PyPIBackend(
        installed_python, Installer(), transport=Transport(index(file()))
    )
    backend.check()
    assert result(backend).detail == "Installation failed; retained logs"
    backend.check()
    assert result(backend).outcome is UpdateOutcome.AVAILABLE
    backend.close()
