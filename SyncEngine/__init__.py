"""
SyncEngine - Bridge between PC media library and iPod

Core components:
- PCLibrary: Scans PC media folder, extracts metadata
- FingerprintDiffEngine: Computes sync plan using acoustic fingerprints
- SyncExecutor: Executes sync plan (copy, transcode, update mapping)
- MappingManager: Tracks fingerprint → list[db_track_id] relationships
- Transcoder: Converts non-iPod formats (FLAC, etc.) to ALAC/AAC

"""

from ._formats import IPOD_NATIVE_FORMATS
from .audio_fingerprint import (
    compute_fingerprint,
    get_or_compute_fingerprint,
    is_fpcalc_available,
    read_fingerprint,
    write_fingerprint,
)
from .backup_manager import BackupManager, BackupProgress, SnapshotInfo, get_device_display_name, get_device_identifier
from .contracts import (
    StorageSummary,
    SyncAction,
    SyncItem,
    SyncOutcome,
    SyncPlan,
    SyncProgress,
    SyncRequest,
)
from .fingerprint_diff_engine import (
    FingerprintDiffEngine,
)
from .integrity import IntegrityReport, check_integrity
from .itunes_prefs import (
    DeviceTotals,
    ITunesPrefs,
    SyncHistoryEntry,
    check_library_owner,
    generate_library_id,
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
from .spl_evaluator import spl_update, spl_update_all, spl_update_from_parsed
from .sync_executor import SyncExecutor
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
    # Fingerprint-based sync (primary)
    "FingerprintDiffEngine",
    "SyncAction",
    "SyncPlan",
    "SyncItem",
    "StorageSummary",
    # Sync execution
    "SyncExecutor",
    "SyncOutcome",
    "SyncProgress",
    "SyncRequest",
    # Audio fingerprinting
    "compute_fingerprint",
    "read_fingerprint",
    "write_fingerprint",
    "get_or_compute_fingerprint",
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
    "generate_library_id",
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
]
