"""Application-owned device documents follow the Library's device safety rules."""

from collections.abc import Iterator
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_resources import Device, build_device

from iOpenPod.app.library_write import LibraryPreparationRequest, LibraryReview
from iOpenPod.app.models.device import ActiveIPod
from iOpenPod.app.services.device_coordinator import DeviceChangedError
from iPodDB.library import LibrarySnapshot, TrackFieldEdit, edit_track_metadata
from storage import (
    DevicePath,
    FileContent,
    FileFingerprint,
    FilePreconditionError,
    StorageError,
    TransactionWrite,
)

DOCUMENT = DevicePath("iPod_Control/iOpenPod/Integrations/application-document-v1.json")
DATABASE = "iPod_Control/iTunes/iTunesDB"
OUTSIDE_APPLICATION_ROOT = (
    "iPod_Control/iTunes/x.json",
    "iPod_Control/iOpenPod/Integrations",
    "iPod_Control/iOpenPod/settings-v2.json",
    "iPod_Control/iOpenPod/genius-mixes-v1.json",
    "iPod_Control/iOpenPodX/x.json",
)


@pytest.fixture
def device(tmp_path: Path) -> Iterator[Device]:
    fixture = build_device(tmp_path)
    try:
        yield fixture
    finally:
        fixture.coordinator.close()


def document_write(
    path: DevicePath, data: bytes, before: FileFingerprint | None = None
) -> TransactionWrite:
    return TransactionWrite(
        path, data, FileContent(len(data), sha256(data).hexdigest()), before
    )


def with_play_count(active: ActiveIPod, count: int) -> LibrarySnapshot:
    return replace(
        active.library,
        tracks=tuple(
            edit_track_metadata(track, (TrackFieldEdit("play_count", count),))
            if track.title == "Track 1"
            else track
            for track in active.library.tracks
        ),
    )


def play_count(active: ActiveIPod) -> int:
    return next(t.play_count for t in active.library.tracks if t.title == "Track 1")


def prepare(device: Device, count: int, *writes: TransactionWrite) -> LibraryReview:
    active = device.active
    return device.coordinator.prepare_library(
        LibraryPreparationRequest(with_play_count(active, count), active, 1, 1),
        lambda _: None,
        Event(),
        application_writes=writes,
    )


def save_ordinarily(device: Device, review: LibraryReview) -> ActiveIPod:
    saved = device.coordinator.save_library(
        review, device.active, lambda _: None, Event()
    )
    assert saved.active is not None, saved.issues
    return saved.active


def test_application_write_commits_with_the_library(device: Device) -> None:
    data = b'{"plays": 7}'
    review = prepare(device, 7, document_write(DOCUMENT, data))
    assert review.result.prepared is not None, review.result.issues
    assert (str(DOCUMENT), "write", len(data), sha256(data).hexdigest()) in {
        (c.path, c.action, c.size_bytes, c.sha256) for c in review.file_changes
    }
    assert not (device.root / str(DOCUMENT)).exists()

    saved = save_ordinarily(device, review)

    assert (device.root / str(DOCUMENT)).read_bytes() == data
    assert play_count(saved) == 7
    reloaded = device.coordinator.select_device(
        device.coordinator.discover_devices().candidates[0].id
    )
    assert play_count(reloaded) == 7


@pytest.mark.parametrize("path", OUTSIDE_APPLICATION_ROOT)
def test_application_write_outside_the_application_root_is_refused(
    device: Device, path: str
) -> None:
    review = prepare(device, 7, document_write(DevicePath(path), b"{}"))

    assert review.result.prepared is None
    assert (
        "resources.invalid_input",
        "Application documents must be under iPod_Control/iOpenPod/Integrations.",
    ) in {(i.code, i.detail) for i in review.result.issues}
    assert not review.file_changes
    saved = device.coordinator.save_library(
        review, device.active, lambda _: None, Event()
    )
    assert saved.active is None
    assert [issue.code for issue in saved.issues] == ["save.stale"]
    assert not (device.root / path).is_file()
    device.assert_original()


def test_stale_application_write_blocks_the_library_review(device: Device) -> None:
    first = device.coordinator.save_application_document(
        device.active, DOCUMENT, b"one", None
    )
    device.coordinator.save_application_document(device.active, DOCUMENT, b"two", first)

    review = prepare(device, 7, document_write(DOCUMENT, b"three", first))

    assert review.result.prepared is None
    assert any(
        i.code == "source.unavailable" and DOCUMENT.name in i.detail
        for i in review.result.issues
    ), review.result.issues
    assert (device.root / str(DOCUMENT)).read_bytes() == b"two"
    device.assert_original()


def test_load_application_document_reports_a_missing_document(
    device: Device,
) -> None:
    assert device.coordinator.load_application_document(
        device.active, DOCUMENT, 1024
    ) == (None, None)


def test_load_application_document_returns_bytes_and_revision(
    device: Device,
) -> None:
    data = b'{"loaded": true}'
    target = device.root / str(DOCUMENT)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)

    loaded, fingerprint = device.coordinator.load_application_document(
        device.active, DOCUMENT, len(data)
    )

    assert loaded == data
    assert fingerprint is not None
    assert (fingerprint.size, fingerprint.sha256) == (
        len(data),
        sha256(data).hexdigest(),
    )


def test_load_application_document_refuses_an_oversize_document(
    device: Device,
) -> None:
    data = b'{"too": "large"}'
    target = device.root / str(DOCUMENT)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)

    with pytest.raises(StorageError):
        device.coordinator.load_application_document(
            device.active, DOCUMENT, len(data) - 1
        )


def test_save_application_document_creates_then_replaces_the_read_revision(
    device: Device,
) -> None:
    created = device.coordinator.save_application_document(
        device.active, DOCUMENT, b"one", None
    )
    assert (device.root / str(DOCUMENT)).read_bytes() == b"one"
    data, before = device.coordinator.load_application_document(
        device.active, DOCUMENT, 1024
    )
    assert (data, before) == (b"one", created)
    assert before is not None

    replaced = device.coordinator.save_application_document(
        device.active, DOCUMENT, b"two", before
    )

    assert replaced != before
    assert replaced.sha256 == sha256(b"two").hexdigest()
    assert device.coordinator.load_application_document(
        device.active, DOCUMENT, 1024
    ) == (b"two", replaced)
    device.assert_original()


def test_create_only_save_refuses_an_existing_document(device: Device) -> None:
    device.coordinator.save_application_document(device.active, DOCUMENT, b"one", None)

    with pytest.raises(FilePreconditionError):
        device.coordinator.save_application_document(
            device.active, DOCUMENT, b"two", None
        )

    assert (device.root / str(DOCUMENT)).read_bytes() == b"one"


def test_save_application_document_rejects_a_stale_revision(device: Device) -> None:
    first = device.coordinator.save_application_document(
        device.active, DOCUMENT, b"one", None
    )
    device.coordinator.save_application_document(device.active, DOCUMENT, b"two", first)

    with pytest.raises(FilePreconditionError):
        device.coordinator.save_application_document(
            device.active, DOCUMENT, b"three", first
        )

    assert (device.root / str(DOCUMENT)).read_bytes() == b"two"


@pytest.mark.parametrize("path", OUTSIDE_APPLICATION_ROOT)
def test_application_document_paths_must_stay_under_the_application_root(
    device: Device, path: str
) -> None:
    with pytest.raises(ValueError, match="iPod_Control/iOpenPod"):
        device.coordinator.save_application_document(
            device.active, DevicePath(path), b"{}", None
        )
    with pytest.raises(ValueError, match="iPod_Control/iOpenPod"):
        device.coordinator.load_application_document(
            device.active, DevicePath(path), 1024
        )

    assert not (device.root / path).is_file()


def test_application_document_save_refuses_after_the_library_changed(
    device: Device,
) -> None:
    previous = device.active
    current = save_ordinarily(device, prepare(device, 3))

    with pytest.raises(DeviceChangedError):
        device.coordinator.save_application_document(previous, DOCUMENT, b"{}", None)
    with pytest.raises(DeviceChangedError):
        device.coordinator.load_application_document(previous, DOCUMENT, 1024)

    assert not (device.root / str(DOCUMENT)).exists()
    device.coordinator.save_application_document(current, DOCUMENT, b"{}", None)
    assert (device.root / str(DOCUMENT)).read_bytes() == b"{}"


def test_application_document_save_refuses_an_externally_changed_itunesdb(
    device: Device,
) -> None:
    database = device.root / DATABASE
    database.write_bytes(database.read_bytes() + b"\0")

    with pytest.raises(DeviceChangedError, match="iTunesDB changed"):
        device.coordinator.save_application_document(
            device.active, DOCUMENT, b"{}", None
        )

    assert not (device.root / str(DOCUMENT)).exists()


def test_unchanged_library_review_publishes_only_the_application_write(
    device: Device,
) -> None:
    active = device.active
    review = device.coordinator.prepare_library(
        LibraryPreparationRequest(active.library, active, 1, 1),
        lambda _: None,
        Event(),
        allow_unchanged=True,
        application_writes=(document_write(DOCUMENT, b"only"),),
    )
    assert review.result.prepared is not None, review.result.issues
    assert [(c.path, c.action) for c in review.file_changes] == [
        (str(DOCUMENT), "write")
    ]
    saved = device.save(review)
    assert saved.active is not None, saved.issues
    assert (device.root / str(DOCUMENT)).read_bytes() == b"only"

    device.restore(saved.recovery_path)

    assert not (device.root / str(DOCUMENT)).exists()


def test_restoring_the_library_removes_a_new_application_document(
    device: Device,
) -> None:
    review = prepare(device, 7, document_write(DOCUMENT, b"new"))
    assert review.result.prepared is not None, review.result.issues
    saved = device.save(review)
    assert saved.active is not None, saved.issues
    assert saved.recovery_path
    assert (device.root / str(DOCUMENT)).read_bytes() == b"new"

    device.restore(saved.recovery_path)

    assert not (device.root / str(DOCUMENT)).exists()


def test_restoring_the_library_returns_a_replaced_application_document(
    device: Device,
) -> None:
    before = device.coordinator.save_application_document(
        device.active, DOCUMENT, b"old", None
    )
    review = prepare(device, 7, document_write(DOCUMENT, b"new", before))
    assert review.result.prepared is not None, review.result.issues
    saved = device.save(review)
    assert saved.active is not None, saved.issues
    assert (device.root / str(DOCUMENT)).read_bytes() == b"new"

    device.restore(saved.recovery_path)

    assert (device.root / str(DOCUMENT)).read_bytes() == b"old"
