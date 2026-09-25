"""A disconnected Sync can be recovered even when its current database cannot parse."""

import hashlib
from pathlib import Path

import pytest
from tests.iOpenPod.app.services.test_library_resources import build_device

from storage import (
    AccessMode,
    DevicePath,
    FileContent,
    RecoverableWriteError,
    StorageTransaction,
    TransactionProgress,
    TransactionState,
    TransactionWrite,
)


def test_recovery_rediscovers_device_without_loading_interrupted_database(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    database = DevicePath("iPod_Control/iTunes/iTunesDB")
    corrupt = b"interrupted Library publication"
    incoming = b"new media"
    with device.storage.open_session(
        device.storage.discover().volumes[0], access=AccessMode.READ_WRITE
    ) as session:
        transaction = StorageTransaction(
            (
                TransactionWrite(
                    database,
                    corrupt,
                    FileContent(len(corrupt), hashlib.sha256(corrupt).hexdigest()),
                    session.fingerprint(database),
                ),
                TransactionWrite(
                    DevicePath("iPod_Control/Music/F00/incoming.mp3"),
                    incoming,
                    FileContent(len(incoming), hashlib.sha256(incoming).hexdigest()),
                ),
            )
        )

        def disconnect(progress: TransactionProgress) -> None:
            if (
                progress.state is TransactionState.PUBLISHING
                and progress.completed == 1
            ):
                device.platform.disconnect(device.root)

        with pytest.raises(RecoverableWriteError) as failure:
            session.execute_transaction(transaction, progress=disconnect)

    journal = failure.value.recovery_path
    assert (device.root / str(database)).read_bytes() == corrupt
    device.coordinator.deactivate()
    device.platform.reconnect(device.root)
    recovered = device.coordinator.recover_sync_journal(journal)
    device.assert_original()
    assert recovered.library.tracks
    assert not (device.root / journal).exists()
    assert not (device.root / "iPod_Control/Music/F00/incoming.mp3").exists()
    device.coordinator.close()
