"""Asynchronous discovery/staging and install-channel isolation contracts."""

import base64
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from time import monotonic, sleep

import pytest
from Crypto.Signature import eddsa
from scripts.update_feed import signed_envelope

from iOpenPod.app.updates.backend import UpdateOutcome, UpdateProgress, UpdateResult
from iOpenPod.app.updates.github import GitHubBackend
from iOpenPod.app.updates.installation import Installation
from iOpenPod.app.updates.releases import REPOSITORY, ReleaseAsset
from iOpenPod.app.updates.transport import UpdateTransport

SEED = bytes(range(32))
KEYS = (
    base64.b64encode(
        eddsa.import_private_key(SEED).public_key().export_key(format="raw")
    ).decode(),
)


@pytest.fixture(autouse=True)
def windows_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "iOpenPod.app.updates.installation.platform.version", lambda: "10.0.26200"
    )


def release(
    version: str = "2.0.2", sequence: int = 42, *, expires: datetime | None = None
) -> bytes:
    now = datetime.now(UTC)
    return signed_envelope(
        {
            "schema": 1,
            "product": "iOpenPod",
            "repository": REPOSITORY,
            "track": "stable",
            "version": version,
            "tag": f"v{version}",
            "sequence": sequence,
            "issued": now.isoformat(),
            "expires": (expires or now + timedelta(days=30)).isoformat(),
            "assets": [
                {
                    "target": "windows-x86_64",
                    "layout": "windows-onefile-v1",
                    "updater_protocol": 1,
                    "size": 1,
                    "sha256": "a" * 64,
                    "executable_sha256": "b" * 64,
                    "minimum_os": "0.0",
                }
            ],
        },
        SEED,
    )


class Transport(UpdateTransport):
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.urls: list[str] = []

    def metadata(self, url: str, cancel: Event) -> bytes:
        self.urls.append(url)
        return self.data


class Installer:
    def __init__(self) -> None:
        self.staged = False
        self.installed = False
        self.closed = False
        self.handoff = False

    def stage(
        self,
        asset: ReleaseAsset,
        metadata: bytes,
        transport: UpdateTransport,
        cancel: Event,
        progress: Callable[[float], None],
    ) -> None:
        self.staged = True
        progress(0.5)

    def install(self, asset: ReleaseAsset) -> None:
        self.installed = True

    def poll(self) -> UpdateResult | UpdateProgress | None:
        return None

    def complete_handoff(self) -> None:
        self.handoff = True

    def close(self) -> None:
        self.closed = True


def result(backend: GitHubBackend) -> UpdateResult:
    deadline = monotonic() + 3
    while monotonic() < deadline:
        event = backend.poll()
        if isinstance(event, UpdateResult):
            return event
        sleep(0.005)
    raise AssertionError("Background update check did not finish")


def build(
    tmp_path: Path,
    transport: Transport,
    installer: Installer | None,
    keys: tuple[str, ...] = KEYS,
) -> GitHubBackend:
    return GitHubBackend(
        Installation(
            "2.0.1",
            "windows-x86_64",
            "windows-onefile-v1",
            keys,
            tmp_path / "iOpenPod.exe",
            tmp_path,
        ),
        installer,
        transport=transport,
        state_path=tmp_path / "history.json",
    )


def test_check_stages_only_after_request_and_installs_only_after_restart(
    tmp_path: Path,
) -> None:
    transport, installer = Transport(release()), Installer()
    backend = build(tmp_path, transport, installer)
    try:
        backend.check()
        assert result(backend).outcome is UpdateOutcome.AVAILABLE
        assert not installer.staged and not installer.installed
        backend.download()
        assert result(backend).outcome is UpdateOutcome.READY
        assert installer.staged and not installer.installed
        backend.install()
        assert installer.installed and not installer.handoff
        backend.complete_handoff()
        assert installer.handoff
    finally:
        backend.close()
    assert installer.closed


def test_persisted_history_rejects_rollback_across_backend_instances(
    tmp_path: Path,
) -> None:
    first = build(tmp_path, Transport(release("2.0.3", 43)), Installer())
    first.check()
    assert result(first).outcome is UpdateOutcome.AVAILABLE
    first.close()
    second = build(tmp_path, Transport(release()), Installer())
    second.check()
    response = result(second)
    assert response.outcome is UpdateOutcome.FAILED and "roll back" in response.detail
    assert json.loads((tmp_path / "history.json").read_text())["version"] == "2.0.3"
    second.close()


def test_expired_or_untrusted_release_never_stages_or_claims_current(
    tmp_path: Path,
) -> None:
    for data in (
        release(expires=datetime.now(UTC) - timedelta(seconds=1)),
        b'{"payload":"bad","signatures":[]}',
    ):
        installer = Installer()
        backend = build(tmp_path, Transport(data), installer)
        backend.check()
        assert result(backend).outcome is UpdateOutcome.FAILED
        assert not installer.staged and not installer.installed
        with pytest.raises(RuntimeError):
            backend.install()
        backend.close()


def test_no_trust_key_offers_only_a_manual_release_link(tmp_path: Path) -> None:
    transport = Transport(b'{"tag_name":"v2.0.2","draft":false,"prerelease":false}')
    backend = build(tmp_path, transport, Installer(), keys=())
    backend.check()
    response = result(backend)
    assert response.outcome is UpdateOutcome.MANUAL
    assert response.url == "https://github.com/TheRealSavi/iOpenPod/releases/tag/v2.0.2"
    assert transport.urls == [
        "https://api.github.com/repos/TheRealSavi/iOpenPod/releases/latest"
    ]
    with pytest.raises(RuntimeError):
        backend.install()
    backend.close()


def test_unsigned_mutable_tag_is_not_a_version(tmp_path: Path) -> None:
    backend = build(
        tmp_path,
        Transport(b'{"tag_name":"BETA","draft":false,"prerelease":false}'),
        None,
        keys=(),
    )
    backend.check()
    assert result(backend).outcome is UpdateOutcome.FAILED
    backend.close()
