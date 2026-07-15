"""Public SyncEngine package boundary.

The preferred orchestration surface is :class:`iopenpod.sync.core.SyncEngine`.
App and GUI code should enter planning, execution, and quick database writes
through that facade so requests, progress, diagnostics, and validation all
flow through one lifecycle.

Lower-level modules remain importable from their concrete modules for focused
tests, but production orchestration should enter through the facade.
"""
from ._formats import IPOD_NATIVE_FORMATS
from .audio_fingerprint import (
    compute_fingerprint,
    get_or_compute_fingerprint_with_status,
    is_fpcalc_available,
    read_fingerprint,
    write_fingerprint,
)
from .backup_manager import BackupManager, BackupProgress, SnapshotInfo, get_device_display_name, get_device_identifier
from .contracts import (
    SYNC_DB_OVERHEAD_BYTES,
    SYNC_DB_WRITE_RESERVE_BYTES,
    SYNC_DISK_RESERVE_BYTES,
    SYNC_UNTIL_FULL_RESERVE_BYTES,
    StorageSummary,
    SyncAction,
    SyncItem,
    SyncOutcome,
    SyncPlan,
    SyncProgress,
    SyncRequest,
    sync_plan_required_free_bytes,
)
from .core import (
    EngineDiagnostic,
    EngineOperation,
    EngineOptions,
    EngineOutcome,
    EnginePlanContext,
    EngineProgress,
    EngineRequest,
    EngineStage,
    EngineTransactionPolicy,
    SyncEngine,
)
from .integrity import IntegrityReport, check_integrity
from .itunes_prefs import (
    DeviceTotals,
    ITunesPrefs,
    SyncHistoryEntry,
    check_library_owner,
    protect_from_itunes,
    read_prefs,
)
from .mapping import MappingFile, MappingManager, TrackMapping
from .pc_library import PCLibrary, PCTrack
from .photos import (
    PCPhotoLibrary,
    PhotoAlbum,
    PhotoDB,
    PhotoEditState,
    PhotoEntry,
    PhotoSyncPlan,
    apply_photo_sync_plan,
    build_photo_sync_plan,
    load_photo_preview,
    read_photo_db,
    scan_pc_photos,
)
from .review_selection import build_filtered_sync_plan, build_selected_photo_plan
from .spl_evaluator import spl_update, spl_update_all, spl_update_from_parsed
from .transcode_cache import CachedFile, CacheIndex, TranscodeCache
from .transcoder import (
    TranscodeResult,
    TranscodeTarget,
    find_ffprobe,
    is_ffmpeg_available,
    needs_transcoding,
    transcode,
)

__all__ = [
    # PC Library
    "PCLibrary",
    "PCTrack",
    # Sync plan contracts
    "SyncAction",
    "SyncPlan",
    "SyncItem",
    "StorageSummary",
    # Typed engine facade
    "SyncEngine",
    "EngineDiagnostic",
    "EngineOperation",
    "EngineOptions",
    "EngineOutcome",
    "EnginePlanContext",
    "EngineProgress",
    "EngineRequest",
    "EngineStage",
    "EngineTransactionPolicy",
    # Execution results
    "SyncOutcome",
    "SyncProgress",
    "SyncRequest",
    "SYNC_DISK_RESERVE_BYTES",
    "SYNC_DB_WRITE_RESERVE_BYTES",
    "SYNC_DB_OVERHEAD_BYTES",
    "SYNC_UNTIL_FULL_RESERVE_BYTES",
    "sync_plan_required_free_bytes",
    # Audio fingerprinting
    "compute_fingerprint",
    "read_fingerprint",
    "write_fingerprint",
    "get_or_compute_fingerprint_with_status",
    "is_fpcalc_available",
    # Mapping
    "MappingManager",
    "MappingFile",
    "TrackMapping",
    # Integrity
    "check_integrity",
    "IntegrityReport",
    # iTunes Prefs
    "read_prefs",
    "protect_from_itunes",
    "check_library_owner",
    "ITunesPrefs",
    "DeviceTotals",
    "SyncHistoryEntry",
    # Transcoding
    "transcode",
    "needs_transcoding",
    "is_ffmpeg_available",
    "find_ffprobe",
    "TranscodeTarget",
    "TranscodeResult",
    "IPOD_NATIVE_FORMATS",
    # Transcode cache
    "TranscodeCache",
    "CachedFile",
    "CacheIndex",
    # Backup manager
    "BackupManager",
    "SnapshotInfo",
    "BackupProgress",
    "get_device_identifier",
    "get_device_display_name",
    # Smart playlist evaluator
    "spl_update",
    "spl_update_from_parsed",
    "spl_update_all",
    # Photos
    "PhotoDB",
    "PhotoAlbum",
    "PhotoEntry",
    "PCPhotoLibrary",
    "PhotoEditState",
    "PhotoSyncPlan",
    "scan_pc_photos",
    "read_photo_db",
    "build_photo_sync_plan",
    "apply_photo_sync_plan",
    "load_photo_preview",
    # Review selection
    "build_filtered_sync_plan",
    "build_selected_photo_plan",
]
