"""Known retained-file edits preserve Sync associations transactionally."""

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest
from tests.iOpenPod.app.test_library_sync_helper import (
    _Fingerprinter,  # pyright: ignore[reportPrivateUsage]
    _library,  # pyright: ignore[reportPrivateUsage]
    _session,  # pyright: ignore[reportPrivateUsage]
    _write_media,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app import library_sync_helper as helper
from iOpenPod.app.library_sync_helper import (
    LIBRARY_SYNC_HELPER_PATH,
    IPodMediaScanner,
    LibrarySyncHelperError,
    SyncDetails,
    SyncedTrack,
    publish_sync_helper,
)
from storage import (
    DevicePath,
    FileContent,
    FilePreconditionError,
    RecoverableWriteError,
    StorageTransaction,
    TransactionProgress,
    TransactionState,
    TransactionWrite,
)


@pytest.mark.parametrize("acoustic", ["1,2,3", ""])
def test_retag_transaction_preserves_every_sync_detail(
    tmp_path: Path, acoustic: str
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    library = _library()
    track = library.tracks[0]
    path = DevicePath(track.metadata.location)
    details = SyncDetails(
        "2026-10-01",
        "Videos/episode.mkv",
        123,
        456,
        "mkv",
        "m4v",
        True,
        host_artwork_sha256="a" * 64,
        host_tag_sha256="b" * 64,
        stream_selection_sha256="c" * 64,
    )
    payload = b"audio-with-new-cover"
    with session:
        initial = publish_sync_helper(
            session,
            library,
            None,
            (SyncedTrack(path, acoustic, details),),
            library_sha256="a" * 64,
        )
        transaction = StorageTransaction(
            (
                TransactionWrite(
                    path,
                    payload,
                    FileContent(len(payload), hashlib.sha256(payload).hexdigest()),
                    session.fingerprint(path),
                ),
            )
        )
        updated_library = replace(
            library, tracks=(replace(track, title="Device edit", artwork_id=99),)
        )
        augmented = helper.retain_retagged_sync_details(
            session,
            transaction,
            library,
            updated_library,
            (track.track_id,),
            library_sha256="b" * 64,
        )
        assert len(augmented.writes) == 2
        assert augmented.writes[-1].path == LIBRARY_SYNC_HELPER_PATH
        assert augmented.writes[-1].expected == initial.helper_revision
        assert augmented.writes[0].modified_ns is not None
        committed = session.execute_transaction(augmented)
        fingerprinter = _Fingerprinter()
        fingerprinter.values = []
        scanned = IPodMediaScanner(fingerprinter).scan(
            session,
            updated_library,
            library_sha256="b" * 64,
            persist=False,
            checkpoint=lambda: None,
        )
        assert not fingerprinter.calls
        record = scanned.tracks[0]
        assert record.sync == initial.tracks[0].sync
        assert record.acoustic_fingerprint == acoustic
        assert record.size_bytes == len(payload)
        assert session.modified_time_matches(
            record.modified_ns, session.stat(path).modified_ns
        )
        session.restore_transaction(committed.recovery)
        assert session.read(path) == b"audio-one"
        restored = helper._load_helper(session)[0]  # pyright: ignore[reportPrivateUsage]
        assert restored.tracks == initial.tracks


@pytest.mark.parametrize("invalid", ["facts", "identity", "path", "unknown"])
def test_retag_never_claims_stale_or_unrelated_evidence(
    tmp_path: Path, invalid: str
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    library = _library()
    track = library.tracks[0]
    path = DevicePath(track.metadata.location)
    details = SyncDetails("2026-10-01", "song.flac", 123, 456, "flac", "mp3", True)
    with session:
        publish_sync_helper(
            session,
            library,
            None,
            (SyncedTrack(path, "1,2,3", details),),
            library_sha256="a" * 64,
        )
        if invalid == "facts":
            (root / str(path)).write_bytes(b"external changed media")
        elif invalid == "identity":
            assert track.ipod is not None
            track = replace(track, ipod=replace(track.ipod, db_track_id=99))
        updated = (
            replace(
                track, metadata=replace(track.metadata, location="iPod_Control/new")
            )
            if invalid == "path"
            else track
        )
        transaction = StorageTransaction(
            (
                TransactionWrite(
                    path,
                    b"new",
                    FileContent(3, hashlib.sha256(b"new").hexdigest()),
                    session.fingerprint(path),
                ),
            )
        )
        assert (
            helper.retain_retagged_sync_details(
                session,
                transaction,
                replace(library, tracks=(track,)),
                replace(library, tracks=(updated,)),
                () if invalid == "unknown" else (track.track_id,),
                library_sha256="b" * 64,
            )
            is transaction
        )


def test_invalid_helper_blocks_retag_and_remains_untouched(tmp_path: Path) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    library = _library()
    path = DevicePath(library.tracks[0].metadata.location)
    with session:
        session.atomic_write(LIBRARY_SYNC_HELPER_PATH, b"invalid", create_parents=True)
        transaction = StorageTransaction(
            (
                TransactionWrite(
                    path,
                    b"new",
                    FileContent(3, hashlib.sha256(b"new").hexdigest()),
                    session.fingerprint(path),
                ),
            )
        )
        with pytest.raises(LibrarySyncHelperError, match="invalid"):
            helper.retain_retagged_sync_details(
                session, transaction, library, library, (7,), library_sha256="b" * 64
            )
        assert session.read(LIBRARY_SYNC_HELPER_PATH) == b"invalid"
        assert session.read(path) == b"audio-one"


def test_missing_helper_does_not_create_sync_history(tmp_path: Path) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    library = _library()
    path = DevicePath(library.tracks[0].metadata.location)
    with session:
        transaction = StorageTransaction(
            (
                TransactionWrite(
                    path,
                    b"new",
                    FileContent(3, hashlib.sha256(b"new").hexdigest()),
                    session.fingerprint(path),
                ),
            )
        )
        assert (
            helper.retain_retagged_sync_details(
                session, transaction, library, library, (7,), library_sha256="b" * 64
            )
            is transaction
        )
        session.execute_transaction(transaction)
        assert not session.exists(LIBRARY_SYNC_HELPER_PATH)
        assert session.read(path) == b"new"


@pytest.mark.parametrize("failure", ["revision", "media", "helper"])
def test_retag_helper_is_guarded_and_recovers_with_media(
    tmp_path: Path, failure: str
) -> None:
    root, session = _session(tmp_path)
    _write_media(root)
    library = _library()
    path = DevicePath(library.tracks[0].metadata.location)
    details = SyncDetails("2026-10-01", "song.flac", 123, 456, "flac", "mp3", True)
    with session:
        publish_sync_helper(
            session,
            library,
            None,
            (SyncedTrack(path, "1,2,3", details),),
            library_sha256="a" * 64,
        )
        original_helper = session.read(LIBRARY_SYNC_HELPER_PATH)
        transaction = helper.retain_retagged_sync_details(
            session,
            StorageTransaction(
                (
                    TransactionWrite(
                        path,
                        b"new",
                        FileContent(3, hashlib.sha256(b"new").hexdigest()),
                        session.fingerprint(path),
                    ),
                )
            ),
            library,
            library,
            (7,),
            library_sha256="b" * 64,
        )
        if failure == "revision":
            session.atomic_write(
                LIBRARY_SYNC_HELPER_PATH,
                b"external helper",
                expected=session.fingerprint(LIBRARY_SYNC_HELPER_PATH),
            )
            with pytest.raises(FilePreconditionError):
                session.execute_transaction(transaction)
            assert session.read(path) == b"audio-one"
            assert session.read(LIBRARY_SYNC_HELPER_PATH) == b"external helper"
        else:

            def interrupt(event: TransactionProgress) -> None:
                if event.state is TransactionState.PUBLISHING and event.completed == (
                    1 if failure == "media" else 2
                ):
                    raise OSError("interrupted during retained media publication")

            with pytest.raises(RecoverableWriteError) as caught:
                session.execute_transaction(transaction, progress=interrupt)
            assert (session.read(LIBRARY_SYNC_HELPER_PATH) == original_helper) is (
                failure == "media"
            )
            recovery = session.inspect_transaction(
                DevicePath(caught.value.recovery_path)
            )
            session.restore_transaction(recovery)
            assert session.read(path) == b"audio-one"
            assert session.read(LIBRARY_SYNC_HELPER_PATH) == original_helper
