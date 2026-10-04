"""Release authentication and publication boundaries without network credentials."""

import base64
import hashlib
import json
import plistlib
import shutil
import subprocess
import tarfile
import urllib.error
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path
from threading import Event
from typing import cast
from xml.etree import ElementTree as ET

import pytest
from Crypto.Signature import eddsa
from scripts import package_updates, publish_update_feed, update_feed

from iOpenPod.app.updates import portable
from iOpenPod.app.updates.installation import Installation
from iOpenPod.app.updates.portable import unpack_linux, verify_linux_runtime
from iOpenPod.app.updates.releases import (
    TARGET_LAYOUTS,
    TARGET_SUFFIXES,
    verify_release,
)
from iOpenPod.app.updates.transport import DownloadAsset, UpdateTransport
from storage.host_installation import HostFileIdentity

SEED = bytes(range(32))  # Public test fixture, never a release credential.
PUBLIC = base64.b64encode(
    eddsa.import_private_key(SEED).public_key().export_key(format="raw")
).decode()
VERSION = "2.0.2"


@pytest.fixture
def release_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "packaging").mkdir()
    (tmp_path / "packaging/update-keys.json").write_text(
        json.dumps({"public_keys": [PUBLIC]})
    )
    for target, suffix in TARGET_SUFFIXES.items():
        identity = json.dumps(
            {
                "schema": 1,
                "product": "iOpenPod",
                "version": VERSION,
                "target": target,
                "layout": TARGET_LAYOUTS[target],
                "public_keys": [PUBLIC],
            }
        ).encode()
        path = tmp_path / f"iOpenPod-{VERSION}-{suffix}"
        if target.startswith("linux"):
            runtime = tmp_path / "dist/iOpenPod"
            (runtime / "_internal/updates").mkdir(parents=True)
            (runtime / "_internal/updates/installation.json").write_bytes(identity)
            (runtime / "_internal/library.so").write_bytes(b"runtime dependency")
            (runtime / "iOpenPod").write_bytes(b"linux executable")
            (tmp_path / "dist/iOpenPod-update").write_bytes(b"stable launcher")
            package_updates.managed_linux_archive(tmp_path, path, VERSION)
        else:
            with zipfile.ZipFile(path, "w") as archive:
                if target.startswith("macos"):
                    archive.writestr(
                        "iOpenPod.app/Contents/Resources/updates/installation.json",
                        identity,
                    )
                    archive.writestr(
                        "iOpenPod.app/Contents/Info.plist",
                        plistlib.dumps(
                            {"SUPublicEDKey": PUBLIC, "CFBundleVersion": VERSION}
                        ),
                    )
                    archive.writestr(
                        "iOpenPod.app/Contents/MacOS/iOpenPod", target.encode()
                    )
                else:
                    archive.writestr("iOpenPod.exe", b"windows executable")
    digest = update_feed.executable_digest

    def executable(path: Path, target: str, version: str, keys: tuple[str, ...]) -> str:
        if target.startswith("windows"):
            # The frozen CArchive is checked separately by native build validation.
            return hashlib.sha256(b"windows executable").hexdigest()
        return digest(path, target, version, keys)

    monkeypatch.setattr(update_feed, "executable_digest", executable)

    def sparkle_sdk(_root: Path) -> Path:
        return tmp_path / "sdk"

    monkeypatch.setattr(update_feed, "sparkle_sdk", sparkle_sdk)

    def signer(
        arguments: list[str], *, input: bytes, capture_output: bool, check: bool
    ) -> subprocess.CompletedProcess[bytes]:
        assert arguments[1:3] == ["--ed-key-file", "-"]
        assert input == base64.b64encode(SEED) + b"\n"
        assert capture_output and check and PUBLIC not in arguments
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(subprocess, "run", signer)
    return tmp_path


def test_feed_authenticates_every_archive_and_mac_appcast(release_files: Path) -> None:
    output = release_files / "feed"
    update_feed.create_feed(release_files, output, VERSION, SEED, root=release_files)
    release = verify_release((output / "stable.json").read_bytes(), (PUBLIC,))
    for target in TARGET_SUFFIXES:
        asset = release.asset(target)
        archive = release_files / asset.filename
        assert asset.size == archive.stat().st_size
        assert asset.sha256 == hashlib.sha256(archive.read_bytes()).hexdigest()
        if target.startswith("macos"):
            eddsa.new(
                eddsa.import_public_key(base64.b64decode(PUBLIC)), "rfc8032"
            ).verify(archive.read_bytes(), base64.b64decode(asset.sparkle_signature))
            enclosure = ET.parse(output / f"{target}.xml").find(
                "./channel/item/enclosure"
            )
            assert enclosure is not None and enclosure.get("url") == asset.url
            assert enclosure.get("length") == str(asset.size)


def test_expired_feed_can_be_renewed_without_rolling_back_history(
    release_files: Path,
) -> None:
    old_output = release_files / "old-feed"
    update_feed.create_feed(
        release_files,
        old_output,
        VERSION,
        SEED,
        root=release_files,
        now=datetime.now(UTC) - timedelta(days=60),
    )
    previous = (old_output / "stable.json").read_bytes()
    output = release_files / "new-feed"
    update_feed.create_feed(
        release_files, output, VERSION, SEED, root=release_files, previous=previous
    )
    release = verify_release((output / "stable.json").read_bytes(), (PUBLIC,))
    assert release.version == VERSION
    with pytest.raises(ValueError, match="rollback"):
        update_feed.create_feed(
            release_files,
            release_files / "rollback",
            "2.0.1",
            SEED,
            root=release_files,
            previous=previous,
        )
    with pytest.raises(ValueError, match="credential"):
        update_feed.create_feed(
            release_files,
            release_files / "wrong-key",
            VERSION,
            bytes(32),
            root=release_files,
        )


@pytest.mark.parametrize("change", ["dependency", "extra", "archive"])
def test_managed_linux_archive_detects_changes_before_running(
    release_files: Path, change: str
) -> None:
    output = release_files / "feed"
    update_feed.create_feed(release_files, output, VERSION, SEED, root=release_files)
    asset = verify_release((output / "stable.json").read_bytes(), (PUBLIC,)).asset(
        "linux-x86_64"
    )
    archive = release_files / asset.filename
    with tarfile.open(archive) as package:
        assert package.getmember("iOpenPod/iOpenPod").isfile()
        assert not any(entry.issym() or entry.islnk() for entry in package)
    destination = release_files / "staged"
    destination.mkdir()
    unpack_linux(archive, destination, asset)
    verify_linux_runtime(archive, destination, asset)
    if change == "dependency":
        (destination / "_internal/library.so").write_bytes(b"changed dependency")
    elif change == "extra":
        (destination / "injected.py").write_bytes(b"extra content")
    else:
        archive.write_bytes(b"changed archive")
    with pytest.raises(ValueError):
        verify_linux_runtime(archive, destination, asset)


def test_linux_staging_retry_reuses_only_a_complete_verified_version(
    release_files: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = release_files / "feed"
    update_feed.create_feed(release_files, output, VERSION, SEED, root=release_files)
    metadata = (output / "stable.json").read_bytes()
    asset = verify_release(metadata, (PUBLIC,)).asset("linux-x86_64")
    root = release_files / "managed"
    old = root / "versions/2.0.1/iOpenPod"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old executable")
    (root / "installation.json").write_text(
        json.dumps({"product": "iOpenPod", "layout": "linux-managed-v1"})
    )
    resources = release_files / "resources"
    (resources / "updates").mkdir(parents=True)
    (resources / "updates/iOpenPod-update").write_bytes(b"test helper")

    class LocalTransport(UpdateTransport):
        def download(
            self,
            asset: DownloadAsset,
            path: Path,
            cancel: Event,
            progress: Callable[[float], None],
        ) -> None:
            shutil.copyfile(release_files / asset.filename, path)

    def staged_operation(directory: Path, _keys: tuple[str, ...]) -> portable.Operation:
        # This staging test also runs on Windows; native helper entry tests own
        # the running-OS gate in read_operation.
        value = json.loads((directory / "operation.json").read_bytes())
        return portable.Operation(
            directory,
            root,
            old,
            value["nonce"],
            asset,
            HostFileIdentity.from_json(value["previous"]),
            HostFileIdentity.from_json(value["incoming"]),
            tuple(value["parents"]),
        )

    monkeypatch.setattr(portable, "read_operation", staged_operation)
    installation = Installation(
        "2.0.1", asset.target, asset.layout, (PUBLIC,), old, resources
    )
    for _attempt in range(2):
        installer = portable.PortableInstaller(installation)
        installer.stage(asset, metadata, LocalTransport(), Event(), lambda _p: None)
        installer.close()
    candidate = root / "versions/2.0.2"
    assert (candidate / "iOpenPod").read_bytes() == b"linux executable"
    assert old.read_bytes() == b"old executable"
    assert len(list(root.glob(".iopenpod-update-*"))) == 2
    library = candidate / "_internal/library.so"
    library.write_bytes(b"user changed this file")
    with pytest.raises(ValueError, match="changed"):
        portable.PortableInstaller(installation).stage(
            asset, metadata, LocalTransport(), Event(), lambda _p: None
        )
    assert library.read_bytes() == b"user changed this file"
    assert old.read_bytes() == b"old executable"


@pytest.mark.parametrize("conflict", [False, True])
def test_publisher_never_overwrites_a_concurrent_feed_commit(
    release_files: Path, monkeypatch: pytest.MonkeyPatch, conflict: bool
) -> None:
    entries: list[dict[str, object]] = []
    for suffix in TARGET_SUFFIXES.values():
        archive = release_files / f"iOpenPod-{VERSION}-{suffix}"
        entries.append(
            {
                "name": archive.name,
                "size": archive.stat().st_size,
                "digest": "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest(),
            }
        )
    old = release_files / "old"
    update_feed.create_feed(release_files, old, VERSION, SEED, root=release_files)
    previous = (old / "stable.json").read_bytes()
    mutations: list[tuple[str, dict[str, object], str | None]] = []

    def api(
        path: str, data: dict[str, object] | None = None, *, method: str | None = None
    ) -> dict[str, object]:
        if data is not None:
            mutations.append((path, data, method))
            if path == "git/refs/heads/update-feed" and conflict:
                raise urllib.error.HTTPError(
                    "https://api.github.com", 422, "Not a fast forward", Message(), None
                )
            return {"sha": "new-" + path.rsplit("/", 1)[-1]}
        if path.startswith("releases/"):
            return {
                "id": 10,
                "draft": False,
                "prerelease": False,
                "tag_name": "v" + VERSION,
                "assets": entries,
            }
        responses: dict[str, dict[str, object]] = {
            "git/ref/heads/update-feed": {"object": {"sha": "old-commit"}},
            "git/commits/old-commit": {"tree": {"sha": "old-tree"}},
            "git/trees/old-tree": {
                "tree": [{"path": "stable.json", "sha": "old-blob"}]
            },
            "git/blobs/old-blob": {"content": base64.b64encode(previous).decode()},
        }
        return responses[path]

    monkeypatch.setattr(publish_update_feed, "_api", api)
    monkeypatch.setattr(publish_update_feed, "ROOT", release_files)
    monkeypatch.setenv("IOPENPOD_UPDATE_PRIVATE_KEY", base64.b64encode(SEED).decode())
    if conflict:
        with pytest.raises(urllib.error.HTTPError):
            publish_update_feed.publish(
                VERSION, release_files, release_files / "publish"
            )
    else:
        assert (
            publish_update_feed.publish(
                VERSION, release_files, release_files / "publish"
            )
            == "new-commits"
        )
    commit = next(data for path, data, _ in mutations if path == "git/commits")
    assert commit["parents"] == ["old-commit"]
    assert mutations[-1] == (
        "git/refs/heads/update-feed",
        {"sha": "new-commits", "force": False},
        "PATCH",
    )
    tree = next(data for path, data, _ in mutations if path == "git/trees")
    assert {
        entry["path"] for entry in cast("list[dict[str, object]]", tree["tree"])
    } == {"stable.json", "macos-arm64.xml", "macos-x86_64.xml"}


@pytest.mark.parametrize("problem", ["draft", "old", "digest"])
def test_publisher_rejects_unpublished_stale_or_changed_assets(
    release_files: Path, monkeypatch: pytest.MonkeyPatch, problem: str
) -> None:
    calls: list[str] = []

    def api(
        path: str, data: dict[str, object] | None = None, *, method: str | None = None
    ) -> dict[str, object]:
        calls.append(path)
        assert data is None and method is None
        assert path.startswith("releases/")
        return {
            "id": 2 if problem == "old" and path == "releases/latest" else 1,
            "draft": problem == "draft",
            "prerelease": False,
            "tag_name": "v" + VERSION,
            "assets": [],
        }

    monkeypatch.setattr(publish_update_feed, "_api", api)
    with pytest.raises(ValueError):
        publish_update_feed.publish(VERSION, release_files, release_files / "rejected")
    assert calls and not (release_files / "rejected").exists()
