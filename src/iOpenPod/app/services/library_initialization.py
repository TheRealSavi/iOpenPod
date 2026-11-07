"""Create-only publication plans for a selected iPod with no Library database."""

from device_registry import DeviceProfile
from iOpenPod.app.services import library_resources
from iPodDB.library import WriteTarget, content_sha256, create_empty_library
from storage import (
    DeviceEntryKind,
    DevicePath,
    FileContent,
    FilePrecondition,
    FilesystemSession,
    StorageTransaction,
    TransactionWrite,
)

CONTROL = DevicePath("iPod_Control")
DIRECTORIES = tuple(
    CONTROL.joinpath(name) for name in ("Device", "iTunes", "Music", "Artwork")
)
DATABASES = (library_resources.ITUNESDB, library_resources.ITUNESCDB)


def available(session: FilesystemSession, *, compressed: bool) -> bool:
    """Inspect absence, never treating an empty or damaged primary as missing."""
    if (
        not session.exists(CONTROL)
        or session.stat(CONTROL).kind is not DeviceEntryKind.DIRECTORY
    ):
        return False
    for path in DATABASES:
        if not session.exists(path):
            continue
        entry = session.stat(path)
        # Late nano firmware keeps an empty iTunesDB compatibility file.
        if (
            compressed
            and path == library_resources.ITUNESDB
            and entry.kind is DeviceEntryKind.FILE
            and entry.size == 0
        ):
            continue
        return False
    return True


def prepare(
    session: FilesystemSession,
    profile: DeviceProfile,
    target: WriteTarget,
    device_name: str,
    dependencies: tuple[FilePrecondition, ...],
) -> StorageTransaction:
    """Validate the complete plan before creating even an empty directory."""
    if not available(session, compressed=target.compressed_database):
        raise ValueError("The iPod no longer has an absent Library database.")
    databases = tuple(
        FilePrecondition(
            path, session.fingerprint(path) if session.exists(path) else None
        )
        for path in DATABASES
    )
    if any(
        file.fingerprint is not None
        and not (
            target.compressed_database
            and file.path == library_resources.ITUNESDB
            and file.fingerprint.size == 0
        )
        for file in databases
    ):
        raise ValueError("A Library database appeared before initialization.")
    for path in DIRECTORIES:
        if (
            session.exists(path)
            and session.stat(path).kind is not DeviceEntryKind.DIRECTORY
        ):
            raise ValueError(f"The required iPod directory is not a directory: {path}")
    recheck(session)
    result = create_empty_library(
        device_name,
        target,
        supports_podcasts=profile.capabilities.audio.supports_podcasts,
        mac_formatted=session.mounted_volume.volume.filesystem_type.casefold().startswith(
            "hfs"
        ),
    )
    prepared = result.prepared
    if prepared is None:
        raise ValueError(" ".join(issue.message for issue in result.issues))
    primary = (
        library_resources.ITUNESCDB
        if target.compressed_database
        else library_resources.ITUNESDB
    )
    artifacts: list[tuple[DevicePath, bytes]] = []
    if prepared.sqlite is not None:
        artifacts.extend(
            (library_resources.sqlite_database_path(name), data)
            for name, data in prepared.sqlite.artifacts()
        )
    if target.compressed_database and databases[0].fingerprint is None:
        artifacts.append((library_resources.ITUNESDB, b""))
    # Publish the readable Library authority after every required companion.
    artifacts.append((primary, prepared.itunes))
    writes = tuple(
        TransactionWrite(path, data, FileContent(len(data), content_sha256(data)))
        for path, data in artifacts
    )
    written = {write.path for write in writes}
    unchanged_databases = tuple(file for file in databases if file.path not in written)
    transaction = StorageTransaction(
        writes, dependencies=(*dependencies, *unchanged_databases)
    )
    # Every write has expected=None: existing SQLite companions also block this
    # narrow initialization, rather than being replaced with an empty projection.
    session.validate_transaction(transaction)
    return transaction


def recheck(session: FilesystemSession) -> None:
    """Reject a removed marker or newly arrived playback evidence at checkpoints."""
    if session.stat(CONTROL).kind is not DeviceEntryKind.DIRECTORY:
        raise ValueError("The selected Volume no longer has an iPod_Control directory.")
    if session.exists(
        CONTROL.joinpath("iTunes")
    ) and library_resources.pending_sidecars(session):
        raise ValueError(
            "Playback Sidecars remain without their Library database. "
            "Restore the Library before loading this iPod."
        )
