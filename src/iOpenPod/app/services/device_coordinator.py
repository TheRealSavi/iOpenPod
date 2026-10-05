"""Application coordination across Storage, Device Registry, and iPodDB."""

from __future__ import annotations

import contextlib
import logging
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, cast

from device_registry import (
    DEFAULT_DEVICE_REGISTRY,
    SYSINFO_AUTHORITY_FILENAME,
    ArtworkFormat,
    ArtworkPixelFormat,
    ArtworkUsage,
    DeviceEvidence,
    DeviceIdentifier,
    DeviceProfile,
    DeviceRegistry,
    EvidenceAuthority,
    IdentificationResult,
    IdentificationStatus,
    UsbIdentifier,
    authority_covers_metadata,
    parse_sysinfo,
    parse_sysinfo_extended,
    reconcile_device_metadata,
)
from iOpenPod.app.display_text import exception_text, source_text
from iOpenPod.app.library_sync_helper import (
    IPodMediaLibrary,
    IPodMediaScanner,
    IPodMediaScanProgress,
    LibrarySyncHelperCancelledError,
    SyncedImage,
    SyncedTrack,
    publish_sync_helper,
)
from iOpenPod.app.library_write import WriteProgress
from iOpenPod.app.models.artwork import ArtworkImage, ArtworkRequest
from iOpenPod.app.models.device import (
    ActiveIPod,
    DeviceCandidate,
    DeviceCandidateId,
    DeviceCandidateIssue,
    DeviceCandidateIssueCode,
    DeviceDiscovery,
    DeviceDiscoveryIssue,
    DeviceReadiness,
)
from iOpenPod.app.models.photos import (
    FULL_RESOLUTION_REQUEST_ID,
    PhotoImage,
    PhotoRequest,
)
from iOpenPod.app.playback.backend import PlaybackSourceError
from iOpenPod.app.podcasts.models import (
    PodcastIssue,
    PodcastIssueCode,
)
from iOpenPod.app.podcasts.store import LoadedPodcastState, PodcastDeviceStore
from iOpenPod.app.services import library_resources, volume_presentation
from iOpenPod.app.services.ipod_preferences import capture_ipod_preferences
from iOpenPod.app.services.linux_identity import UDEV_RULE_VERSION
from iPodDB.library import (
    CoverFormat,
    CoverPixelFormat,
    IPodLibrary,
    PhotoPixelFormat,
    PhotoRepresentationKind,
    PhotoThumbnailFormat,
)
from storage import (
    AccessMode,
    ConnectionGeneration,
    CopyResult,
    DeviceEntryKind,
    DevicePath,
    EjectResult,
    FileFingerprint,
    FileIdentity,
    FilePrecondition,
    FilesystemSession,
    HardwareProbeIssueCode,
    HardwareProbeResult,
    HostPath,
    MountedVolume,
    RecoverableWriteError,
    ScsiVpdPagePlan,
    Storage,
    StorageCapacityError,
    StorageError,
    StorageTransaction,
    TransactionActivity,
    TransactionActivityPhase,
    TransactionDurabilityPendingError,
    TransactionProgress,
    TransactionState,
    VolumeId,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

    from iOpenPod.app.backups.models import BackupDeviceContext
    from iOpenPod.app.library_write import (
        LibraryPreparationRequest,
        LibraryReview,
        LibrarySaveResult,
    )
    from iOpenPod.app.playback.backend import PlaybackSource
    from iPodDB.library import Hash72Material, LibraryWritePlan, Photo, PhotoRead, Track

logger = logging.getLogger(__name__)

_SYSINFO_PATH = DevicePath("iPod_Control/Device/SysInfo")
_SYSINFO_EXTENDED_PATH = DevicePath("iPod_Control/Device/SysInfoExtended")
_SYSINFO_AUTHORITY_PATH = DevicePath(
    f"iPod_Control/Device/{SYSINFO_AUTHORITY_FILENAME}"
)
_IPOD_CONTROL_PATH = DevicePath("iPod_Control")
_ITUNESDB_PATH = DevicePath("iPod_Control/iTunes/iTunesDB")
_ITUNESCDB_PATH = DevicePath("iPod_Control/iTunes/iTunesCDB")
_HASHINFO_PATH = DevicePath("iPod_Control/Device/HashInfo")
_ARTWORKDB_PATH = DevicePath("iPod_Control/Artwork/ArtworkDB")
_ARTWORK_DIRECTORY = DevicePath("iPod_Control/Artwork")
_PHOTOSDB_PATH = DevicePath("Photos/Photo Database")
_PHOTOS_DIRECTORY = DevicePath("Photos")
_DEVICE_METADATA_LIMIT = 1024 * 1024
_ARTWORK_DATABASE_LIMIT = 128 * 1024 * 1024
_PHOTOS_DATABASE_LIMIT = 128 * 1024 * 1024
_ARTWORK_PAYLOAD_LIMIT = 32 * 1024 * 1024
_PHOTO_PAYLOAD_LIMIT = 32 * 1024 * 1024
_TRANSACTION_CLEANUP_ISSUE_CODES = {
    DeviceCandidateIssueCode.TRANSACTION_CLEANUP_PENDING,
    DeviceCandidateIssueCode.TRANSACTION_CLEANUP_FLUSH_PENDING,
}
_IPOD_SYSINFO_VPD_PLAN = ScsiVpdPagePlan(
    index_page=0xC0,
    first_data_page=0xC2,
    last_data_page=0xFF,
    scan_range_when_index_empty=True,
)
_DISPLAY_ONLY_F1060 = ArtworkFormat(
    format_id=1060,
    width=320,
    height=320,
    row_bytes=640,
    pixel_format=ArtworkPixelFormat.RGB565_LE,
    usage=ArtworkUsage.COVER,
)


class DeviceCoordinationError(Exception):
    """Base class for device-workflow failures reported by iOpenPod."""


class DeviceCandidateNotFoundError(DeviceCoordinationError):
    """The requested candidate is no longer in the latest discovery snapshot."""


class DeviceNotSelectableError(DeviceCoordinationError):
    """The requested candidate cannot safely become the Active iPod."""


class DeviceChangedError(DeviceCoordinationError):
    """Identity or database content changed while selection was in progress."""


class DeviceAccessError(DeviceCoordinationError):
    """Storage could not safely access the selected Volume."""


class SyncRecoveryRequiredError(DeviceCoordinationError):
    """An interrupted transaction needs the user's restore-or-keep decision."""

    def __init__(self, recovery_path: str) -> None:
        self.recovery_path = recovery_path
        super().__init__(
            source_text(
                "An interrupted transaction is still present on this iPod. Restore it "
                "or choose Keep Current Contents before another Sync: {path}",
                path=recovery_path,
            )
        )


class SyncRecoveryDeclinedError(DeviceCoordinationError):
    """Recovery was declined, but reloading or flushing needs user attention."""


class SyncRecoveryRestoredError(DeviceCoordinationError):
    """Restoration and cleanup succeeded, but the Library needs manual reloading."""


class SyncCleanupCompletedError(DeviceCoordinationError):
    """Recovery files were removed, but final flush needs safe device ejection."""


class SyncRestoredCleanupPendingError(DeviceCoordinationError):
    """The original files verified; only recovery namespace cleanup remains."""


class DeviceEjectError(DeviceCoordinationError):
    """The Host did not confirm safe removal of the Active iPod."""


class DeviceLibraryLoadError(DeviceCoordinationError):
    """The selected Library could not be parsed or its sidecars committed."""


class DeviceArtworkLoadError(DeviceCoordinationError):
    """Artwork metadata or pixels could not be read and decoded safely."""


class DevicePhotoLoadError(DeviceCoordinationError):
    """Photo metadata or thumbnail pixels could not be read and decoded safely."""


class DeviceTrackExportError(DeviceCoordinationError):
    """A Track could not be safely read from the Active iPod for export."""


class DevicePhotoExportError(DeviceCoordinationError):
    """A Photo could not be safely read from the Active iPod for export."""


@dataclass(frozen=True, slots=True)
class _CandidateRecord:
    mounted_volume: MountedVolume
    candidate: DeviceCandidate
    database_path: DevicePath | None
    hardware_evidence: DeviceEvidence = field(default_factory=DeviceEvidence)
    device_evidence: DeviceEvidence = field(default_factory=DeviceEvidence)
    live_sysinfo_extended: bytes = b""
    persistent_issues: tuple[DeviceCandidateIssue, ...] = ()


@dataclass(slots=True)
class _ActiveConnection:
    session: FilesystemSession
    record: _CandidateRecord
    active_ipod: ActiveIPod
    library_source: IPodLibrary
    time_precondition: FilePrecondition | None = None
    sidecar_preconditions: tuple[FilePrecondition, ...] = ()


@dataclass(frozen=True, slots=True)
class _VolumePresentationPolicy:
    enabled: bool


@dataclass(frozen=True, slots=True)
class _PreparedLibraryWrite:
    review: LibraryReview
    transaction: StorageTransaction
    presentation_policy: _VolumePresentationPolicy
    temporary_files: contextlib.ExitStack


@dataclass(frozen=True, slots=True)
class _DevicePlaybackSource:
    reader: Callable[[int, int], bytes]
    byte_count: int
    file_name: str

    def read_at(self, offset: int, length: int) -> bytes:
        if offset < 0 or length < 0:
            raise ValueError("Playback Source offsets and lengths must be non-negative")
        if offset >= self.byte_count or length == 0:
            return b""
        return self.reader(
            offset,
            min(length, self.byte_count - offset),
        )


@dataclass(frozen=True, slots=True)
class _IthmbByteCacheKey:
    generation: ConnectionGeneration
    path: DevicePath
    identity: FileIdentity
    offset: int
    length: int


class DeviceCoordinator:
    """Own one Active iPod while hiding all filesystem mechanics from the GUI.

    This is the deep Application Layer seam.  Discovery and selection both
    revalidate a Storage Connection Generation, Device Registry is only given
    already-read evidence, and iPodDB is only given already-read bytes.
    """

    def __init__(
        self,
        storage: Storage,
        registry: DeviceRegistry = DEFAULT_DEVICE_REGISTRY,
        library_loader: Callable[[bytes], IPodLibrary] = IPodLibrary.parse,
        *,
        ithmb_cache_byte_limit: int = 16 * 1024 * 1024,
        ipod_media_scanner: IPodMediaScanner | None = None,
        volume_presentation_enabled: bool = True,
    ) -> None:
        if ithmb_cache_byte_limit <= 0:
            raise ValueError("The iTHMB byte-cache limit must be positive")
        self._storage = storage
        self._registry = registry
        self._library_loader = library_loader
        self._records: dict[DeviceCandidateId, _CandidateRecord] = {}
        self._discovery = DeviceDiscovery(candidates=())
        self._discovery_volumes: dict[DeviceCandidateId, MountedVolume] = {}
        self._active: _ActiveConnection | None = None
        self._prepared_for_save: _PreparedLibraryWrite | None = None
        self._preparation_generation = 0
        self._lock = threading.RLock()
        self._presentation_policy_lock = threading.Lock()
        self._presentation_policy = _VolumePresentationPolicy(
            volume_presentation_enabled
        )
        self._ithmb_cache_byte_limit = ithmb_cache_byte_limit
        self._ithmb_cache_bytes = 0
        self._ithmb_bytes: OrderedDict[_IthmbByteCacheKey, bytes] = OrderedDict()
        self._podcast_store = PodcastDeviceStore()
        self._ipod_media_scanner = ipod_media_scanner or IPodMediaScanner()
        self._recovery_observations: dict[
            str, tuple[MountedVolume, FileFingerprint]
        ] = {}
        self._sync_cleanup_path = ""

    @property
    def volume_presentation_enabled(self) -> bool:
        return self._current_presentation_policy().enabled

    def _current_presentation_policy(self) -> _VolumePresentationPolicy:
        with self._presentation_policy_lock:
            return self._presentation_policy

    def set_volume_presentation_enabled(self, enabled: bool) -> None:
        """Retire older policies without making the GUI wait for device I/O."""
        with self._presentation_policy_lock:
            if self._presentation_policy.enabled != enabled:
                self._presentation_policy = _VolumePresentationPolicy(enabled)

    @property
    def sync_cleanup_path(self) -> str:
        """Terminal cleanup found while selecting the current iPod."""
        with self._lock:
            return self._sync_cleanup_path

    def _check_sync_recovery(self, session: FilesystemSession) -> str:
        journals = self._terminal_sync_journals(session)
        return str(journals[0][0]) if journals else ""

    def _terminal_sync_journals(
        self, session: FilesystemSession
    ) -> tuple[tuple[DevicePath, TransactionState], ...]:
        try:
            return _terminal_transaction_journals(session)
        except SyncRecoveryRequiredError as error:
            self._recovery_observations[error.recovery_path] = (
                session.mounted_volume,
                session.fingerprint(DevicePath(error.recovery_path)),
            )
            raise

    @property
    def discovery(self) -> DeviceDiscovery:
        with self._lock:
            return self._discovery

    @property
    def active_ipod(self) -> ActiveIPod | None:
        with self._lock:
            return self._active.active_ipod if self._active is not None else None

    @property
    def active_volume_id(self) -> VolumeId | None:
        """Return the stable Volume Identity for the Active iPod, when loaded."""

        with self._lock:
            if self._active is None:
                return None
            return self._active.record.mounted_volume.volume.id

    def scrobble_context(self, expected: ActiveIPod) -> tuple[str, Callable[[], None]]:
        """Capture stable receipt identity and checks for read-only scrobbling."""
        with self._lock:
            active = self._active
            if active is None or active.active_ipod is not expected:
                raise DeviceChangedError("The Active iPod changed before scrobbling.")
            session = active.session
            identity = active.record.mounted_volume.volume.id.value
        database_path = library_resources.database_path(expected.database_name)

        def checkpoint() -> None:
            with self._lock:
                if self._active is not active or active.active_ipod is not expected:
                    raise DeviceChangedError(
                        "The Active iPod changed during scrobbling."
                    )
            # Storage revalidates the actual connection, including unplugging.
            session.stat(database_path)

        checkpoint()
        if session.fingerprint(database_path) != expected.database_fingerprint:
            raise DeviceChangedError(
                "The iPod Library changed. Reload before scrobbling."
            )
        return identity, checkpoint

    def scan_ipod_media(
        self,
        expected: ActiveIPod,
        progress: Callable[[IPodMediaScanProgress], None],
        cancelled: threading.Event,
    ) -> IPodMediaLibrary:
        """Scan the current iPod files and safely refresh its Sync helper."""

        def checkpoint() -> None:
            if cancelled.is_set():
                raise LibrarySyncHelperCancelledError

        with self._lock:
            active = self._active
            if active is None or active.active_ipod is not expected:
                raise DeviceChangedError(
                    "The Active iPod changed before its media scan began."
                )
            mounted = active.record.mounted_volume
            # A pre-Review scan supplies evidence only. Sync publishes its helper
            # after the Library transaction has been verified successfully.
            persist = False
            active_session = active.session

        managed_session = (
            self._storage.open_session(mounted, access=AccessMode.READ_WRITE)
            if persist
            else contextlib.nullcontext(active_session)
        )
        database_path = library_resources.database_path(expected.database_name)

        def validate_source() -> None:
            checkpoint()
            with self._lock:
                if self._active is not active or not active_session.is_active:
                    raise DeviceChangedError(
                        "The Active iPod disconnected or changed during its media scan."
                    )
            if session.fingerprint(database_path) != expected.database_fingerprint:
                raise DeviceChangedError(
                    "The iPod Library changed during its media scan. Reload and try again."
                )

        with managed_session as session:
            validate_source()
            result = self._ipod_media_scanner.scan(
                session,
                expected.library,
                library_sha256=expected.database_fingerprint.sha256,
                persist=persist,
                checkpoint=checkpoint,
                progress=progress,
                validate_source=validate_source,
                report_read_only=not mounted.volume.capabilities.safe_for_writes,
            )
            validate_source()
        return result

    @contextlib.contextmanager
    def sync_session(
        self, expected: ActiveIPod, *, access: AccessMode = AccessMode.READ_ONLY
    ) -> Generator[FilesystemSession]:
        """Bind Sync checks and helper publication to one exact selected Library."""

        with self._lock:
            active = self._active
            if active is None or active.active_ipod is not expected:
                raise DeviceChangedError("The Active iPod changed. Rescan before Sync.")
            mounted = active.record.mounted_volume
            if not mounted.volume.capabilities.safe_for_writes:
                raise DeviceAccessError(
                    "The iPod is not safely writable. Reconnect on a writable volume."
                )
        with self._storage.open_session(mounted, access=access) as session:

            def validate() -> None:
                with self._lock:
                    if self._active is not active or active.active_ipod is not expected:
                        raise DeviceChangedError("The Active iPod changed during Sync.")
                if (
                    not active.session.is_active
                    or session.fingerprint(
                        library_resources.database_path(expected.database_name)
                    )
                    != expected.database_fingerprint
                ):
                    raise DeviceChangedError(
                        "The iPod Library changed. Reload and review Sync again."
                    )

            validate()
            self._check_sync_recovery(session)
            yield session
            validate()

    def publish_sync_success(
        self,
        expected: ActiveIPod,
        previous: IPodMediaLibrary | None,
        tracks: tuple[SyncedTrack, ...],
        images: tuple[SyncedImage, ...] = (),
    ) -> IPodMediaLibrary:
        """Refresh the non-authoritative helper after a verified Library commit."""

        with self.sync_session(expected, access=AccessMode.READ_WRITE) as session:
            return publish_sync_helper(
                session,
                expected.library,
                previous,
                tracks,
                images,
                library_sha256=expected.database_fingerprint.sha256,
            )

    def finalize_sync_success(self, expected: ActiveIPod, recovery_path: str) -> None:
        """Remove recovery payloads only after the committed Library was verified."""

        with self.sync_session(expected, access=AccessMode.READ_WRITE) as session:
            _finalize_committed_transaction(session, DevicePath(recovery_path))

    def recover_failed_sync(
        self,
        expected: ActiveIPod,
        recovery_path: str,
        progress: Callable[[WriteProgress], None] | None = None,
    ) -> None:
        """Restore and clean a failed Sync while its selected device remains bound.

        Storage validates observed publication state before restoring any file. A
        disconnect or conflicting external change retains the journal for recovery.
        """

        with self._lock:
            active = self._active
            if (
                active is None
                or active.active_ipod is not expected
                or not active.session.is_active
            ):
                raise DeviceChangedError(
                    "Reconnect the same iPod to recover the interrupted Sync."
                )
            mounted = active.record.mounted_volume
        with self._storage.open_session(
            mounted, access=AccessMode.READ_WRITE
        ) as session:

            def activity(event: TransactionActivity) -> None:
                if progress is not None:
                    progress(_transaction_activity_progress(event, recovery=True))

            def restoring(event: TransactionProgress) -> None:
                if progress is not None:
                    progress(
                        WriteProgress(
                            "save.recovery.restoring",
                            "Restoring the previous Library. Keep the iPod connected.",
                            completed=event.completed,
                            total=event.total,
                            current_item=str(event.path or ""),
                            unit="files",
                        )
                    )

            recovery = session.inspect_transaction(
                DevicePath(recovery_path), activity=activity
            )
            restored = session.restore_transaction(
                recovery, progress=restoring, activity=activity
            )
            if progress is not None:
                progress(
                    WriteProgress(
                        "save.recovery.cleanup",
                        "Previous Library restored. Removing recovery files…",
                    )
                )
            try:
                flushed = session.finalize_transaction(restored.recovery)
            except TransactionDurabilityPendingError as error:
                _raise_if_cleanup_completed(session, recovery.journal_path, error)
                raise SyncRestoredCleanupPendingError(str(error)) from error
            except StorageError as error:
                raise SyncRestoredCleanupPendingError(str(error)) from error
            if not flushed.complete:
                raise SyncCleanupCompletedError(
                    source_text(
                        "The previous Library was restored and Sync recovery files were removed. "
                        "Safely eject before unplugging; device flushing could not be confirmed. {detail}",
                        detail=flushed.detail,
                    )
                )

    def recover_sync_journal(self, recovery_path: str) -> ActiveIPod:
        """Reconnect to the exact journal's device and restore before loading it.

        A partially published database need not be loadable for recovery. Storage
        validates the journal's Physical Device and Volume identities, and every
        observed file, before it grants restoration authority.
        """
        path = DevicePath(recovery_path)
        with self._lock:
            volumes = self._storage.discover().volumes
            matches: list[MountedVolume] = []
            for mounted in volumes:
                if not mounted.volume.capabilities.safe_for_writes:
                    continue
                with self._storage.open_session(mounted) as session:
                    if session.exists(path):
                        session.read_transaction_state(path)
                        matches.append(mounted)
            if len(matches) != 1:
                raise DeviceChangedError(
                    "Reconnect the same writable iPod. Its recovery journal must "
                    "be present on exactly one connected volume."
                )
            mounted = matches[0]
            with self._storage.open_session(
                mounted, access=AccessMode.READ_WRITE
            ) as session:
                # A previous restoration may have succeeded before cleanup failed.
                # Its verified terminal state needs cleanup, not another rollback.
                try:
                    if (
                        session.read_transaction_state(path)
                        is TransactionState.RESTORED
                    ):
                        flushed = session.finalize_restored_transaction(path)
                    else:
                        recovery = session.inspect_transaction(path)
                        restored = session.restore_transaction(recovery)
                        flushed = session.finalize_transaction(restored.recovery)
                except TransactionDurabilityPendingError as error:
                    try:
                        _raise_if_cleanup_completed(session, path, error)
                    except SyncCleanupCompletedError as completed:
                        self._deactivate_locked()
                        raise SyncRecoveryRestoredError(
                            source_text(
                                "The previous Library was restored. Sync recovery files were removed, "
                                "but device flushing could not be confirmed. Safely eject before unplugging. {detail}",
                                detail=str(error),
                            )
                        ) from completed
                    raise SyncRestoredCleanupPendingError(str(error)) from error
                except StorageError as error:
                    # Cleanup only runs after a verified RESTORED state above.
                    # Failures during inspection/restoration must keep their own
                    # recovery diagnosis, so confirm the journal before classifying.
                    if (
                        session.read_transaction_state(path)
                        is TransactionState.RESTORED
                    ):
                        raise SyncRestoredCleanupPendingError(str(error)) from error
                    raise
                if not flushed.complete:
                    self._deactivate_locked()
                    raise SyncRecoveryRestoredError(
                        source_text(
                            "The previous Library was restored and Sync recovery files were removed. "
                            "Safely eject before unplugging; device flushing could not be confirmed. {detail}",
                            detail=flushed.detail,
                        )
                    )
            self._deactivate_locked()
            try:
                self.discover_devices()
                candidate = self.candidate_id_for_volume(mounted.volume.id)
                if candidate is None:
                    raise DeviceChangedError("The restored iPod is not ready to load.")
                return self.select_device(candidate, reconcile_sidecars=False)
            except SyncRecoveryRequiredError:
                # A different pending transaction remains actionable on its own.
                raise
            except Exception as error:
                raise SyncRecoveryRestoredError(
                    source_text(
                        "The previous Library was restored and temporary files were cleaned up. "
                        "The iPod could not be reloaded. Refresh the Device Picker and select it again. {detail}",
                        detail=str(error),
                    )
                ) from error

    def keep_sync_contents(self, recovery_path: str) -> ActiveIPod:
        """Retire one journal without restoring or deleting any Library files.

        The journal is renamed beside its retained payloads. Its original bytes
        remain available for manual diagnosis, but discovery no longer treats it
        as an unresolved operation. This does not certify a successful Sync.
        """
        path = DevicePath(recovery_path)
        if (
            re.fullmatch(
                r"\.iopenpod-recovery/[0-9a-f]{32}/transaction\.json", str(path)
            )
            is None
        ):
            raise DeviceAccessError("The Sync recovery journal path is invalid.")
        namespace = path.parent
        assert namespace is not None
        retired = namespace.joinpath("declined-transaction.json")
        with self._lock:
            observed = self._recovery_observations.get(recovery_path)
            matches: list[tuple[MountedVolume, FileFingerprint | None]] = []
            for mounted in self._storage.discover().volumes:
                if not mounted.volume.capabilities.safe_for_writes:
                    continue
                if observed is not None and (
                    mounted.physical_device.id != observed[0].physical_device.id
                    or mounted.volume.id != observed[0].volume.id
                ):
                    continue
                with self._storage.open_session(mounted) as session:
                    if observed is not None:
                        # A corrupt journal can be declined because its location
                        # and bytes were observed on this exact Physical Device.
                        matches.append(
                            (mounted, observed[1] if session.exists(path) else None)
                        )
                    elif session.exists(path):
                        # Results from this run may precede discovery. Validate
                        # their journal identity before accepting a path alone.
                        session.read_transaction_state(path)
                        matches.append((mounted, session.fingerprint(path)))
            if len(matches) != 1:
                raise DeviceChangedError(
                    "Reconnect the same writable iPod before keeping its current contents."
                )
            mounted, expected = matches[0]
            if expected is not None:
                self._recovery_observations[recovery_path] = (mounted, expected)
            with self._storage.open_session(
                mounted, access=AccessMode.READ_WRITE
            ) as session:
                if expected is not None:
                    session.move(path, retired, expected_source=expected)
                flushed = session.flush()
            self._recovery_observations.pop(recovery_path, None)
            self._deactivate_locked()
            if not flushed.complete:
                raise SyncRecoveryDeclinedError(
                    source_text(
                        "Current contents were kept and recovery was declined. "
                        "Safely eject before unplugging; device flushing could not be confirmed. {detail}",
                        detail=flushed.detail,
                    )
                )
            try:
                self.discover_devices()
                candidate = self.candidate_id_for_volume(mounted.volume.id)
                if candidate is None:
                    raise DeviceChangedError("The iPod is not ready to load.")
                return self.select_device(
                    candidate, reconcile_metadata=False, reconcile_sidecars=False
                )
            except SyncRecoveryRequiredError:
                raise
            except Exception as error:
                raise SyncRecoveryDeclinedError(
                    source_text(
                        "Current contents were kept and recovery was declined. "
                        "The current Library could not be loaded; the interrupted Sync may "
                        "be incomplete. Recovery copies remain beside declined-transaction.json. "
                        "Refresh the Device Picker after repairing the Library. {detail}",
                        detail=str(error),
                    )
                ) from error

    def cleanup_sync_journal(self, recovery_path: str) -> None:
        """Retry terminal transaction cleanup without restoring the previous Library."""
        path = DevicePath(recovery_path)
        if (
            re.fullmatch(
                r"\.iopenpod-recovery/[0-9a-f]{32}/transaction\.json", str(path)
            )
            is None
        ):
            raise DeviceAccessError("The Sync cleanup journal path is invalid.")
        namespace = path.parent
        assert namespace is not None
        with self._lock:
            matches: list[MountedVolume] = []
            for mounted in self._storage.discover().volumes:
                if not mounted.volume.capabilities.safe_for_writes:
                    continue
                with self._storage.open_session(mounted) as session:
                    if session.exists(path):
                        state = session.read_transaction_state(path)
                        if state not in (
                            TransactionState.COMMITTED,
                            TransactionState.RESTORED,
                        ):
                            raise SyncRecoveryRequiredError(str(path))
                        matches.append(mounted)
                    elif session.exists(namespace):
                        # Storage only removes an empty namespace without its journal.
                        matches.append(mounted)
            if not matches:
                raise DeviceChangedError(
                    "Reconnect the original iPod and retry cleanup. Its Sync cleanup "
                    "journal is not present on a connected writable volume."
                )
            if len(matches) != 1:
                raise DeviceChangedError(
                    "The Sync cleanup journal was found on more than one connected "
                    "volume. Connect only its original iPod and retry cleanup."
                )
            with self._storage.open_session(
                matches[0], access=AccessMode.READ_WRITE
            ) as session:
                try:
                    if not session.exists(path):
                        flushed = session.finalize_missing_transaction(path)
                    elif (
                        session.read_transaction_state(path)
                        is TransactionState.COMMITTED
                    ):
                        flushed = session.finalize_committed_transaction(path)
                    else:
                        flushed = session.finalize_restored_transaction(path)
                except TransactionDurabilityPendingError as error:
                    _raise_if_cleanup_completed(session, path, error)
                    raise
                if not flushed.complete:
                    raise SyncCleanupCompletedError(
                        source_text(
                            "Sync recovery files were removed, but device flushing could not be "
                            "confirmed. Safely eject before unplugging. {detail}",
                            detail=flushed.detail,
                        )
                    )

    def backup_device_context(self) -> BackupDeviceContext | None:
        """Describe the Active iPod for archive association without a Host path."""

        with self._lock:
            return (
                _backup_device_context(self._active)
                if self._active is not None
                else None
            )

    def require_backup_host_paths(self, *paths: Path) -> None:
        """Require backup Host paths to be outside the Active iPod's disk."""

        with self._lock:
            active = self._active
            if active is None:
                return
            for path in paths:
                try:
                    self._storage.require_host_path_off_physical_device(
                        HostPath(path),
                        active.record.mounted_volume,
                    )
                except StorageError as error:
                    raise DeviceAccessError(
                        source_text(
                            "A selected backup path could not be proven to be on another Physical Device: {detail}",
                            detail=str(error),
                        )
                    ) from error

    @contextlib.contextmanager
    def backup_session(
        self,
        expected: ActiveIPod,
        backup_root: Path,
        *,
        access: AccessMode,
    ) -> Generator[tuple[BackupDeviceContext, FilesystemSession]]:
        """Bind one backup operation to the exact Active iPod connection."""

        with self._lock:
            active = self._active
            if active is None or active.active_ipod is not expected:
                raise DeviceChangedError(
                    "The Active iPod changed before the backup operation began."
                )
            try:
                self._storage.require_host_path_off_physical_device(
                    HostPath(backup_root),
                    active.record.mounted_volume,
                )
            except StorageError as error:
                raise DeviceAccessError(
                    source_text(
                        "The backup location could not be proven to be on another Physical Device: {detail}",
                        detail=str(error),
                    )
                ) from error
            context = _backup_device_context(active)

        if access is AccessMode.READ_ONLY:
            # Capture retains the identity-bound session, but must not retain the
            # coordinator lock. Playback, artwork, and other foreground reads
            # acquire that lock briefly to validate the same Active iPod.
            yield context, active.session
            return

        with self._lock:
            if self._active is not active or not active.session.is_active:
                raise DeviceChangedError(
                    "The Active iPod changed before restore write access opened."
                )
            with self._storage.open_session(
                active.record.mounted_volume,
                access=AccessMode.READ_WRITE,
            ) as session:
                if self._active is not active or not active.session.is_active:
                    raise DeviceChangedError(
                        "The Active iPod changed before restore write access opened."
                    )
                yield context, session

    def candidate_id_for_volume(self, volume_id: VolumeId) -> DeviceCandidateId | None:
        """Resolve one ready candidate by stable Volume Identity.

        Duplicate Volume Identities fail closed instead of choosing an arbitrary
        currently connected candidate.
        """

        with self._lock:
            matches = tuple(
                record.candidate.id
                for record in self._records.values()
                if record.mounted_volume.volume.id == volume_id
                and record.candidate.selectable
            )
        return matches[0] if len(matches) == 1 else None

    def load_podcast_state(self, expected: ActiveIPod) -> LoadedPodcastState:
        """Load, reconcile, and when safe persist Podcast state for this Library."""

        with self._lock:
            active = self._active
            if active is None or active.active_ipod is not expected:
                raise DeviceChangedError(
                    "The Active iPod changed before Podcast state could be loaded."
                )
            writable = active.record.mounted_volume.volume.capabilities.safe_for_writes
            loaded = self._podcast_store.load(
                active.session,
                expected.library.tracks,
                writable=writable,
            )
            if not loaded.requires_persistence:
                return loaded
            try:
                return self._save_podcast_state(active, expected, loaded)
            except (StorageError, ValueError) as error:
                return replace(
                    loaded,
                    snapshot=replace(
                        loaded.snapshot,
                        writable=False,
                        issues=(
                            *loaded.snapshot.issues,
                            PodcastIssue(
                                PodcastIssueCode.PERSISTENCE_FAILED,
                                "Podcast state was loaded, but its reconciled files "
                                "could not be saved to the iPod.",
                                str(error),
                            ),
                        ),
                    ),
                    requires_persistence=False,
                )

    def save_podcast_state(
        self,
        expected: ActiveIPod,
        state: LoadedPodcastState,
    ) -> LoadedPodcastState:
        """Persist an exact Podcast state revision for the current Active iPod."""

        with self._lock:
            active = self._active
            if active is None or active.active_ipod is not expected:
                raise DeviceChangedError(
                    "The Active iPod changed before Podcast state could be saved."
                )
            return self._save_podcast_state(active, expected, state)

    def _save_podcast_state(
        self,
        active: _ActiveConnection,
        expected: ActiveIPod,
        state: LoadedPodcastState,
    ) -> LoadedPodcastState:
        with self._storage.open_session(
            active.record.mounted_volume,
            access=AccessMode.READ_WRITE,
        ) as session:
            if self._active is not active or not active.session.is_active:
                raise DeviceChangedError(
                    "The Active iPod changed before Podcast state publication."
                )
            if (
                session.fingerprint(
                    library_resources.database_path(expected.database_name)
                )
                != expected.database_fingerprint
            ):
                raise DeviceChangedError(
                    "The iTunesDB changed; reload before saving Podcast state."
                )
            return self._podcast_store.save(session, state)

    def prepare_library(
        self,
        request: LibraryPreparationRequest,
        progress: Callable[[WriteProgress], None],
        cancelled: threading.Event,
        *,
        podcast_state: LoadedPodcastState | None = None,
    ) -> LibraryReview:
        """Prepare a review with private Host staging and read-only device access."""
        from iOpenPod.app.library_write import (
            LibraryReview,
            PreparationCancelledError,
            WriteProgress,
        )
        from iPodDB.library import (
            LibraryWriteResult,
            WriteChecksum,
            WriteIssue,
            WritePhase,
            WriteResources,
            WriteTarget,
        )

        expected, snapshot = request.source, request.snapshot

        def checkpoint(
            phase: str,
            message: str,
            *,
            completed: int | None = None,
            total: int | None = None,
            current_item: str = "",
            unit: str = "",
        ) -> None:
            if cancelled.is_set():
                raise PreparationCancelledError
            progress(
                WriteProgress(
                    phase,
                    message,
                    completed=completed,
                    total=total,
                    current_item=current_item,
                    unit=unit,
                )
            )

        def database_progress(phase: WritePhase) -> None:
            labels = {
                WritePhase.VALIDATION: source_text("Validating Library changes"),
                WritePhase.RESOURCES: source_text("Validating required resources"),
                WritePhase.RECONCILIATION: source_text(
                    "Reconciling retained database records"
                ),
                WritePhase.ARTWORK: source_text(
                    "Preparing artwork relationships and assets"
                ),
                WritePhase.SERIALIZATION: source_text("Serializing database artifacts"),
                WritePhase.SIGNING: source_text("Finalizing database signatures"),
                WritePhase.VERIFICATION: source_text(
                    "Reparsing and verifying candidate output"
                ),
            }
            checkpoint(
                "database." + phase.value,
                labels[phase],
                completed=tuple(labels).index(phase) + 1,
                total=len(labels),
                current_item=labels[phase],
                unit="steps",
            )

        with self._lock:
            active = self._active
            self._discard_prepared_write()
            self._preparation_generation += 1
            preparation_generation = self._preparation_generation
            presentation_policy = self._current_presentation_policy()
            if active is None or active.active_ipod.library is not expected.library:
                return LibraryReview(
                    None,
                    LibraryWriteResult(
                        (
                            WriteIssue(
                                "source.changed",
                                "The Active iPod changed. Review the current Library instead.",
                            ),
                        )
                    ),
                )
            source = active.library_source
        plan: LibraryWritePlan | None = None
        resources: WriteResources | None = None
        result: LibraryWriteResult | None = None
        checkpoint("source.check", "Checking source")
        temporary_files = contextlib.ExitStack()
        try:
            if (
                active.session.fingerprint(
                    library_resources.database_path(expected.database_name)
                )
                != expected.database_fingerprint
            ):
                raise DeviceChangedError(
                    "The source iTunesDB changed. Reload the Library before preparing changes."
                )
            if (
                expected.artwork_database_fingerprint is not None
                and active.session.fingerprint(_ARTWORKDB_PATH)
                != expected.artwork_database_fingerprint
            ):
                raise DeviceChangedError(
                    "The source ArtworkDB changed. Reload the Library before preparing changes."
                )
            photos_fingerprint = (
                active.session.fingerprint(_PHOTOSDB_PATH)
                if active.session.exists(_PHOTOSDB_PATH)
                else None
            )
            if photos_fingerprint != expected.photos_database_fingerprint:
                raise DeviceChangedError(
                    "The source Photo Database changed. Reload the Library before preparing changes."
                )
            capabilities = expected.profile.capabilities
            checksum = WriteChecksum(capabilities.database.checksum.value)
            sqlite_checksum = WriteChecksum(capabilities.database.sqlite_checksum.value)
            guid = _read_device_guid(active.session)
            hash72_material: Hash72Material | None = None
            if WriteChecksum.HASH72 in (checksum, sqlite_checksum):
                if active.session.exists(_HASHINFO_PATH):
                    hash72_material = _read_hash72_material(
                        active.session, source.serialize().itunes, guid
                    )
                else:
                    with contextlib.suppress(ValueError, StorageError):
                        hash72_material = _read_hash72_material(
                            active.session, source.serialize().itunes, guid
                        )
            sqlite_postprocess_commands: tuple[str, ...] = ()
            sqlite_postprocess_preconditions: tuple[FilePrecondition, ...] = ()
            if capabilities.database.uses_sqlite_database:
                (
                    sqlite_postprocess_commands,
                    sqlite_postprocess_precondition,
                ) = _read_sqlite_postprocess_commands(
                    active.session,
                    required=capabilities.database.requires_sqlite_postprocessing,
                )
                sqlite_postprocess_preconditions = (sqlite_postprocess_precondition,)
            target = WriteTarget(
                checksum=checksum,
                firewire_guid=guid,
                max_database_bytes=capabilities.database.max_database_bytes,
                compressed_database=capabilities.database.supports_compressed_database,
                sqlite_database=capabilities.database.uses_sqlite_database,
                sqlite_checksum=sqlite_checksum,
                hash72_material=hash72_material,
                sqlite_postprocess_commands=sqlite_postprocess_commands,
                artwork_root_value=capabilities.artwork.artwork_root_value,
                photos_root_value=capabilities.artwork.photos_root_value,
                photo_formats=tuple(
                    PhotoThumbnailFormat(
                        f.format_id,
                        f.width,
                        f.height,
                        f.row_bytes,
                        PhotoPixelFormat(f.pixel_format.value),
                    )
                    for f in capabilities.artwork.photo_formats
                ),
                supports_sparse_artwork=capabilities.artwork.supports_sparse_artwork,
                cover_formats=tuple(
                    CoverFormat(
                        f.format_id,
                        f.width,
                        f.height,
                        f.row_bytes,
                        CoverPixelFormat(f.pixel_format.value),
                    )
                    for f in capabilities.artwork.cover_formats
                ),
            )
            if active.time_precondition is None:
                raise DeviceChangedError(
                    "The iPod timezone settings could not be verified. Reload before saving."
                )
            library_resources.recheck(active.session, (active.time_precondition,))
            library_resources.recheck(active.session, active.sidecar_preconditions)
            checkpoint("draft.analysis", "Analyzing changes")
            plan = source.analyze(
                source.begin_draft(
                    snapshot,
                    delete_omissions=request.delete_omissions,
                    replace_media=request.replace_media,
                    replace_photos=request.replace_photos,
                ),
                target,
            )
            checkpoint("resources.capture", "Capturing required resources")
            captured = library_resources.capture(
                active.session,
                request,
                plan,
                lambda: checkpoint("resources.capture", "Capturing required resources"),
                temporary_files=temporary_files,
                additional_preconditions=(
                    *sqlite_postprocess_preconditions,
                    active.time_precondition,
                ),
                volume_presentation_enabled=presentation_policy.enabled,
                consumed_sidecars=source.consumed_sidecars,
                loaded_sidecars=active.sidecar_preconditions,
            )
            resources = captured.resources
            result = source.prepare(plan, resources, progress=database_progress)
            result = replace(result, issues=(*result.issues, *captured.issues))
            checkpoint("source.recheck", "Verifying source revision")
            with self._lock:
                if self._active is not active or not active.session.is_active:
                    raise DeviceChangedError(
                        "The Active iPod disconnected or changed during preparation."
                    )
            if (
                active.session.fingerprint(
                    library_resources.database_path(expected.database_name)
                )
                != expected.database_fingerprint
            ):
                raise DeviceChangedError(
                    "The source database changed during preparation. Reload and review again."
                )
            if (
                expected.artwork_database_fingerprint is not None
                and active.session.fingerprint(_ARTWORKDB_PATH)
                != expected.artwork_database_fingerprint
            ):
                raise DeviceChangedError(
                    "The source ArtworkDB changed during preparation. Reload and review again."
                )
            photos_fingerprint = (
                active.session.fingerprint(_PHOTOSDB_PATH)
                if active.session.exists(_PHOTOSDB_PATH)
                else None
            )
            if photos_fingerprint != expected.photos_database_fingerprint:
                raise DeviceChangedError(
                    "The source Photo Database changed during preparation. Reload and review again."
                )
            write = None
            if result.prepared is not None:
                library_resources.recheck(active.session, captured.files)
                original = source.serialize()
                write = library_resources.transaction(
                    active.session,
                    captured,
                    result.prepared,
                    original.itunes,
                    original.artwork,
                    original.photos,
                    primary_database=library_resources.database_path(
                        expected.database_name
                    ),
                )
                if podcast_state is not None:
                    history = self._podcast_store.history_transaction(podcast_state)
                    write = replace(
                        write,
                        writes=(*write.writes, *history.writes),
                        dependencies=(*write.dependencies, *history.dependencies),
                    )
                    active.session.validate_transaction(write)
            review = LibraryReview(
                plan,
                result,
                resources=resources,
                file_changes=library_resources.describe(write)
                if write is not None
                else (),
            )
            with self._lock:
                if (
                    self._active is active
                    and write is not None
                    and preparation_generation == self._preparation_generation
                    and presentation_policy is self._current_presentation_policy()
                ):
                    self._prepared_for_save = _PreparedLibraryWrite(
                        review, write, presentation_policy, temporary_files.pop_all()
                    )
            return review
        except (StorageError, DeviceChangedError, ValueError) as error:
            code = "source.unavailable"
            message = "The source could not be verified. Reconnect or reload before reviewing."
            if isinstance(error, StorageCapacityError):
                code = "resources.insufficient_space"
                message = "There is not enough free space to stage these changes and retain recovery data."
            elif isinstance(error, ValueError):
                code = "resources.invalid_input"
                message = "Required resources could not be prepared. Review the details and correct the input."
            return LibraryReview(
                plan,
                LibraryWriteResult(
                    (
                        *(
                            result.issues
                            if result is not None
                            else plan.issues
                            if plan is not None
                            else ()
                        ),
                        WriteIssue(
                            code,
                            message,
                            phase="resources",
                            detail=str(error),
                        ),
                    ),
                    measurements=result.measurements if result is not None else (),
                ),
                resources=resources,
            )
        finally:
            temporary_files.close()

    def save_library(
        self,
        review: LibraryReview,
        expected: ActiveIPod,
        progress: Callable[[WriteProgress], None],
        cancelled: threading.Event,
        *,
        retain_recovery: bool = False,
    ) -> LibrarySaveResult:
        """Publish the issued review and clean its verified transaction by default.

        Sync explicitly retains recovery until its post-commit provenance step,
        then owns finalization. Ordinary saves must not leave that work to callers.
        """
        from iOpenPod.app.library_write import (
            LibrarySaveResult,
            PreparationCancelledError,
            WriteProgress,
        )
        from iPodDB.library import (
            IssueSeverity,
            WriteIssue,
        )

        def failure(
            code: str, message: str, detail: str = "", recovery: str = ""
        ) -> LibrarySaveResult:
            return LibrarySaveResult(
                (
                    WriteIssue(
                        code,
                        message,
                        phase="save",
                        detail=detail,
                        artifact=str(
                            library_resources.database_path(expected.database_name)
                        ),
                    ),
                ),
                recovery_path=recovery,
            )

        with self._lock:
            active = self._active
            issued = self._prepared_for_save
            plan, prepared = review.plan, review.result.prepared
            if (
                active is None
                or active.active_ipod.library is not expected.library
                or issued is None
                or review is not issued.review
                or issued.presentation_policy is not self._current_presentation_policy()
                or plan is None
                or prepared is None
                or prepared.source_revision
                != active.library_source.begin_draft().source_revision
            ):
                return failure(
                    "save.stale",
                    "The review no longer belongs to the Active iPod. Prepare again.",
                )
            # Construct the next authoritative source before touching the device.
            updated_source = IPodLibrary.parse(
                prepared.itunes, device_time=active.library_source.device_time
            )
            if prepared.artwork is not None:
                updated_source = updated_source.with_artwork(prepared.artwork)
            if prepared.photos is not None:
                updated_source = updated_source.with_photos(prepared.photos)
            if updated_source.snapshot != prepared.snapshot:
                return failure(
                    "save.verification_failed",
                    "The prepared Library did not verify.",
                )
            try:
                with self._storage.open_session(
                    active.record.mounted_volume, access=AccessMode.READ_WRITE
                ) as session:

                    def checkpoint() -> None:
                        if cancelled.is_set():
                            raise PreparationCancelledError
                        if self._active is not active or not active.session.is_active:
                            raise DeviceChangedError(
                                "The Active iPod changed before publication"
                            )
                        if (
                            session.fingerprint(
                                library_resources.database_path(expected.database_name)
                            )
                            != expected.database_fingerprint
                        ):
                            raise DeviceChangedError(
                                "The iTunesDB changed; reload before retrying"
                            )
                        artwork_fingerprint = (
                            session.fingerprint(_ARTWORKDB_PATH)
                            if session.exists(_ARTWORKDB_PATH)
                            else None
                        )
                        if artwork_fingerprint != expected.artwork_database_fingerprint:
                            raise DeviceChangedError(
                                "The ArtworkDB changed; reload before retrying"
                            )
                        photos_fingerprint = (
                            session.fingerprint(_PHOTOSDB_PATH)
                            if session.exists(_PHOTOSDB_PATH)
                            else None
                        )
                        if photos_fingerprint != expected.photos_database_fingerprint:
                            raise DeviceChangedError(
                                "The Photo Database changed; reload before retrying"
                            )
                        if (
                            plan.requires_sidecar_inventory
                            and library_resources.pending_sidecars(
                                session,
                                tuple(
                                    file.path
                                    for file in issued.transaction.dependencies
                                )
                                + tuple(
                                    write.path for write in issued.transaction.writes
                                )
                                + tuple(
                                    removal.path
                                    for removal in issued.transaction.removals
                                ),
                            )
                        ):
                            raise DeviceChangedError(
                                "Playback sidecars appeared after review; reload before retrying"
                            )
                        if plan.target.firewire_guid and (
                            _read_device_guid(session) != plan.target.firewire_guid
                        ):
                            raise DeviceChangedError(
                                "The device signing identity changed"
                            )
                        if plan.target.hash72_material is not None:
                            try:
                                material = _read_hash72_material(
                                    session,
                                    active.library_source.serialize().itunes,
                                    plan.target.firewire_guid,
                                )
                            except ValueError as error:
                                raise DeviceChangedError(
                                    "The device HASH72 signing material changed"
                                ) from error
                            if not material.matches(plan.target.hash72_material):
                                raise DeviceChangedError(
                                    "The device HASH72 signing material changed"
                                )

                    progress(
                        WriteProgress(
                            "save.source_check", "Checking the reviewed source"
                        )
                    )
                    checkpoint()
                    progress(
                        WriteProgress(
                            "save.storage_transaction",
                            "Staging and verifying Library files…",
                        )
                    )

                    def cancel_checkpoint() -> None:
                        if cancelled.is_set():
                            raise PreparationCancelledError
                        if self._active is not active or not active.session.is_active:
                            raise DeviceChangedError(
                                "The Active iPod changed during staging"
                            )

                    def transaction_progress(event: TransactionProgress) -> None:
                        progress(
                            WriteProgress(
                                "save.storage." + event.state.value,
                                _transaction_progress_text(event),
                                completed=event.completed,
                                total=event.total,
                                current_item=str(event.path or ""),
                                unit="files",
                            )
                        )
                        if event.state is TransactionState.PREPARED:
                            checkpoint()

                    committed = session.execute_transaction(
                        issued.transaction,
                        checkpoint=cancel_checkpoint,
                        progress=transaction_progress,
                        activity=lambda event: progress(
                            _transaction_activity_progress(event)
                        ),
                    )
                    # Storage verified the entire committed artifact by SHA-256.
                    fingerprints = {
                        file.path: file.fingerprint for file in committed.recovery.files
                    }
                    primary_database = library_resources.database_path(
                        expected.database_name
                    )
                    database_fingerprint = fingerprints[primary_database]
                    assert database_fingerprint is not None
                    updated = replace(
                        expected,
                        library=updated_source.snapshot,
                        database_fingerprint=database_fingerprint,
                        artwork_database_fingerprint=fingerprints[_ARTWORKDB_PATH],
                        photos_database_fingerprint=fingerprints[_PHOTOSDB_PATH],
                    )
                    active.library_source = updated_source
                    active.sidecar_preconditions = tuple(
                        FilePrecondition(
                            file.path, fingerprints.get(file.path, file.fingerprint)
                        )
                        for file in active.sidecar_preconditions
                        if not any(
                            r.path == file.path for r in issued.transaction.removals
                        )
                    )
                    active.active_ipod = updated
                    self._discard_prepared_write()
                    self._ithmb_bytes.clear()
                    self._ithmb_cache_bytes = 0
                    issues: tuple[WriteIssue, ...] = (
                        ()
                        if committed.flush.complete
                        else (
                            WriteIssue(
                                "save.flush_incomplete",
                                "Library changes were verified, but the system could not confirm a complete device flush. Use the operating system's safe eject before unplugging.",
                                severity=IssueSeverity.WARNING,
                                phase="save",
                                detail=committed.flush.detail,
                            ),
                        )
                    )
                    if (
                        issued.presentation_policy.enabled
                        and expected.library.device_name != updated.library.device_name
                    ):
                        details = volume_presentation.apply_native(
                            session, updated.library.device_name
                        )
                        if details:
                            issues += (
                                WriteIssue(
                                    "save.volume_presentation_incomplete",
                                    "The iPod name was saved, but its desktop name or icon could not be applied exactly.",
                                    severity=IssueSeverity.WARNING,
                                    phase="save",
                                    detail="\n".join(details),
                                ),
                            )
                    recovery_path = str(committed.recovery.journal_path)
                    if not retain_recovery:
                        try:
                            progress(
                                WriteProgress(
                                    "save.cleanup",
                                    "Cleaning verified Library recovery files…",
                                )
                            )
                            _finalize_committed_transaction(
                                session, committed.recovery.journal_path
                            )
                            recovery_path = ""
                        except SyncCleanupCompletedError as error:
                            recovery_path = ""
                            issues += (
                                WriteIssue(
                                    "save.cleanup_flush_pending",
                                    "Library changes were saved and recovery files were removed, "
                                    "but the final device flush could not be confirmed. "
                                    "Safely eject before unplugging.",
                                    severity=IssueSeverity.WARNING,
                                    phase="save",
                                    detail=str(error),
                                ),
                            )
                        except Exception as error:
                            # Publication is already verified. A cleanup failure
                            # must never turn the accepted Library into a failed save.
                            issues += (
                                WriteIssue(
                                    "save.cleanup_pending",
                                    "Library changes were saved, but recovery-file cleanup "
                                    "could not finish. Reload the iPod to retry cleanup.",
                                    severity=IssueSeverity.WARNING,
                                    phase="save",
                                    detail=str(error),
                                    artifact=recovery_path,
                                ),
                            )
                    return LibrarySaveResult(issues, updated, recovery_path)
            except RecoverableWriteError as error:
                self._discard_prepared_write()
                if not error.publication_started and isinstance(
                    error.__cause__, PreparationCancelledError
                ):
                    return failure(
                        "save.cancelled",
                        "Saving was cancelled.",
                        recovery=error.recovery_path,
                    )
                return failure(
                    "save.recovery_required"
                    if error.publication_started
                    else "save.failed",
                    "Saving could not be verified. Reload the iPod before retrying; a recovery copy may be available.",
                    str(error),
                    error.recovery_path,
                )
            except (StorageError, DeviceChangedError) as error:
                return failure(
                    "save.source_unavailable",
                    "The iPod could not be saved. Reconnect or reload before retrying.",
                    str(error),
                )

    @property
    def cached_ithmb_byte_count(self) -> int:
        with self._lock:
            return self._ithmb_cache_bytes

    def discover_devices(self, *, refresh_known: bool = True) -> DeviceDiscovery:
        """Replace candidate state from one complete Storage discovery pass."""

        with self._lock:
            result = self._storage.discover()
            records = tuple(
                record
                for item in result.volumes
                if (record := self._discover_record(item, refresh_known)) is not None
            )
            records = tuple(
                sorted(
                    records,
                    key=lambda item: (
                        item.candidate.display_name.casefold(),
                        item.candidate.id.value,
                    ),
                )
            )
            self._records = {record.candidate.id: record for record in records}
            self._discovery_volumes = {
                DeviceCandidateId(item.connection_generation.value): item
                for item in result.volumes
            }
            active_id = self._reconcile_active_connection(
                refresh_candidate=refresh_known,
            )
            self._discovery = DeviceDiscovery(
                candidates=tuple(record.candidate for record in records),
                issues=tuple(
                    DeviceDiscoveryIssue(issue.source, issue.detail)
                    for issue in result.issues
                ),
                active_candidate_id=active_id,
            )
            return self._discovery

    def _discover_record(
        self, mounted: MountedVolume, refresh_known: bool
    ) -> _CandidateRecord | None:
        previous = self._records.get(
            DeviceCandidateId(mounted.connection_generation.value)
        )
        current: _CandidateRecord | None
        try:
            if (
                not refresh_known
                and previous is not None
                and previous.candidate.readiness is DeviceReadiness.READY
                and self._discovery_volumes.get(previous.candidate.id) == mounted
            ):
                with self._storage.open_session(mounted) as session:
                    self._check_sync_recovery(session)
                current = previous
            else:
                current = self._inspect_mounted_volume(mounted)
            active = self._active
            if (
                current is not None
                and previous is not None
                and active is not None
                and active.record.mounted_volume.connection_generation
                == mounted.connection_generation
            ):
                with self._storage.open_session(mounted) as session:
                    self._sync_cleanup_path = self._check_sync_recovery(session)
                cleanup_issues = tuple(
                    issue
                    for issue in previous.persistent_issues
                    if issue.code
                    is DeviceCandidateIssueCode.TRANSACTION_CLEANUP_FLUSH_PENDING
                    or (
                        issue.code
                        is DeviceCandidateIssueCode.TRANSACTION_CLEANUP_PENDING
                        and self._sync_cleanup_path
                    )
                )
                current = replace(
                    current,
                    candidate=replace(
                        current.candidate,
                        issues=tuple(
                            issue
                            for issue in current.candidate.issues
                            if issue.code not in _TRANSACTION_CLEANUP_ISSUE_CODES
                        )
                        + cleanup_issues,
                    ),
                    persistent_issues=tuple(
                        issue
                        for issue in current.persistent_issues
                        if issue.code not in _TRANSACTION_CLEANUP_ISSUE_CODES
                    )
                    + cleanup_issues,
                )
            return current
        except SyncRecoveryRequiredError as error:
            # Discovery must still list every other iPod. Selection opens the
            # recovery choice before parsing this iPod's interrupted Library.
            hardware = _hardware_evidence(mounted)
            record = previous or _inspection_failed_record(
                mounted,
                self._registry.identify(hardware),
                hardware,
                StorageError(str(error)),
            )
            return replace(
                record,
                candidate=replace(
                    record.candidate,
                    readiness=DeviceReadiness.SYNC_RECOVERY_REQUIRED,
                    issues=(),
                ),
            )

    def select_device(
        self,
        candidate_id: DeviceCandidateId,
        *,
        reconcile_metadata: bool = True,
        reconcile_sidecars: bool = True,
    ) -> ActiveIPod:
        """Commit captured sidecars before exposing the selected Library.

        Recovery reloads disable reconciliation to show the restored or explicitly
        kept database without immediately changing the user's recovery outcome.
        """

        with self._lock:
            self._deactivate_locked()
            record = self._records.get(candidate_id)
            if record is None:
                raise DeviceCandidateNotFoundError(
                    "This device is no longer connected. Refresh the Device Picker."
                )
            record = replace(
                record,
                candidate=replace(
                    record.candidate,
                    issues=tuple(
                        issue
                        for issue in record.candidate.issues
                        if issue.code not in _TRANSACTION_CLEANUP_ISSUE_CODES
                    ),
                ),
                persistent_issues=tuple(
                    issue
                    for issue in record.persistent_issues
                    if issue.code not in _TRANSACTION_CLEANUP_ISSUE_CODES
                ),
            )
            if not record.candidate.selectable:
                raise DeviceNotSelectableError(
                    source_text(
                        "{name} is not ready to load ({readiness}).",
                        name=record.candidate.display_name,
                        readiness=record.candidate.readiness.value,
                    )
                )

            try:
                with self._storage.open_session(
                    record.mounted_volume
                ) as preflight_session:
                    self._sync_cleanup_path = self._check_sync_recovery(
                        preflight_session
                    )
            except StorageError as error:
                raise DeviceAccessError(str(error)) from error
            if reconcile_metadata:
                cleanup_issues = self._cleanup_selected_transactions(record)
                for issue in cleanup_issues:
                    record = _with_persistent_issue(record, issue)
                record = self._reconcile_device_metadata(record)
            self._records[candidate_id] = record

            try:
                session = self._storage.open_session(
                    record.mounted_volume,
                    access=AccessMode.READ_ONLY,
                )
            except StorageError as error:
                raise DeviceAccessError(str(error)) from error

            try:
                current = self._inspect_open_session(
                    session,
                    record.hardware_evidence,
                    live_sysinfo_extended=record.live_sysinfo_extended,
                    persistent_issues=record.persistent_issues,
                )
                _require_same_profile(record, current)
                database_path = current.database_path
                profile = current.candidate.profile
                if database_path is None or profile is None:
                    raise DeviceNotSelectableError(
                        "The selected iPod no longer has a supported iTunesDB."
                    )

                snapshot = session.read_snapshot(
                    database_path,
                    max_bytes=profile.capabilities.database.max_database_bytes,
                )
                try:
                    preferences = capture_ipod_preferences(
                        session,
                        profile,
                        firmware_versions=tuple(
                            item.value
                            for item in current.device_evidence.firmware_versions
                        ),
                    )
                    library = self._library_loader(snapshot.data).with_device_time(
                        preferences.device_time
                    )
                except (TypeError, ValueError) as error:
                    raise DeviceLibraryLoadError(
                        "The selected iPod's primary Library database could not be parsed."
                    ) from error

                current_fingerprint = session.fingerprint(database_path)
                if current_fingerprint != snapshot.fingerprint:
                    raise DeviceChangedError(
                        "The iTunesDB changed while it was loading. Refresh and try again."
                    )

                current, library, artwork_fingerprint = self._load_optional_artwork(
                    session, current, library
                )
                current, library, photos_fingerprint = self._load_optional_photos(
                    session, current, library
                )

                try:
                    sidecars, sidecar_preconditions = library_resources.load_sidecars(
                        session
                    )
                    if reconcile_sidecars:
                        library = library.with_sidecars(sidecars)
                except ValueError as error:
                    raise DeviceLibraryLoadError(str(error)) from error
                if session.fingerprint(database_path) != current_fingerprint:
                    raise DeviceChangedError(
                        "The iTunesDB changed while playback sidecars were loading. Reload the iPod."
                    )

                time_warnings = library.time_warnings
                if time_warnings:
                    current = replace(
                        current,
                        candidate=replace(
                            current.candidate,
                            issues=(
                                *current.candidate.issues,
                                *(
                                    DeviceCandidateIssue(
                                        DeviceCandidateIssueCode.TIMEZONE_UNCERTAIN,
                                        issue.message,
                                    )
                                    for issue in time_warnings
                                ),
                            ),
                        ),
                    )
                active_ipod = ActiveIPod(
                    candidate=current.candidate,
                    profile=profile,
                    library=library.snapshot,
                    database_name=database_path.name,
                    database_fingerprint=current_fingerprint,
                    artwork_database_fingerprint=artwork_fingerprint,
                    photos_database_fingerprint=photos_fingerprint,
                    preferences=preferences.sections,
                )
                if reconcile_metadata:
                    presentation_issues = self._reconcile_volume_presentation(
                        current, active_ipod
                    )
                    if presentation_issues:
                        current = replace(
                            current,
                            candidate=replace(
                                current.candidate,
                                issues=(
                                    *current.candidate.issues,
                                    *presentation_issues,
                                ),
                            ),
                        )
                        active_ipod = replace(active_ipod, candidate=current.candidate)
                    remaining_cleanup = self._check_sync_recovery(session)
                    if not self._sync_cleanup_path:
                        self._sync_cleanup_path = remaining_cleanup
                    if session.fingerprint(database_path) != current_fingerprint:
                        raise DeviceChangedError(
                            "The iTunesDB changed while desktop presentation was updated. Reload the iPod."
                        )
                self._records[candidate_id] = current
                connection = _ActiveConnection(
                    session=session,
                    record=current,
                    active_ipod=active_ipod,
                    library_source=library,
                    time_precondition=preferences.time_precondition,
                    sidecar_preconditions=sidecar_preconditions,
                )
                # The selection lock keeps this private connection out of the
                # published application state until its transaction is verified.
                self._active = connection
                if reconcile_sidecars:
                    self._commit_selected_sidecars(connection)
                active_ipod = connection.active_ipod
                current = connection.record
                self._records[candidate_id] = current
                self._discovery = replace(
                    self._discovery,
                    candidates=tuple(
                        current.candidate if item.id == candidate_id else item
                        for item in self._discovery.candidates
                    ),
                    active_candidate_id=candidate_id,
                )
                return active_ipod
            except StorageError as error:
                session.close()
                self._deactivate_locked()
                raise DeviceAccessError(str(error)) from error
            except Exception:
                session.close()
                self._deactivate_locked()
                raise

    def _commit_selected_sidecars(self, active: _ActiveConnection) -> None:
        """Use the normal signed, verified save while selection owns the lock."""
        from iOpenPod.app.library_write import LibraryPreparationRequest
        from iPodDB.library import IssueSeverity, WriteIssue

        def load_error(issues: tuple[WriteIssue, ...]) -> DeviceLibraryLoadError:
            return DeviceLibraryLoadError(
                source_text(
                    "Playback history and On-The-Go Playlists could not be saved "
                    "while loading the iPod. {detail}",
                    detail="\n".join(
                        f"{issue.message} {issue.detail}".strip()
                        for issue in issues
                        if issue.severity is IssueSeverity.ERROR
                    ),
                )
            )

        source = active.library_source
        if source.sidecar_issues:
            raise load_error(source.sidecar_issues)
        if not source.consumed_sidecars:
            return
        cancelled = threading.Event()
        expected = active.active_ipod
        review = self.prepare_library(
            LibraryPreparationRequest(expected.library, expected, 0, 0),
            lambda _: None,
            cancelled,
        )
        if review.result.prepared is None:
            raise load_error(review.result.issues)
        saved = self.save_library(review, expected, lambda _: None, cancelled)
        if saved.active is None:
            if saved.recovery_path:
                # Keep recovery actionable even if the device disconnected and
                # the selection session can no longer inspect the journal.
                raise SyncRecoveryRequiredError(saved.recovery_path)
            raise load_error(saved.issues)
        if saved.recovery_path:
            self._sync_cleanup_path = saved.recovery_path
        for issue in saved.issues:
            code = {
                "save.cleanup_pending": DeviceCandidateIssueCode.TRANSACTION_CLEANUP_PENDING,
                "save.cleanup_flush_pending": DeviceCandidateIssueCode.TRANSACTION_CLEANUP_FLUSH_PENDING,
            }.get(issue.code, DeviceCandidateIssueCode.PLAYBACK_SIDECAR_FLUSH_PENDING)
            active.record = _with_persistent_issue(
                active.record,
                DeviceCandidateIssue(code, f"{issue.message} {issue.detail}".strip()),
            )
        active.active_ipod = replace(saved.active, candidate=active.record.candidate)

    def _cleanup_selected_transactions(
        self, record: _CandidateRecord
    ) -> tuple[DeviceCandidateIssue, ...]:
        """Reclaim verified terminal transactions only for the selected iPod."""
        if not self._sync_cleanup_path:
            return ()
        if not record.mounted_volume.volume.capabilities.safe_for_writes:
            return (
                DeviceCandidateIssue(
                    DeviceCandidateIssueCode.TRANSACTION_CLEANUP_PENDING,
                    "Recovery files could not be cleaned because the Volume is read-only or unsafe for writes.",
                ),
            )
        issues: list[DeviceCandidateIssue] = []
        pending = ""
        try:
            with self._storage.open_session(
                record.mounted_volume, access=AccessMode.READ_WRITE
            ) as session:
                # Examine every journal before deleting any recovery copies. An
                # unfinished or malformed transaction still requires a decision.
                journals = self._terminal_sync_journals(session)
                for path, state in journals:
                    self._sync_cleanup_path = pending or str(path)
                    try:
                        flushed = (
                            session.finalize_committed_transaction(path)
                            if state is TransactionState.COMMITTED
                            else session.finalize_restored_transaction(path)
                        )
                    except StorageError as error:
                        if not session.is_active:
                            raise
                        remains = session.exists(path)
                        if remains and not pending:
                            pending = str(path)
                        issues.append(
                            DeviceCandidateIssue(
                                DeviceCandidateIssueCode.TRANSACTION_CLEANUP_PENDING
                                if remains
                                else DeviceCandidateIssueCode.TRANSACTION_CLEANUP_FLUSH_PENDING,
                                (
                                    source_text(
                                        "Recovery-file cleanup could not finish for {path}: {error}",
                                        path=str(path),
                                        error=str(error),
                                    )
                                    if remains
                                    else source_text(
                                        "Recovery files were removed, but device flushing could not be confirmed. "
                                        "Safely eject before unplugging. {error}",
                                        error=str(error),
                                    )
                                ),
                            )
                        )
                    else:
                        if not flushed.complete:
                            issues.append(
                                DeviceCandidateIssue(
                                    DeviceCandidateIssueCode.TRANSACTION_CLEANUP_FLUSH_PENDING,
                                    source_text(
                                        "Recovery files were removed, but device flushing could not be confirmed. "
                                        "Safely eject before unplugging. {detail}",
                                        detail=flushed.detail,
                                    ),
                                )
                            )
        except StorageError as error:
            return (
                *issues,
                DeviceCandidateIssue(
                    DeviceCandidateIssueCode.TRANSACTION_CLEANUP_PENDING,
                    source_text(
                        "Recovery-file cleanup could not finish: {error}",
                        error=str(error),
                    ),
                ),
            )
        self._sync_cleanup_path = pending
        return tuple(issues)

    def _reconcile_volume_presentation(
        self, record: _CandidateRecord, active: ActiveIPod
    ) -> tuple[DeviceCandidateIssue, ...]:
        """Provision only the selected iPod, with its saved name as a dependency."""
        if not self.volume_presentation_enabled:
            return ()
        if not record.mounted_volume.volume.capabilities.safe_for_writes:
            return (
                DeviceCandidateIssue(
                    DeviceCandidateIssueCode.VOLUME_PRESENTATION_INCOMPLETE,
                    "Desktop appearance was not updated because the Volume is read-only or unsafe for writes.",
                ),
            )
        try:
            with self._storage.open_session(
                record.mounted_volume, access=AccessMode.READ_WRITE
            ) as session:
                presentation = volume_presentation.capture(
                    session, active.library.device_name, active.profile.product_image
                )
                if presentation.writes:
                    changed = {write.path for write in presentation.writes}
                    transaction = StorageTransaction(
                        presentation.writes,
                        dependencies=(
                            FilePrecondition(
                                library_resources.database_path(active.database_name),
                                active.database_fingerprint,
                            ),
                            *(
                                file
                                for file in presentation.files
                                if file.path not in changed
                            ),
                        ),
                    )
                    committed = session.execute_transaction(transaction)
                    session.finalize_committed_transaction(
                        committed.recovery.journal_path
                    )
                library_resources.recheck(
                    session,
                    (
                        FilePrecondition(
                            library_resources.database_path(active.database_name),
                            active.database_fingerprint,
                        ),
                    ),
                )
                details = volume_presentation.apply_native(
                    session, active.library.device_name
                )
        except (StorageError, OSError, ValueError) as error:
            details = (str(error),)
        return tuple(
            DeviceCandidateIssue(
                DeviceCandidateIssueCode.VOLUME_PRESENTATION_INCOMPLETE, detail
            )
            for detail in details
        )

    def load_artwork(self, request: ArtworkRequest) -> ArtworkImage | None:
        """Read and decode the best available cover for one current image ID."""

        with self._lock:
            active = self._active
            if active is None:
                return None
            try:
                read = active.library_source.artwork_read(
                    request.artwork_id,
                    tuple(
                        CoverFormat(
                            cover.format_id,
                            cover.width,
                            cover.height,
                            cover.row_bytes,
                            CoverPixelFormat(cover.pixel_format.value),
                        )
                        for cover in _display_cover_formats(active.active_ipod.profile)
                    ),
                    request.target_px,
                )
            except ValueError as error:
                raise DeviceArtworkLoadError(str(error)) from error
            if read is None:
                return None
            generation = active.record.mounted_volume.connection_generation
            artwork_fingerprint = active.active_ipod.artwork_database_fingerprint

        try:
            if not 0 < read.length <= _ARTWORK_PAYLOAD_LIMIT:
                raise DeviceArtworkLoadError("Artwork declares an unsafe byte length")
            path = DevicePath(read.relative_path)
            if not path.is_relative_to(_ARTWORK_DIRECTORY):
                raise DeviceArtworkLoadError("Artwork is outside iPod_Control/Artwork")
            payload = self._read_ithmb_payload(
                active,
                path,
                offset=read.offset,
                length=read.length,
            )
            decoded = read.decode(payload)
        except (StorageError, ValueError) as error:
            raise DeviceArtworkLoadError(
                f"Artwork {request.artwork_id} could not be loaded: {error}"
            ) from error

        with self._lock:
            if self._active is not active:
                return None
        fingerprint_key = (
            artwork_fingerprint.sha256 if artwork_fingerprint is not None else "none"
        )
        return ArtworkImage(
            cache_key=(
                f"{generation}:{fingerprint_key}:{request.artwork_id}:{read.format_id}"
            ),
            artwork_id=request.artwork_id,
            format_id=read.format_id,
            width=decoded.width,
            height=decoded.height,
            rgb888=decoded.rgb888,
        )

    def load_photo(self, request: PhotoRequest) -> PhotoImage | None:
        """Read and decode one display representation for a current Photo."""

        full_resolution_path: DevicePath | None = None
        read: PhotoRead | None = None
        with self._lock:
            active = self._active
            if active is None:
                return None
            if request.format_id == FULL_RESOLUTION_REQUEST_ID:
                photos = active.active_ipod.library.photos
                current = (
                    None
                    if photos is None
                    else next(
                        (
                            candidate
                            for candidate in photos.photos
                            if candidate.photo_id == request.photo_id
                        ),
                        None,
                    )
                )
                if current is None:
                    return None
                full_resolution_path = self._full_resolution_path(active, current)
                if full_resolution_path is None:
                    return None
                generation = active.record.mounted_volume.connection_generation
                photos_fingerprint = active.active_ipod.photos_database_fingerprint
            else:
                try:
                    read = active.library_source.photo_read(
                        request.photo_id,
                        tuple(
                            PhotoThumbnailFormat(
                                image_format.format_id,
                                image_format.width,
                                image_format.height,
                                image_format.row_bytes,
                                PhotoPixelFormat(image_format.pixel_format.value),
                            )
                            for image_format in active.active_ipod.profile.capabilities.artwork.photo_formats
                        ),
                        request.target_px,
                        format_id=request.format_id,
                    )
                except ValueError as error:
                    raise DevicePhotoLoadError(str(error)) from error
                if read is None:
                    return None
                generation = active.record.mounted_volume.connection_generation
                photos_fingerprint = active.active_ipod.photos_database_fingerprint

        if full_resolution_path is not None:
            try:
                snapshot = active.session.read_snapshot(
                    full_resolution_path,
                    max_bytes=_PHOTO_PAYLOAD_LIMIT,
                )
                width, height, rgb888 = _decode_full_resolution_photo(
                    snapshot.data,
                    request.target_px,
                )
            except (StorageError, ValueError) as error:
                raise DevicePhotoLoadError(
                    f"Photo {request.photo_id} could not be loaded: {error}"
                ) from error

            with self._lock:
                if self._active is not active:
                    return None
            return PhotoImage(
                cache_key=(
                    f"{generation}:{snapshot.fingerprint.sha256}:"
                    f"{request.photo_id}:{FULL_RESOLUTION_REQUEST_ID}:"
                    f"{request.target_px}"
                ),
                photo_id=request.photo_id,
                format_id=FULL_RESOLUTION_REQUEST_ID,
                width=width,
                height=height,
                rgb888=rgb888,
            )

        if read is None:
            return None
        try:
            if not 0 < read.length <= _PHOTO_PAYLOAD_LIMIT:
                raise DevicePhotoLoadError("Photo declares an unsafe byte length")
            path = DevicePath(read.relative_path)
            if not path.is_relative_to(_PHOTOS_DIRECTORY):
                raise DevicePhotoLoadError("Photo is outside Photos")
            payload = self._read_ithmb_payload(
                active,
                path,
                offset=read.offset,
                length=read.length,
            )
            decoded = read.decode(payload)
        except (StorageError, ValueError) as error:
            raise DevicePhotoLoadError(
                f"Photo {request.photo_id} could not be loaded: {error}"
            ) from error

        with self._lock:
            if self._active is not active:
                return None
        fingerprint_key = (
            photos_fingerprint.sha256 if photos_fingerprint is not None else "none"
        )
        return PhotoImage(
            cache_key=(
                f"{generation}:{fingerprint_key}:{request.photo_id}:{read.format_id}"
            ),
            photo_id=request.photo_id,
            format_id=read.format_id,
            width=decoded.width,
            height=decoded.height,
            rgb888=decoded.rgb888,
        )

    def _full_resolution_path(
        self,
        active: _ActiveConnection,
        photo: Photo,
    ) -> DevicePath | None:
        for representation in photo.representations:
            if (
                representation.kind is not PhotoRepresentationKind.FULL_RESOLUTION
                or not representation.relative_path
            ):
                continue
            try:
                path = DevicePath(representation.relative_path)
            except ValueError:
                continue
            if not path.is_relative_to(_PHOTOS_DIRECTORY):
                continue
            if not active.session.exists(path):
                continue
            entry = active.session.stat(path)
            if entry.kind is DeviceEntryKind.FILE and entry.size > 0:
                return path
        return None

    def reference_for_photo(self, photo: Photo) -> HostPath | None:
        """Return a readable full-resolution Host path for naming, when present."""

        try:
            with self._lock:
                active, _current, path = self._photo_export_source(photo)
                if path is None:
                    return None
                root = active.session.mounted_volume.mount_point.path
                return HostPath(root.joinpath(*path.parts))
        except DevicePhotoExportError:
            raise
        except (StorageError, ValueError) as error:
            raise DevicePhotoExportError(
                source_text(
                    "The selected Photo cannot be referenced on the iPod: {error}",
                    error=str(error),
                )
            ) from error

    def require_photo_export_directory(self, directory: HostPath) -> None:
        """Require Photo export output to be outside the Active iPod's disk."""

        try:
            with self._lock:
                active = self._active
                if active is None:
                    raise DevicePhotoExportError(
                        source_text("Select an Active iPod before exporting Photos.")
                    )
                self._storage.require_host_path_off_physical_device(
                    directory,
                    active.record.mounted_volume,
                )
        except DevicePhotoExportError:
            raise
        except StorageError as error:
            raise DevicePhotoExportError(
                source_text(
                    "The Photo export folder could not be proven to be on another Physical Device: {error}",
                    error=str(error),
                )
            ) from error

    def copy_photo_to_host(
        self,
        photo: Photo,
        destination: HostPath,
        *,
        source: HostPath,
    ) -> CopyResult:
        """Stream one full-resolution Photo into a create-only Host destination."""

        try:
            with self._lock:
                active, _current, path = self._photo_export_source(photo)
                if path is None:
                    raise DevicePhotoExportError(
                        source_text(
                            "The Photo's full-resolution file is no longer readable."
                        )
                    )
                root = active.session.mounted_volume.mount_point.path
                if HostPath(root.joinpath(*path.parts)) != source:
                    raise DevicePhotoExportError(
                        source_text(
                            "The Photo's full-resolution file changed before export."
                        )
                    )
            result = active.session.copy_to_host(path, destination)
            with self._lock:
                if self._active is not active or not active.session.is_active:
                    raise DevicePhotoExportError(
                        source_text(
                            "The Active iPod changed while the Photo was exported."
                        )
                    )
            return result
        except DevicePhotoExportError:
            raise
        except (StorageError, ValueError) as error:
            raise DevicePhotoExportError(
                source_text(
                    "The selected Photo could not be exported: {error}",
                    error=str(error),
                )
            ) from error

    def image_for_photo_export(
        self,
        photo: Photo,
        *,
        format_id: int,
    ) -> PhotoImage | None:
        """Decode one exact retained iTHMB format for Photo export."""

        try:
            with self._lock:
                active, current, _path = self._photo_export_source(photo)
            image = self.load_photo(
                PhotoRequest(current.photo_id, 8192, format_id=format_id)
            )
            with self._lock:
                if self._active is not active or not active.session.is_active:
                    raise DevicePhotoExportError(
                        source_text(
                            "The Active iPod changed while the Photo was exported."
                        )
                    )
            return image
        except DevicePhotoExportError:
            raise
        except (DevicePhotoLoadError, StorageError, ValueError) as error:
            raise DevicePhotoExportError(
                source_text(
                    "The selected Photo could not be decoded for export: {error}",
                    error=str(error),
                )
            ) from error

    def _photo_export_source(
        self,
        photo: Photo,
    ) -> tuple[_ActiveConnection, Photo, DevicePath | None]:
        active = self._active
        if active is None:
            raise DevicePhotoExportError(
                source_text("Select an Active iPod before exporting Photos.")
            )
        photos = active.active_ipod.library.photos
        current = (
            None
            if photos is None
            else next(
                (
                    candidate
                    for candidate in photos.photos
                    if candidate.photo_id == photo.photo_id
                ),
                None,
            )
        )
        if current is None:
            raise DevicePhotoExportError(
                source_text(
                    "This Photo is not stored in the Active iPod Photo Library."
                )
            )
        return active, current, self._full_resolution_path(active, current)

    def open_playback_source(self, track: Track) -> PlaybackSource:
        """Open one current Library Track without exposing its Mount Point."""

        try:
            with self._lock:
                active = self._active
                if active is None:
                    raise PlaybackSourceError(
                        source_text("Select an Active iPod before starting playback.")
                    )
                current_track = next(
                    (
                        candidate
                        for candidate in active.active_ipod.library.tracks
                        if candidate.track_id == track.track_id
                    ),
                    None,
                )
                if current_track is None:
                    raise PlaybackSourceError(
                        source_text(
                            "This Track is no longer part of the Active iPod Library."
                        )
                    )
                path = _track_device_path(current_track)
                entry = active.session.stat(path)
                if entry.kind is not DeviceEntryKind.FILE:
                    raise PlaybackSourceError(
                        source_text(
                            "The selected Track does not reference a readable media file."
                        )
                    )
                identity = active.session.file_identity(path)
                if identity.size <= 0:
                    raise PlaybackSourceError(
                        source_text(
                            "The selected Track does not reference a readable media file."
                        )
                    )

                def read_payload(offset: int, length: int) -> bytes:
                    return self._read_playback_payload(
                        active,
                        path,
                        identity,
                        offset=offset,
                        length=length,
                    )

                return _DevicePlaybackSource(
                    reader=read_payload,
                    byte_count=identity.size,
                    file_name=path.name,
                )
        except PlaybackSourceError:
            raise
        except (StorageError, ValueError) as error:
            raise PlaybackSourceError(
                source_text(
                    "The selected Track's media could not be opened: {error}",
                    error=str(error),
                )
            ) from error

    def reference_for_track(self, track: Track) -> HostPath:
        """Return the current absolute Host path for one validated iPod Track."""

        try:
            with self._lock:
                active, path = self._track_export_source(track)
                root = active.session.mounted_volume.mount_point.path
                return HostPath(root.joinpath(*path.parts))
        except DeviceTrackExportError:
            raise
        except (StorageError, ValueError) as error:
            raise DeviceTrackExportError(
                source_text(
                    "The selected Track cannot be referenced on the iPod: {error}",
                    error=str(error),
                )
            ) from error

    def copy_track_to_host(
        self,
        track: Track,
        destination: HostPath,
        *,
        prepare_staged: Callable[[HostPath], None] | None = None,
    ) -> CopyResult:
        """Stream one validated iPod Track into a create-only Host destination."""

        try:
            with self._lock:
                active, path = self._track_export_source(track)
            result = active.session.copy_to_host(
                path,
                destination,
                prepare_staged=prepare_staged,
            )
            with self._lock:
                if self._active is not active or not active.session.is_active:
                    raise DeviceTrackExportError(
                        source_text(
                            "The Active iPod changed while the Track was exported."
                        )
                    )
            return result
        except DeviceTrackExportError:
            raise
        except (StorageError, ValueError) as error:
            raise DeviceTrackExportError(
                source_text(
                    "The selected Track could not be exported: {error}",
                    error=str(error),
                )
            ) from error

    def artwork_for_track(self, track: Track) -> ArtworkImage | None:
        """Load the largest available cover linked to one current iPod Track."""

        with self._lock:
            active, _path = self._track_export_source(track)
            current_track = next(
                candidate
                for candidate in active.active_ipod.library.tracks
                if candidate.track_id == track.track_id
            )
            artwork_id = current_track.artwork_id
        if artwork_id <= 0:
            return None
        return self.load_artwork(ArtworkRequest(artwork_id, 4096))

    def _track_export_source(
        self, track: Track
    ) -> tuple[_ActiveConnection, DevicePath]:
        active = self._active
        if active is None:
            raise DeviceTrackExportError(
                source_text("Select an Active iPod before exporting Tracks.")
            )
        current_track = next(
            (
                candidate
                for candidate in active.active_ipod.library.tracks
                if candidate.track_id == track.track_id
            ),
            None,
        )
        if current_track is None:
            raise DeviceTrackExportError(
                source_text("This Track is not stored in the Active iPod Library.")
            )
        try:
            path = _track_device_path(current_track)
        except PlaybackSourceError as error:
            raise DeviceTrackExportError(exception_text(error)) from error
        entry = active.session.stat(path)
        if entry.kind is not DeviceEntryKind.FILE or entry.size <= 0:
            raise DeviceTrackExportError(
                source_text(
                    "The selected Track does not reference a readable media file."
                )
            )
        return active, path

    def deactivate(self) -> None:
        """End the Active iPod Filesystem Session and clear device state."""

        with self._lock:
            self._deactivate_locked()

    def eject_active_ipod(self, expected: ActiveIPod) -> EjectResult:
        """Close iOpenPod access, then safely eject the exact Physical Device."""

        with self._lock:
            active = self._active
            if active is None or active.active_ipod is not expected:
                raise DeviceChangedError(
                    "The Active iPod changed before safe eject could begin."
                )
            mounted_volume = active.record.mounted_volume
            active.session.close()
            try:
                result = self._storage.eject(mounted_volume)
            except StorageError as error:
                try:
                    restored_session = self._storage.open_session(
                        mounted_volume,
                        access=AccessMode.READ_ONLY,
                    )
                except StorageError:
                    self._forget_ejected_physical_device_locked(active)
                    raise DeviceEjectError(
                        source_text(
                            "{detail} iOpenPod can no longer verify this connection; "
                            "refresh after completing safe removal in the operating system.",
                            detail=str(error),
                        )
                    ) from error
                active.session = restored_session
                raise DeviceEjectError(str(error)) from error

            self._forget_ejected_physical_device_locked(active)
            return result

    def _load_optional_artwork(
        self,
        session: FilesystemSession,
        record: _CandidateRecord,
        library: IPodLibrary,
    ) -> tuple[_CandidateRecord, IPodLibrary, FileFingerprint | None]:
        """Load optional artwork without weakening connection failure semantics."""

        try:
            if not session.exists(_ARTWORKDB_PATH):
                return record, library, None
            entry = session.stat(_ARTWORKDB_PATH)
            if entry.kind is not DeviceEntryKind.FILE or entry.size <= 0:
                return _unreadable_artwork(
                    record,
                    library,
                    "ArtworkDB is empty or is not a regular file.",
                )
            if entry.size > _ARTWORK_DATABASE_LIMIT:
                return _unreadable_artwork(
                    record,
                    library,
                    "ArtworkDB exceeds the safe metadata read limit.",
                )

            snapshot = session.read_snapshot(
                _ARTWORKDB_PATH,
                max_bytes=_ARTWORK_DATABASE_LIMIT,
            )
            artwork_library = library.with_artwork(snapshot.data)
            fingerprint = session.fingerprint(_ARTWORKDB_PATH)
            if fingerprint != snapshot.fingerprint:
                return _unreadable_artwork(
                    record,
                    library,
                    "ArtworkDB changed while it was loading.",
                )
            return record, artwork_library, fingerprint
        except StorageError as error:
            if not session.is_active:
                raise
            return _unreadable_artwork(record, library, f"ArtworkDB: {error}")
        except (TypeError, ValueError) as error:
            return _unreadable_artwork(record, library, f"ArtworkDB: {error}")

    def _load_optional_photos(
        self,
        session: FilesystemSession,
        record: _CandidateRecord,
        library: IPodLibrary,
    ) -> tuple[_CandidateRecord, IPodLibrary, FileFingerprint | None]:
        """Load optional PhotosDB metadata without weakening device selection."""

        try:
            if not session.exists(_PHOTOSDB_PATH):
                return record, library, None
            entry = session.stat(_PHOTOSDB_PATH)
            if entry.kind is not DeviceEntryKind.FILE or entry.size <= 0:
                return _unreadable_photos(
                    record,
                    library,
                    "Photo Database is empty or is not a regular file.",
                )
            if entry.size > _PHOTOS_DATABASE_LIMIT:
                return _unreadable_photos(
                    record,
                    library,
                    "Photo Database exceeds the safe metadata read limit.",
                )

            snapshot = session.read_snapshot(
                _PHOTOSDB_PATH,
                max_bytes=_PHOTOS_DATABASE_LIMIT,
            )
            photo_library = library.with_photos(snapshot.data)
            fingerprint = session.fingerprint(_PHOTOSDB_PATH)
            if fingerprint != snapshot.fingerprint:
                return _unreadable_photos(
                    record,
                    library,
                    "Photo Database changed while it was loading.",
                )
            return record, photo_library, fingerprint
        except StorageError as error:
            if not session.is_active:
                raise
            return _unreadable_photos(record, library, f"Photo Database: {error}")
        except (TypeError, ValueError) as error:
            return _unreadable_photos(record, library, f"Photo Database: {error}")

    def close(self) -> None:
        """Release every Filesystem Session owned by this coordinator."""

        with self._lock:
            self._deactivate_locked()
            self._storage.close_all_sessions()

    def _inspect_mounted_volume(
        self,
        mounted: MountedVolume,
    ) -> _CandidateRecord | None:
        hardware_evidence = _hardware_evidence(mounted)
        try:
            with self._storage.open_session(
                mounted,
                access=AccessMode.READ_ONLY,
            ) as preflight_session:
                if not preflight_session.exists(_IPOD_CONTROL_PATH):
                    return None
                self._check_sync_recovery(preflight_session)
                if not _hardware_probe_required(
                    preflight_session,
                    self._registry,
                    hardware_evidence,
                ):
                    return self._inspect_open_session(
                        preflight_session,
                        hardware_evidence,
                    )
        except StorageError as error:
            return _inspection_failed_record(
                mounted,
                self._registry.identify(hardware_evidence),
                hardware_evidence,
                error,
            )

        live_sysinfo_extended = b""
        persistent_issues: tuple[DeviceCandidateIssue, ...] = ()
        try:
            probe = self._storage.probe_hardware(
                mounted,
                page_plan=_IPOD_SYSINFO_VPD_PLAN,
            )
        except StorageError as error:
            persistent_issues = (
                DeviceCandidateIssue(
                    DeviceCandidateIssueCode.HARDWARE_PROBE_FAILED,
                    str(error),
                ),
            )
        else:
            probe_evidence, live_sysinfo_extended = _probe_evidence(
                mounted,
                probe,
            )
            hardware_evidence = hardware_evidence.merged_with(probe_evidence)
            persistent_issues = _probe_candidate_issues(probe)
            persistent_issues = (
                *persistent_issues,
                *_platform_probe_candidate_issues(
                    self._storage.platform_name,
                    mounted,
                    probe,
                ),
            )
        try:
            with self._storage.open_session(
                mounted,
                access=AccessMode.READ_ONLY,
            ) as session:
                return self._inspect_open_session(
                    session,
                    hardware_evidence,
                    live_sysinfo_extended=live_sysinfo_extended,
                    persistent_issues=persistent_issues,
                )
        except StorageError as error:
            return _inspection_failed_record(
                mounted,
                self._registry.identify(hardware_evidence),
                hardware_evidence,
                error,
                live_sysinfo_extended,
                persistent_issues,
            )

    def _inspect_open_session(
        self,
        session: FilesystemSession,
        hardware_evidence: DeviceEvidence | None = None,
        *,
        live_sysinfo_extended: bytes = b"",
        persistent_issues: tuple[DeviceCandidateIssue, ...] = (),
    ) -> _CandidateRecord:
        mounted = session.mounted_volume
        evidence = hardware_evidence or _hardware_evidence(mounted)
        metadata_evidence, metadata_issues = _read_device_metadata(session)
        issues = (*persistent_issues, *metadata_issues)
        device_evidence = evidence.merged_with(metadata_evidence)
        identification = self._registry.identify(device_evidence)
        readiness = _identification_readiness(identification.status)
        database_path: DevicePath | None = None

        profile = identification.profile
        if profile is not None and readiness is DeviceReadiness.READY:
            database = profile.capabilities.database
            database_path, database_readiness, database_issues = _locate_database(
                session,
                compressed=database.supports_compressed_database,
            )
            readiness = database_readiness
            issues = (*issues, *database_issues)

        candidate = _candidate_from(
            mounted,
            identification,
            readiness,
            issues,
        )
        return _CandidateRecord(
            mounted,
            candidate,
            database_path,
            evidence,
            device_evidence,
            live_sysinfo_extended,
            persistent_issues,
        )

    def _reconcile_device_metadata(
        self,
        record: _CandidateRecord,
    ) -> _CandidateRecord:
        profile = record.candidate.profile
        if profile is None:
            return record
        writable = record.mounted_volume.volume.capabilities.safe_for_writes
        access = AccessMode.READ_WRITE if writable else AccessMode.READ_ONLY
        try:
            with self._storage.open_session(
                record.mounted_volume,
                access=access,
            ) as session:
                sysinfo, sysinfo_fingerprint = _read_optional_metadata(
                    session,
                    _SYSINFO_PATH,
                )
                extended, extended_fingerprint = _read_optional_metadata(
                    session,
                    _SYSINFO_EXTENDED_PATH,
                )
                authority, authority_fingerprint = _read_optional_metadata(
                    session,
                    _SYSINFO_AUTHORITY_PATH,
                )
                metadata_evidence = parse_sysinfo(
                    sysinfo,
                    source=_SYSINFO_PATH.name,
                ).merged_with(
                    parse_sysinfo_extended(
                        extended,
                        source=_SYSINFO_EXTENDED_PATH.name,
                    )
                )
                combined_evidence = record.hardware_evidence.merged_with(
                    metadata_evidence
                )
                identification = self._registry.identify(combined_evidence)
                if (
                    identification.profile is None
                    or identification.profile.model_number != profile.model_number
                ):
                    raise DeviceChangedError(
                        "The selected iPod's identity changed before metadata repair."
                    )
                plan = reconcile_device_metadata(
                    evidence=combined_evidence,
                    profile=identification.profile,
                    existing_sysinfo=sysinfo,
                    existing_sysinfo_extended=extended,
                    existing_authority=authority,
                    live_sysinfo_extended=record.live_sysinfo_extended,
                )
                if not plan.changed:
                    return record
                if not writable:
                    return _with_persistent_issue(
                        record,
                        DeviceCandidateIssue(
                            DeviceCandidateIssueCode.METADATA_RECONCILIATION_SKIPPED,
                            "Device identity metadata needs repair, but this Volume "
                            "is not safe for writes.",
                        ),
                    )
                if plan.sysinfo_changed:
                    session.atomic_write(
                        _SYSINFO_PATH,
                        plan.sysinfo,
                        expected=sysinfo_fingerprint,
                        create_parents=True,
                    )
                if plan.sysinfo_extended_changed:
                    session.atomic_write(
                        _SYSINFO_EXTENDED_PATH,
                        plan.sysinfo_extended,
                        expected=extended_fingerprint,
                        create_parents=True,
                    )
                if plan.authority_changed:
                    session.atomic_write(
                        _SYSINFO_AUTHORITY_PATH,
                        plan.authority,
                        expected=authority_fingerprint,
                        create_parents=True,
                    )
                if (
                    session.read(
                        _SYSINFO_PATH,
                        max_bytes=_DEVICE_METADATA_LIMIT,
                    )
                    != plan.sysinfo
                    or session.read(
                        _SYSINFO_EXTENDED_PATH,
                        max_bytes=_DEVICE_METADATA_LIMIT,
                    )
                    != plan.sysinfo_extended
                    or session.read(
                        _SYSINFO_AUTHORITY_PATH,
                        max_bytes=_DEVICE_METADATA_LIMIT,
                    )
                    != plan.authority
                ):
                    raise DeviceChangedError(
                        "Device metadata did not verify after its atomic repair."
                    )
                flush = session.flush()
                flush_issue = (
                    ()
                    if flush.complete
                    else (
                        DeviceCandidateIssue(
                            DeviceCandidateIssueCode.METADATA_RECONCILIATION_FAILED,
                            source_text(
                                "Metadata was verified but the Host could not confirm "
                                "its flush: {detail}",
                                detail=flush.detail,
                            ),
                        ),
                    )
                )
        except DeviceChangedError:
            raise
        except StorageError as error:
            return _with_persistent_issue(
                record,
                DeviceCandidateIssue(
                    DeviceCandidateIssueCode.METADATA_RECONCILIATION_FAILED,
                    str(error),
                ),
            )

        persistent_issues = (*record.persistent_issues, *flush_issue)
        try:
            with self._storage.open_session(
                record.mounted_volume,
                access=AccessMode.READ_ONLY,
            ) as verification_session:
                verified = self._inspect_open_session(
                    verification_session,
                    record.hardware_evidence,
                    live_sysinfo_extended=record.live_sysinfo_extended,
                    persistent_issues=persistent_issues,
                )
        except StorageError as error:
            raise DeviceAccessError(str(error)) from error
        _require_same_profile(record, verified)
        return verified

    def _reconcile_active_connection(
        self, *, refresh_candidate: bool = True
    ) -> DeviceCandidateId | None:
        active = self._active
        if active is None:
            return None
        candidate_id = active.record.candidate.id
        current = self._records.get(candidate_id)
        same_profile = (
            current is not None
            and current.candidate.readiness is DeviceReadiness.READY
            and current.candidate.model_number == active.record.candidate.model_number
        )
        if not active.session.is_active or not same_profile or current is None:
            self._deactivate_locked()
            return None

        active.record = current
        cleanup_changed = tuple(
            issue
            for issue in active.active_ipod.candidate.issues
            if issue.code in _TRANSACTION_CLEANUP_ISSUE_CODES
        ) != tuple(
            issue
            for issue in current.candidate.issues
            if issue.code in _TRANSACTION_CLEANUP_ISSUE_CODES
        )
        if (
            refresh_candidate or cleanup_changed
        ) and active.active_ipod.candidate != current.candidate:
            active.active_ipod = replace(
                active.active_ipod, candidate=current.candidate
            )
        return candidate_id

    def _discard_prepared_write(self) -> None:
        """Release private media copies when their issued review is retired."""
        issued, self._prepared_for_save = self._prepared_for_save, None
        if issued is not None:
            try:
                issued.temporary_files.close()
            except OSError:
                logger.warning(
                    "Could not remove private Library staging files", exc_info=True
                )

    def _deactivate_locked(self) -> None:
        active = self._active
        self._active = None
        self._sync_cleanup_path = ""
        self._discard_prepared_write()
        self._ithmb_bytes.clear()
        self._ithmb_cache_bytes = 0
        if active is not None:
            active.session.close()
        self._discovery = replace(self._discovery, active_candidate_id=None)

    def _forget_ejected_physical_device_locked(
        self,
        active: _ActiveConnection,
    ) -> None:
        """Clear every candidate from the Physical Device that left Storage."""

        physical_id = active.record.mounted_volume.physical_device.id
        removed_ids = {
            candidate_id
            for candidate_id, record in self._records.items()
            if record.mounted_volume.physical_device.id == physical_id
        }
        self._records = {
            candidate_id: record
            for candidate_id, record in self._records.items()
            if candidate_id not in removed_ids
        }
        if self._active is active:
            self._active = None
        self._discard_prepared_write()
        self._ithmb_bytes.clear()
        self._ithmb_cache_bytes = 0
        active.session.close()
        self._discovery = replace(
            self._discovery,
            candidates=tuple(
                candidate
                for candidate in self._discovery.candidates
                if candidate.id not in removed_ids
            ),
            active_candidate_id=None,
        )

    def _read_ithmb_payload(
        self,
        active: _ActiveConnection,
        path: DevicePath,
        *,
        offset: int,
        length: int,
    ) -> bytes:
        session = active.session
        generation = active.record.mounted_volume.connection_generation
        identity = session.file_identity(path)
        key = _IthmbByteCacheKey(generation, path, identity, offset, length)
        with self._lock:
            if self._active is active:
                cached = self._ithmb_bytes.get(key)
                if cached is not None:
                    self._ithmb_bytes.move_to_end(key)
                    return cached

        snapshot = session.read_range_snapshot(path, offset=offset, length=length)
        key = _IthmbByteCacheKey(
            generation,
            path,
            snapshot.identity,
            offset,
            length,
        )
        with self._lock:
            if self._active is active:
                self._discard_stale_ithmb_bytes(key)
                self._retain_ithmb_bytes(key, snapshot.data)
        return snapshot.data

    def _read_playback_payload(
        self,
        active: _ActiveConnection,
        path: DevicePath,
        identity: FileIdentity,
        *,
        offset: int,
        length: int,
    ) -> bytes:
        with self._lock:
            if self._active is not active:
                raise PlaybackSourceError(
                    source_text("Playback stopped because the Active iPod changed.")
                )
        try:
            snapshot = active.session.read_range_snapshot(
                path,
                offset=offset,
                length=length,
            )
        except StorageError as error:
            raise PlaybackSourceError(
                source_text(
                    "Playback could not read the selected Track: {error}",
                    error=str(error),
                )
            ) from error
        with self._lock:
            if self._active is not active:
                raise PlaybackSourceError(
                    source_text("Playback stopped because the Active iPod changed.")
                )
        if snapshot.identity != identity:
            raise PlaybackSourceError(
                source_text(
                    "Playback stopped because the selected Track changed on the iPod."
                )
            )
        return snapshot.data

    def _discard_stale_ithmb_bytes(self, current: _IthmbByteCacheKey) -> None:
        stale = tuple(
            key
            for key in self._ithmb_bytes
            if key.generation == current.generation
            and key.path == current.path
            and key.identity != current.identity
        )
        for key in stale:
            self._ithmb_cache_bytes -= len(self._ithmb_bytes.pop(key))

    def _retain_ithmb_bytes(self, key: _IthmbByteCacheKey, data: bytes) -> None:
        if len(data) > self._ithmb_cache_byte_limit:
            return
        retained = self._ithmb_bytes.pop(key, None)
        if retained is not None:
            self._ithmb_cache_bytes -= len(retained)
        self._ithmb_bytes[key] = data
        self._ithmb_cache_bytes += len(data)
        while self._ithmb_cache_bytes > self._ithmb_cache_byte_limit:
            _discarded_key, discarded = self._ithmb_bytes.popitem(last=False)
            self._ithmb_cache_bytes -= len(discarded)


def _decode_full_resolution_photo(
    payload: bytes,
    target_px: int,
) -> tuple[int, int, bytes]:
    """Decode and downsample one bounded ordinary image for display."""

    from io import BytesIO

    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with Image.open(BytesIO(payload)) as opened:
            if (
                max(opened.size) > 8192
                or opened.width * opened.height > 32 * 1024 * 1024
            ):
                raise ValueError(
                    "Full-resolution Photo dimensions exceed the display limit"
                )
            oriented = ImageOps.exif_transpose(opened)
            try:
                edge = min(target_px, 8192)
                oriented.thumbnail(
                    (edge, edge),
                    Image.Resampling.LANCZOS,
                    reducing_gap=2.0,
                )
                rgb = oriented.convert("RGB")
                try:
                    return rgb.width, rgb.height, rgb.tobytes()
                finally:
                    rgb.close()
            finally:
                oriented.close()
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as error:
        raise ValueError("Full-resolution Photo is not a supported image") from error


def _hardware_evidence(mounted: MountedVolume) -> DeviceEvidence:
    identifiers = mounted.physical_device.identifiers
    source = f"{mounted.physical_device.bus.value} hardware"
    usb_identifiers: tuple[DeviceIdentifier[UsbIdentifier], ...] = ()
    if identifiers.usb_vendor_id is not None and identifiers.usb_product_id is not None:
        usb_identifiers = (
            DeviceIdentifier(
                UsbIdentifier(
                    identifiers.usb_vendor_id,
                    identifiers.usb_product_id,
                ),
                source,
                EvidenceAuthority.CURRENT_HARDWARE,
            ),
        )

    return DeviceEvidence(
        product_serials=_current_text_identifier(
            identifiers.product_serial,
            source,
        ),
        transport_serials=_current_text_identifier(
            identifiers.transport_serial,
            source,
        ),
        usb_identifiers=usb_identifiers,
    )


def _backup_device_context(active: _ActiveConnection) -> BackupDeviceContext:
    from iOpenPod.app.backups.models import (
        BackupDeviceContext,
        BackupDeviceIdentity,
        BackupDeviceMetadata,
        BackupIdentityClaim,
        BackupIdentityClaimKind,
        LegacyIdentityClaim,
    )

    evidence = active.record.device_evidence
    product_serials = tuple(
        item.value.strip() for item in evidence.product_serials if item.value.strip()
    )
    transport_serials = tuple(
        item.value.strip() for item in evidence.transport_serials if item.value.strip()
    )
    mounted = active.record.mounted_volume
    identity = BackupDeviceIdentity(
        (
            *tuple(
                BackupIdentityClaim.from_hardware(
                    BackupIdentityClaimKind.PRODUCT_SERIAL,
                    value,
                )
                for value in product_serials
            ),
            *tuple(
                BackupIdentityClaim.from_hardware(
                    BackupIdentityClaimKind.TRANSPORT_SERIAL,
                    value,
                )
                for value in transport_serials
            ),
            BackupIdentityClaim.from_hardware(
                BackupIdentityClaimKind.VOLUME_ID,
                mounted.volume.id.value,
            ),
        )
    )
    profile = active.active_ipod.profile
    return BackupDeviceContext(
        archive_key=None,
        display_name=active.active_ipod.display_name,
        identity=identity,
        filesystem_type=mounted.volume.filesystem_type,
        metadata=BackupDeviceMetadata(
            family=profile.family,
            generation=profile.generation,
            color=profile.finish,
            display_name=profile.display_name,
            product_image=profile.product_image,
        ),
        legacy_identity_claims=tuple(
            LegacyIdentityClaim.from_original_key(value)
            for value in (*product_serials, *transport_serials)
        ),
    )


def _hardware_probe_required(
    session: FilesystemSession,
    registry: DeviceRegistry,
    hardware_evidence: DeviceEvidence,
) -> bool:
    if not session.exists(_IPOD_CONTROL_PATH):
        return False
    sysinfo, _sysinfo_fingerprint = _read_optional_metadata(
        session,
        _SYSINFO_PATH,
    )
    extended, _extended_fingerprint = _read_optional_metadata(
        session,
        _SYSINFO_EXTENDED_PATH,
    )
    authority, _authority_fingerprint = _read_optional_metadata(
        session,
        _SYSINFO_AUTHORITY_PATH,
    )
    if not authority_covers_metadata(
        authority,
        sysinfo=sysinfo,
        sysinfo_extended=extended,
    ):
        return True
    metadata_evidence = parse_sysinfo(sysinfo).merged_with(
        parse_sysinfo_extended(extended)
    )
    identification = registry.identify(hardware_evidence.merged_with(metadata_evidence))
    return identification.status is not IdentificationStatus.EXACT


def _inspection_failed_record(
    mounted: MountedVolume,
    identification: IdentificationResult,
    hardware_evidence: DeviceEvidence,
    error: StorageError,
    live_sysinfo_extended: bytes = b"",
    persistent_issues: tuple[DeviceCandidateIssue, ...] = (),
) -> _CandidateRecord:
    candidate = _candidate_from(
        mounted,
        identification,
        DeviceReadiness.INSPECTION_FAILED,
        (
            *persistent_issues,
            DeviceCandidateIssue(
                DeviceCandidateIssueCode.INSPECTION_FAILED,
                str(error),
            ),
        ),
    )

    return _CandidateRecord(
        mounted,
        candidate,
        None,
        hardware_evidence,
        hardware_evidence,
        live_sysinfo_extended,
        persistent_issues,
    )


def _probe_evidence(
    mounted: MountedVolume,
    result: HardwareProbeResult,
) -> tuple[DeviceEvidence, bytes]:
    evidence = DeviceEvidence()
    live_sysinfo_extended = b""
    identifiers = mounted.physical_device.identifiers
    for observation in result.observations:
        source = observation.source
        host_properties = {
            property_.name: property_.value for property_ in observation.host_properties
        }
        udev_product_serial = host_properties.get(
            "ID_IOPENPOD_PRODUCT_SERIAL",
            "",
        )
        apple_device = identifiers.usb_vendor_id == 0x05AC or (
            observation.vendor.casefold().startswith("apple")
            and observation.product.casefold().startswith("ipod")
        )
        observation_evidence = DeviceEvidence(
            product_serials=(
                (
                    *_apple_product_serial_identifier(
                        observation.unit_serial,
                        source,
                    ),
                    *_apple_product_serial_identifier(
                        udev_product_serial,
                        "udev_scsi_id",
                    ),
                )
                if apple_device
                else ()
            ),
            transport_serials=_current_text_identifier(
                observation.transport_serial,
                source,
            ),
            firmware_versions=_current_text_identifier(
                observation.firmware_revision,
                source,
            ),
        )
        if observation.vendor_payload:
            observation_evidence = observation_evidence.merged_with(
                parse_sysinfo_extended(
                    observation.vendor_payload,
                    source=source,
                    authority=EvidenceAuthority.CURRENT_HARDWARE,
                )
            )
            if not live_sysinfo_extended:
                live_sysinfo_extended = observation.vendor_payload
        evidence = evidence.merged_with(observation_evidence)
    return evidence, live_sysinfo_extended


def _probe_candidate_issues(
    result: HardwareProbeResult,
) -> tuple[DeviceCandidateIssue, ...]:
    return tuple(
        DeviceCandidateIssue(
            (
                DeviceCandidateIssueCode.HARDWARE_PROBE_SETUP_REQUIRED
                if issue.code is HardwareProbeIssueCode.SETUP_REQUIRED
                else DeviceCandidateIssueCode.HARDWARE_PROBE_FAILED
            ),
            issue.detail,
        )
        for issue in result.issues
    )


def _platform_probe_candidate_issues(
    platform_name: str,
    mounted: MountedVolume,
    result: HardwareProbeResult,
) -> tuple[DeviceCandidateIssue, ...]:
    if (
        platform_name != "linux"
        or mounted.physical_device.identifiers.usb_vendor_id != 0x05AC
    ):
        return ()
    properties = {
        property_.name: property_.value
        for observation in result.observations
        for property_ in observation.host_properties
    }
    rule_version = properties.get("ID_IOPENPOD_RULE_VERSION", "").strip()
    udev_product_serial = _valid_apple_product_serial(
        properties.get("ID_IOPENPOD_PRODUCT_SERIAL", "")
    )
    direct_product_serial = any(
        _valid_apple_product_serial(observation.unit_serial)
        for observation in result.observations
    )
    if rule_version == UDEV_RULE_VERSION:
        logger.info(
            "Linux iPod udev runtime properties: expected rule version %s "
            "observed for the current connection",
            UDEV_RULE_VERSION,
        )
    elif rule_version:
        logger.info(
            "Linux iPod udev runtime properties: cached version marker differs "
            "from bundled version %s",
            UDEV_RULE_VERSION,
        )
    else:
        logger.info(
            "Linux iPod udev runtime properties: identity-rule marker not observed "
            "for the current connection"
        )

    if udev_product_serial:
        logger.info(
            "Linux iPod udev runtime property supplied the product serial for the "
            "current connection; this does not prove the rule file is still installed"
        )
        return ()
    if direct_product_serial:
        logger.info(
            "Linux direct SCSI probing supplied the product serial; the udev "
            "identity rule was not used for this result"
        )
        return ()
    if rule_version == UDEV_RULE_VERSION:
        logger.info(
            "Linux iPod identity rule ran but did not publish a valid product serial"
        )
        return (
            DeviceCandidateIssue(
                DeviceCandidateIssueCode.HARDWARE_PROBE_FAILED,
                "The iOpenPod Linux identity rule ran, but this iPod did not "
                "publish its product serial. Reconnect it and refresh devices.",
            ),
        )
    return (
        DeviceCandidateIssue(
            DeviceCandidateIssueCode.HARDWARE_PROBE_SETUP_REQUIRED,
            "Linux needs the bundled 61-iopenpod.rules identity rule before "
            "iOpenPod can verify this model. Install it in /etc/udev/rules.d, "
            "reload udev rules, then reconnect the iPod.",
        ),
    )


def _current_text_identifier(
    value: str,
    source: str,
) -> tuple[DeviceIdentifier[str], ...]:
    normalized = value.strip()
    if not normalized:
        return ()
    return (
        DeviceIdentifier(
            normalized,
            source,
            EvidenceAuthority.CURRENT_HARDWARE,
        ),
    )


def _apple_product_serial_identifier(
    value: str,
    source: str,
) -> tuple[DeviceIdentifier[str], ...]:
    serial = _valid_apple_product_serial(value)
    return _current_text_identifier(serial, source)


def _valid_apple_product_serial(value: str) -> str:
    serial = value.replace(" ", "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{11,12}", serial, flags=re.ASCII):
        return ""
    return serial


def _read_device_metadata(
    session: FilesystemSession,
) -> tuple[DeviceEvidence, tuple[DeviceCandidateIssue, ...]]:
    evidence = DeviceEvidence()
    issues: list[DeviceCandidateIssue] = []
    readers = (
        (_SYSINFO_PATH, parse_sysinfo),
        (_SYSINFO_EXTENDED_PATH, parse_sysinfo_extended),
    )
    for path, parser in readers:
        try:
            if not session.exists(path):
                continue
            payload = session.read(path, max_bytes=_DEVICE_METADATA_LIMIT)
            evidence = evidence.merged_with(parser(payload, source=path.name))
        except (StorageError, ValueError) as error:
            issues.append(
                DeviceCandidateIssue(
                    DeviceCandidateIssueCode.METADATA_UNREADABLE,
                    f"{path.name}: {error}",
                )
            )
    return evidence, tuple(issues)


def _read_optional_metadata(
    session: FilesystemSession,
    path: DevicePath,
) -> tuple[bytes, FileFingerprint | None]:
    if not session.exists(path):
        return b"", None
    snapshot = session.read_snapshot(path, max_bytes=_DEVICE_METADATA_LIMIT)
    return snapshot.data, snapshot.fingerprint


def _read_device_guid(session: FilesystemSession) -> bytes:
    if not session.exists(_SYSINFO_PATH):
        return b""
    evidence = parse_sysinfo(
        session.read(_SYSINFO_PATH, max_bytes=_DEVICE_METADATA_LIMIT)
    )
    candidates = {item.value.removeprefix("0x") for item in evidence.transport_serials}
    if len(candidates) != 1:
        return b""
    try:
        result = bytes.fromhex(next(iter(candidates)))
    except ValueError:
        return b""
    return result if len(result) == 8 else b""


def _read_hash72_material(
    session: FilesystemSession,
    retained_database: bytes,
    guid: bytes,
) -> Hash72Material:
    from iPodDB.library import (
        parse_hash72_info,
        recover_hash72_material,
    )

    if session.exists(_HASHINFO_PATH):
        material = parse_hash72_info(
            session.read(_HASHINFO_PATH, max_bytes=_DEVICE_METADATA_LIMIT)
        )
        if not material.belongs_to_guid(guid):
            raise ValueError(
                "The device HashInfo UUID does not match its FireWire GUID"
            )
        return material
    return recover_hash72_material(retained_database)


def _read_sqlite_postprocess_commands(
    session: FilesystemSession,
    *,
    required: bool,
) -> tuple[tuple[str, ...], FilePrecondition]:
    if not session.exists(_SYSINFO_EXTENDED_PATH):
        if required:
            raise ValueError(
                "The device requires SQLite postprocess commands, but "
                "SysInfoExtended is missing"
            )
        return (), FilePrecondition(_SYSINFO_EXTENDED_PATH, None)
    snapshot = session.read_snapshot(
        _SYSINFO_EXTENDED_PATH, max_bytes=_DEVICE_METADATA_LIMIT
    )
    commands = _parse_sqlite_postprocess_commands(snapshot.data, required=required)
    return commands, FilePrecondition(_SYSINFO_EXTENDED_PATH, snapshot.fingerprint)


def _parse_sqlite_postprocess_commands(
    data: bytes,
    *,
    required: bool,
) -> tuple[str, ...]:
    import plistlib

    try:
        root_value: object = plistlib.loads(data)
    except (plistlib.InvalidFileException, ValueError) as error:
        raise ValueError("SysInfoExtended is not a readable property list") from error
    if not isinstance(root_value, dict):
        if required:
            raise ValueError(
                "The device requires SQLite postprocess commands, but "
                "SysInfoExtended has no property dictionary"
            )
        return ()
    root = cast("dict[object, object]", root_value)
    definition = root.get("com.apple.mobile.iTunes.SQLMusicLibraryPostProcessCommands")
    if definition is None:
        if required:
            raise ValueError(
                "The device requires SQLite postprocess commands, but "
                "SysInfoExtended does not contain them"
            )
        return ()
    if not isinstance(definition, dict):
        raise ValueError("SQLite postprocess metadata is not a dictionary")
    definition_values = cast("dict[object, object]", definition)
    sql_commands_value = definition_values.get("SQLCommands")
    version_sets_value = definition_values.get("UserVersionCommandSets")
    if not isinstance(sql_commands_value, dict) or not isinstance(
        version_sets_value, dict
    ):
        raise ValueError("SQLite postprocess metadata is incomplete")
    sql_commands = cast("dict[object, object]", sql_commands_value)
    version_sets = cast("dict[object, object]", version_sets_value)
    versions: list[tuple[int, object]] = []
    for key, value in version_sets.items():
        if not isinstance(key, str):
            continue
        try:
            number = int(key)
        except ValueError:
            continue
        if number > 0:
            versions.append((number, value))
    if not versions:
        raise ValueError("SQLite postprocess metadata has no command-set version")
    selected_value = max(versions, key=lambda item: item[0])[1]
    if not isinstance(selected_value, dict):
        raise ValueError("SQLite postprocess command set is malformed")
    selected = cast("dict[object, object]", selected_value)
    commands_value = selected.get("Commands")
    if not isinstance(commands_value, list):
        raise ValueError("SQLite postprocess command set is malformed")
    commands = cast("list[object]", commands_value)
    result: list[str] = []
    for command_name in commands:
        if not isinstance(command_name, str):
            raise ValueError("SQLite postprocess command reference is invalid")
        command = sql_commands.get(command_name)
        if not isinstance(command, str) or not command.strip():
            raise ValueError("SQLite postprocess command reference is invalid")
        result.append(command)
    if required and not result:
        raise ValueError("The required SQLite postprocess command set is empty")
    return tuple(result)


def _locate_database(
    session: FilesystemSession,
    *,
    compressed: bool = False,
) -> tuple[
    DevicePath | None,
    DeviceReadiness,
    tuple[DeviceCandidateIssue, ...],
]:
    issues: list[DeviceCandidateIssue] = []
    primary = _ITUNESCDB_PATH if compressed else _ITUNESDB_PATH
    if session.exists(primary):
        entry = session.stat(primary)
        if entry.kind is DeviceEntryKind.FILE and entry.size > 0:
            return primary, DeviceReadiness.READY, ()
        issues.append(
            DeviceCandidateIssue(
                DeviceCandidateIssueCode.DATABASE_EMPTY,
                source_text(
                    "{name} is empty or is not a regular file.", name=primary.name
                ),
            )
        )
    if not compressed and session.exists(_ITUNESCDB_PATH):
        entry = session.stat(_ITUNESCDB_PATH)
        if entry.kind is DeviceEntryKind.FILE and entry.size > 0:
            return None, DeviceReadiness.DATABASE_UNSUPPORTED, tuple(issues)
    return None, DeviceReadiness.DATABASE_MISSING, tuple(issues)


def _identification_readiness(status: IdentificationStatus) -> DeviceReadiness:
    return {
        IdentificationStatus.EXACT: DeviceReadiness.READY,
        IdentificationStatus.UNKNOWN: DeviceReadiness.UNKNOWN,
        IdentificationStatus.AMBIGUOUS: DeviceReadiness.AMBIGUOUS,
        IdentificationStatus.CONFLICTING: DeviceReadiness.CONFLICTING,
        IdentificationStatus.RECOVERY_MODE: DeviceReadiness.RECOVERY_MODE,
    }[status]


def _candidate_from(
    mounted: MountedVolume,
    identification: IdentificationResult,
    readiness: DeviceReadiness,
    issues: tuple[DeviceCandidateIssue, ...],
) -> DeviceCandidate:
    volume = mounted.volume
    physical_device = mounted.physical_device
    display_name = (
        volume.label.strip()
        or physical_device.display_name.strip()
        or "Removable Volume"
    )
    return DeviceCandidate(
        id=DeviceCandidateId(mounted.connection_generation.value),
        display_name=display_name,
        host_description=physical_device.display_name.strip(),
        bus=physical_device.bus.value,
        identification_status=identification.status,
        readiness=readiness,
        profile=identification.profile,
        total_bytes=volume.total_bytes,
        available_bytes=volume.available_bytes,
        issues=issues,
    )


def _require_same_profile(
    discovered: _CandidateRecord,
    current: _CandidateRecord,
) -> None:
    if not current.candidate.selectable:
        raise DeviceChangedError(
            "The selected iPod's identity or database changed. Refresh and try again."
        )
    if discovered.candidate.model_number != current.candidate.model_number:
        raise DeviceChangedError(
            "The selected connection now identifies as a different iPod."
        )


def _with_candidate_issue(
    record: _CandidateRecord,
    issue: DeviceCandidateIssue,
) -> _CandidateRecord:
    return replace(
        record,
        candidate=replace(
            record.candidate,
            issues=(*record.candidate.issues, issue),
        ),
    )


def _with_persistent_issue(
    record: _CandidateRecord,
    issue: DeviceCandidateIssue,
) -> _CandidateRecord:
    return replace(
        _with_candidate_issue(record, issue),
        persistent_issues=(*record.persistent_issues, issue),
    )


def _unreadable_artwork(
    record: _CandidateRecord,
    library: IPodLibrary,
    detail: str,
) -> tuple[_CandidateRecord, IPodLibrary, None]:
    return (
        _with_candidate_issue(
            record,
            DeviceCandidateIssue(
                DeviceCandidateIssueCode.ARTWORK_DATABASE_UNREADABLE,
                detail,
            ),
        ),
        library,
        None,
    )


def _unreadable_photos(
    record: _CandidateRecord,
    library: IPodLibrary,
    detail: str,
) -> tuple[_CandidateRecord, IPodLibrary, None]:
    return (
        _with_candidate_issue(
            record,
            DeviceCandidateIssue(
                DeviceCandidateIssueCode.PHOTOS_DATABASE_UNREADABLE,
                detail,
            ),
        ),
        library,
        None,
    )


def _display_cover_formats(profile: DeviceProfile) -> tuple[ArtworkFormat, ...]:
    native = profile.capabilities.artwork.cover_formats
    return native or (_DISPLAY_ONLY_F1060,)


def _finalize_committed_transaction(
    session: FilesystemSession, path: DevicePath
) -> None:
    try:
        flushed = session.finalize_committed_transaction(path)
    except TransactionDurabilityPendingError as error:
        _raise_if_cleanup_completed(session, path, error)
        raise
    if not flushed.complete:
        raise SyncCleanupCompletedError(
            source_text(
                "Recovery files were removed, but device flushing could not be confirmed. "
                "Safely eject before unplugging. {detail}",
                detail=flushed.detail,
            )
        )


def _raise_if_cleanup_completed(
    session: FilesystemSession,
    path: DevicePath,
    error: TransactionDurabilityPendingError,
) -> None:
    try:
        removed = not session.exists(path)
    except StorageError:
        return
    if removed:
        raise SyncCleanupCompletedError(
            source_text(
                "Sync recovery files were removed, but device flushing could not be confirmed. "
                "Safely eject before unplugging. {detail}",
                detail=str(error),
            )
        ) from error


def _terminal_transaction_journals(
    session: FilesystemSession,
) -> tuple[tuple[DevicePath, TransactionState], ...]:
    """Recognize crash recovery from durable device journals before any mutation."""
    recovery_root = DevicePath(".iopenpod-recovery")
    if not session.exists(recovery_root):
        return ()
    cleanup: list[tuple[DevicePath, TransactionState]] = []
    for entry in session.list_directory(recovery_root):
        if (
            entry.kind is not DeviceEntryKind.DIRECTORY
            or re.fullmatch(r"[0-9a-f]{32}", entry.path.name) is None
        ):
            continue
        journal = entry.path.joinpath("transaction.json")
        if not session.exists(journal):
            continue
        try:
            status = session.read_transaction_status(journal)
        except (StorageError, ValueError) as error:
            raise SyncRecoveryRequiredError(str(journal)) from error
        if status.state not in (TransactionState.COMMITTED, TransactionState.RESTORED):
            raise SyncRecoveryRequiredError(str(journal))
        # Host identities can change across reconnects. Completed journals are
        # not interrupted work, but only matching identities may offer cleanup.
        if status.identity_matches:
            cleanup.append((journal, status.state))
    return tuple(cleanup)


def _track_device_path(track: Track) -> DevicePath:
    location = track.metadata.location.strip()
    if not location:
        raise PlaybackSourceError(
            source_text("The selected Track has no media location.")
        )
    path = DevicePath(location)
    if not path.is_relative_to(_IPOD_CONTROL_PATH):
        raise PlaybackSourceError(
            source_text("The selected Track's media location is outside iPod_Control.")
        )
    return path


def _transaction_progress_text(event: TransactionProgress) -> str:
    parameters = {"completed": str(event.completed), "total": str(event.total)}
    labels = {
        TransactionState.STAGING: source_text(
            "Staging Library files: {completed} of {total}", **parameters
        ),
        TransactionState.PREPARED: source_text(
            "Prepared Library files: {completed} of {total}", **parameters
        ),
        TransactionState.PUBLISHING: source_text(
            "Publishing Library files: {completed} of {total}", **parameters
        ),
        TransactionState.COMMITTED: source_text(
            "Committed Library files: {completed} of {total}", **parameters
        ),
        TransactionState.RESTORING: source_text(
            "Restoring Library files: {completed} of {total}", **parameters
        ),
        TransactionState.RESTORED: source_text(
            "Restored Library files: {completed} of {total}", **parameters
        ),
    }
    return labels[event.state]


def _transaction_activity_progress(
    event: TransactionActivity,
    *,
    recovery: bool = False,
) -> WriteProgress:
    labels = (
        {
            TransactionActivityPhase.VERIFYING_STAGED: source_text(
                "Verifying staged files before publication before completing recovery…"
            ),
            TransactionActivityPhase.VERIFYING_WRITES: source_text(
                "Verifying files on the iPod before completing recovery…"
            ),
            TransactionActivityPhase.VERIFYING_RECOVERY: source_text(
                "Verifying Library files and recovery copies before completing recovery…"
            ),
            TransactionActivityPhase.CHECKING_DEPENDENCIES: source_text(
                "Checking retained Library files before completing recovery…"
            ),
            TransactionActivityPhase.INSPECTING: source_text(
                "Reading transaction files for verification before completing recovery…"
            ),
            TransactionActivityPhase.RECHECKING: source_text(
                "Rechecking captured file contents before completing recovery…"
            ),
            TransactionActivityPhase.FLUSHING: source_text(
                "Waiting for the iPod to finish writing data before completing recovery…"
            ),
        }
        if recovery
        else {
            TransactionActivityPhase.VERIFYING_STAGED: source_text(
                "Verifying staged files before publication…"
            ),
            TransactionActivityPhase.VERIFYING_WRITES: source_text(
                "Verifying files on the iPod…"
            ),
            TransactionActivityPhase.VERIFYING_RECOVERY: source_text(
                "Verifying Library files and recovery copies…"
            ),
            TransactionActivityPhase.CHECKING_DEPENDENCIES: source_text(
                "Checking retained Library files…"
            ),
            TransactionActivityPhase.INSPECTING: source_text(
                "Reading transaction files for verification…"
            ),
            TransactionActivityPhase.RECHECKING: source_text(
                "Rechecking captured file contents…"
            ),
            TransactionActivityPhase.FLUSHING: source_text(
                "Waiting for the iPod to finish writing data…"
            ),
        }
    )
    return WriteProgress(
        ("save.recovery." if recovery else "save.storage.") + event.phase.value,
        labels[event.phase],
        completed=event.completed,
        total=event.total,
        current_item=str(event.path or ""),
        unit="files",
    )


__all__ = [
    "DeviceAccessError",
    "DeviceArtworkLoadError",
    "DeviceCandidateNotFoundError",
    "DeviceChangedError",
    "DeviceCoordinationError",
    "DeviceCoordinator",
    "DeviceLibraryLoadError",
    "DeviceNotSelectableError",
    "DevicePhotoExportError",
    "DevicePhotoLoadError",
    "DeviceTrackExportError",
    "SyncCleanupCompletedError",
    "SyncRecoveryDeclinedError",
    "SyncRecoveryRequiredError",
    "SyncRecoveryRestoredError",
    "SyncRestoredCleanupPendingError",
]
