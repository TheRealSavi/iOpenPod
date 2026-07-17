"""
Content-Addressable Backup Manager for iPod devices.

Creates git-like snapshots of the ENTIRE iPod filesystem. Each snapshot is
a manifest listing every file and its SHA-256 hash. Files are stored once
by hash in a **shared** blob store — identical files across different devices
are stored only once, saving significant space for multi-iPod users.

Storage layout on PC:
    <backup_dir>/
        blobs/<aa>/<aabbccddee...>      # Shared content-addressable files
        <device_id>/
            snapshots/<timestamp>.json  # Manifest per backup
            hashcache.json              # Speed cache: (path,size,mtime) → hash

Restore is a full wipe-and-replace: the iPod is returned to the exact state
captured by the snapshot.
"""

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from iopenpod.device.durability import (
    durable_replace,
    durable_unlink,
    flush_filesystem,
    flush_parent_directory,
    flush_written_file,
)
from iopenpod.device.filesystem_profile import FilesystemProfile, inspect_filesystem_profile
from iopenpod.device.storage_safety import allocated_size, require_file_size_supported
from iopenpod.device.write_guard import DeviceWriteGuard, DeviceWriteSafetyError
from iopenpod.device.write_readiness import (
    inspect_device_write_readiness,
    revalidate_device_write_readiness,
    volume_lock_key,
)

logger = logging.getLogger(__name__)

# Default backup directory (XDG-aware on Linux)


def _resolve_default_backup_dir() -> str:
    try:
        from iopenpod.infrastructure.settings_paths import default_data_dir
        return os.path.join(default_data_dir(), "backups")
    except Exception:
        return os.path.join(os.path.expanduser("~"), "iOpenPod", "backups")


_DEFAULT_BACKUP_DIR = _resolve_default_backup_dir()

# Number of worker threads for parallel I/O.
# iPod is on USB (single bus) so diminishing returns above ~4,
# but we overlap iPod reads with PC blob writes + CPU hashing.
_NUM_WORKERS = 4

# OS-managed directories/files to skip during backup and never delete during restore.
# Stored in lower-case; comparisons use .lower() for case-insensitive matching on
# Windows (FAT32/exFAT are case-preserving but case-insensitive).
_OS_EXCLUDE_LOWER = frozenset({
    "system volume information",
    "$recycle.bin",
    ".trashes",
    ".fseventsd",
    ".spotlight-v100",
    ".ds_store",
    ".metadata_never_index",
    "thumbs.db",
    "desktop.ini",
})


def _is_excluded(name: str) -> bool:
    """Check if a filename/dirname should be excluded (case-insensitive)."""
    lower = name.lower()
    return lower in _OS_EXCLUDE_LOWER or lower.startswith("._")


# SHA-256 read buffer
_HASH_BUF_SIZE = 1024 * 1024  # 1 MB

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True, slots=True)
class _RestoreFile:
    relative_path: str
    file_hash: str
    size: int
    blob_path: Path


@dataclass(slots=True)
class _RestoreWriteSession:
    """Identity-retained, durable mutation session for one backup restore."""

    mount_path: Path
    filesystem_profile: FilesystemProfile
    device_dirty: bool = False
    finalized: bool = False
    finalize_attempted: bool = False

    def revalidate(self, *, probe_case_sensitivity: bool | None = None) -> None:
        self.filesystem_profile = revalidate_device_write_readiness(
            self.filesystem_profile,
            probe_case_sensitivity=probe_case_sensitivity,
        )

    def validate_target(self, relative_path: str, size: int) -> None:
        target = _resolve_restore_path(self.mount_path, relative_path)
        limit = int(self.filesystem_profile.max_component_length or 0)
        if limit > 0:
            relative_parts = target.relative_to(self.mount_path).parts
            too_long = next((part for part in relative_parts if len(part) > limit), None)
            if too_long is not None:
                raise DeviceWriteSafetyError(
                    f"The backup path component {too_long!r} exceeds this iPod "
                    f"filesystem's {limit}-character filename limit."
                )
        require_file_size_supported(
            size,
            max_file_size_bytes=self.filesystem_profile.max_file_size_bytes,
            display_name=relative_path,
        )

    def ensure_parent(self, relative_path: str) -> None:
        target = _resolve_restore_path(self.mount_path, relative_path)
        relative_parent_parts = target.parent.relative_to(self.mount_path).parts
        for depth in range(1, len(relative_parent_parts) + 1):
            self.revalidate()
            target = _resolve_restore_path(self.mount_path, relative_path)
            directory = self.mount_path.joinpath(*relative_parent_parts[:depth])
            if directory.exists():
                if not directory.is_dir():
                    raise DeviceWriteSafetyError(
                        f"Cannot restore {relative_path}: {directory} is not a directory."
                    )
                continue
            directory.mkdir()
            flush_parent_directory(directory)
            self.device_dirty = True

    def delete(self, relative_path: str) -> None:
        self.revalidate()
        target = _resolve_restore_path(self.mount_path, relative_path)
        durable_unlink(target)
        self.device_dirty = True

    def remove_empty_parents(self, relative_path: str) -> None:
        target = _resolve_restore_path(self.mount_path, relative_path)
        relative_parent_parts = target.parent.relative_to(self.mount_path).parts
        for depth in range(len(relative_parent_parts), 0, -1):
            parent = self.mount_path.joinpath(*relative_parent_parts[:depth])
            try:
                has_entries = next(parent.iterdir(), None) is not None
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise DeviceWriteSafetyError(
                    f"Could not inspect restore directory {parent}: {exc}"
                ) from exc
            if has_entries:
                break
            self.revalidate()
            _resolve_restore_path(self.mount_path, relative_path)
            if not parent.exists():
                continue
            try:
                parent.rmdir()
                flush_parent_directory(parent)
            except OSError as exc:
                raise DeviceWriteSafetyError(
                    f"Could not remove empty restore directory {parent}: {exc}"
                ) from exc
            self.device_dirty = True

    def install(self, restore_file: _RestoreFile) -> None:
        self.validate_target(restore_file.relative_path, restore_file.size)
        self.ensure_parent(restore_file.relative_path)
        self.revalidate()
        self._ensure_free_space(restore_file.size, restore_file.relative_path)
        target = _resolve_restore_path(self.mount_path, restore_file.relative_path)
        fd, raw_temp = tempfile.mkstemp(
            dir=str(target.parent),
            prefix=".iop-restore-",
            suffix=".tmp",
        )
        temp_path = Path(raw_temp)
        self.device_dirty = True
        try:
            with open(restore_file.blob_path, "rb") as source, os.fdopen(
                fd,
                "wb",
            ) as destination:
                fd = -1
                shutil.copyfileobj(source, destination, _HASH_BUF_SIZE)
                flush_written_file(destination)

            if _hash_file(temp_path) != restore_file.file_hash:
                raise DeviceWriteSafetyError(
                    f"The temporary restore copy for {restore_file.relative_path} "
                    "failed its SHA-256 verification."
                )

            self.revalidate()
            target = _resolve_restore_path(self.mount_path, restore_file.relative_path)
            if temp_path.parent != target.parent:
                raise DeviceWriteSafetyError(
                    "The restore destination changed before atomic replacement."
                )
            durable_replace(temp_path, target)

            if _hash_file(target) != restore_file.file_hash:
                raise DeviceWriteSafetyError(
                    f"The restored file {restore_file.relative_path} failed its "
                    "SHA-256 verification."
                )
        except Exception:
            if fd >= 0:
                os.close(fd)
            self._cleanup_temp_if_safe(temp_path)
            raise

    def finalize(self) -> None:
        self.finalize_attempted = True
        self.revalidate()
        flush_ok, flush_message = flush_filesystem(self.mount_path)
        if not flush_ok:
            raise DeviceWriteSafetyError(
                f"The restored iPod could not be flushed safely: {flush_message}"
            )
        self.revalidate()
        self.finalized = True
        logger.info("Backup restore durability barrier completed: %s", flush_message)

    def _ensure_free_space(self, size: int, relative_path: str) -> None:
        try:
            free = shutil.disk_usage(self.mount_path).free
        except OSError as exc:
            raise DeviceWriteSafetyError(
                f"Could not verify iPod free space before restoring "
                f"{relative_path}: {exc}"
            ) from exc
        required = allocated_size(
            size,
            self.filesystem_profile.allocation_unit_size,
        )
        if free < required:
            raise DeviceWriteSafetyError(
                f"The iPod does not have enough free space to atomically restore "
                f"{relative_path}. iOpenPod stopped before creating its temporary copy."
            )

    def _cleanup_temp_if_safe(self, temp_path: Path) -> None:
        try:
            self.revalidate()
            durable_unlink(temp_path, missing_ok=True)
        except Exception as exc:
            logger.warning(
                "Could not safely remove temporary restore file %s: %s",
                temp_path,
                exc,
            )


def _resolve_restore_path(ipod_root: Path, relative_path: str) -> Path:
    """Resolve one manifest path within the selected iPod root."""
    if not isinstance(relative_path, str) or not relative_path or "\x00" in relative_path:
        raise DeviceWriteSafetyError("The backup contains an invalid file path.")
    unified = relative_path.replace("\\", "/")
    if unified.startswith("/") or re.match(r"^[A-Za-z]:", unified):
        raise DeviceWriteSafetyError(
            f"The backup contains an absolute file path: {relative_path!r}."
        )
    parts = tuple(unified.split("/"))
    if any(not part or part in {".", ".."} or ":" in part for part in parts):
        raise DeviceWriteSafetyError(
            f"The backup contains an unsafe file path: {relative_path!r}."
        )
    if any(_is_excluded(part) for part in parts):
        raise DeviceWriteSafetyError(
            f"The backup path {relative_path!r} targets an OS-managed location."
        )

    try:
        root = ipod_root.resolve(strict=True)
    except OSError as exc:
        raise DeviceWriteSafetyError(
            f"The selected iPod root is unavailable: {exc}"
        ) from exc
    candidate = root.joinpath(*parts)
    current = root
    for part in parts:
        current /= part
        try:
            if current.is_symlink():
                raise DeviceWriteSafetyError(
                    f"The backup path {relative_path!r} crosses a symbolic link."
                )
        except OSError as exc:
            raise DeviceWriteSafetyError(
                f"Could not safely inspect backup path {relative_path!r}: {exc}"
            ) from exc
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise DeviceWriteSafetyError(
            f"The backup path escapes the selected iPod: {relative_path!r}."
        ) from exc
    return candidate


def _hash_file(path: Path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as file:
        while chunk := file.read(_HASH_BUF_SIZE):
            sha.update(chunk)
    return sha.hexdigest()


def _inspect_backup_source(
    mount_path: Path,
    *,
    reported_volume_format: str,
    expected_volume_identity_key: str,
) -> FilesystemProfile:
    """Capture and validate the scan-time identity for a read-only backup pass."""
    profile = inspect_filesystem_profile(
        mount_path,
        reported_volume_format=reported_volume_format,
    )
    if not profile.identity.is_complete:
        raise DeviceWriteSafetyError(
            "The connected iPod volume identity could not be verified before backup."
        )
    if volume_lock_key(profile) != expected_volume_identity_key:
        raise DeviceWriteSafetyError(
            "A different volume is mounted at the selected iPod path. "
            "iOpenPod stopped before creating a mixed-device backup."
        )
    logger.info(
        "Backup source filesystem: mount=%s actual=%s reported=%s identity=%s",
        profile.mount_path,
        profile.filesystem_type or "unknown",
        profile.reported_volume_format or "unknown",
        expected_volume_identity_key,
    )
    return profile


def _revalidate_backup_source(retained: FilesystemProfile) -> None:
    current = inspect_filesystem_profile(
        retained.inspection_path or retained.mount_path,
        reported_volume_format=retained.reported_volume_format,
    )
    if (
        not current.identity.is_complete
        or current.identity != retained.identity
        or current.filesystem_type != retained.filesystem_type
        or os.path.realpath(current.mount_path) != os.path.realpath(retained.mount_path)
    ):
        raise DeviceWriteSafetyError(
            "The selected iPod volume changed while its backup was being created. "
            "iOpenPod discarded the incomplete snapshot."
        )


@dataclass
class SnapshotInfo:
    """Summary information about a backup snapshot."""

    id: str  # timestamp string, e.g. "20260228_151400"
    timestamp: str  # ISO format datetime
    device_id: str
    device_name: str
    file_count: int = 0
    total_size: int = 0  # bytes
    # Delta vs previous snapshot (computed on list)
    files_added: int = 0
    files_removed: int = 0
    files_changed: int = 0
    # Device metadata (family, generation, color) for UI display
    device_meta: dict = field(default_factory=dict)

    @property
    def display_date(self) -> str:
        """Human-readable date string."""
        try:
            dt = datetime.fromisoformat(self.timestamp)
            return dt.strftime("%b %d, %Y · %I:%M %p")
        except Exception:
            return self.timestamp


@dataclass
class BackupProgress:
    """Progress info for backup/restore callbacks."""

    stage: str  # "hashing", "copying", "restoring", "cleaning"
    current: int
    total: int
    current_file: str = ""
    message: str = ""


class BackupManager:
    """
    Manages content-addressable backups of a full iPod device.

    Args:
        device_id: Unique identifier for the device (serial number or folder name).
        backup_dir: Root directory for all backups. Empty string uses default.
        device_name: Human-readable device name (for display in manifests).
    """

    def __init__(self, device_id: str, backup_dir: str = "",
                 device_name: str = "iPod",
                 device_meta: dict | None = None):
        self.device_id = self._sanitize_id(device_id)
        self.device_name = device_name
        self.device_meta = device_meta or {}
        self.backup_root = Path(backup_dir or _DEFAULT_BACKUP_DIR)
        self.device_dir = self.backup_root / self.device_id
        self.blobs_dir = self.backup_root / "blobs"  # Shared across devices
        self.snapshots_dir = self.device_dir / "snapshots"
        self.hashcache_path = self.device_dir / "hashcache.json"

        # One-time migration: move per-device blobs to the shared store
        self._migrate_device_blobs()

    @staticmethod
    def _sanitize_id(device_id: str) -> str:
        """Sanitize device_id for use as a directory name."""
        # Replace problematic characters
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in device_id)
        return safe or "unknown_device"

    # ── Public API ──────────────────────────────────────────────────────────

    def create_backup(
        self,
        ipod_path: str | Path,
        progress_callback: Callable[[BackupProgress], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        max_backups: int = 10,
        *,
        reported_volume_format: str = "",
        expected_volume_identity_key: str = "",
    ) -> SnapshotInfo | None:
        """
        Create a full backup of the iPod device.

        Walks the entire iPod root, hashes every file, stores new blobs,
        and writes a snapshot manifest. Prunes old snapshots if over limit.

        Args:
            ipod_path: Root path of the iPod (e.g. "D:\\").
            progress_callback: Called with BackupProgress updates.
            is_cancelled: If provided, called to check for cancellation.
            max_backups: Max snapshots to retain (0 = unlimited).

        Returns:
            SnapshotInfo for the new snapshot, or None if cancelled/failed.
        """
        ipod_root = Path(ipod_path)
        source_profile: FilesystemProfile | None = None
        if expected_volume_identity_key:
            source_profile = _inspect_backup_source(
                ipod_root,
                reported_volume_format=reported_volume_format,
                expected_volume_identity_key=expected_volume_identity_key,
            )

        # Ensure directories exist
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self.update_device_metadata()

        # Load hash cache for speed
        hash_cache = self._load_hash_cache()

        # Phase 1: Discover all files
        if progress_callback:
            progress_callback(BackupProgress(
                "scanning", 0, 0, message="Enumerating iPod files…"
            ))

        all_files = self._walk_device(ipod_root)
        if source_profile is not None:
            _revalidate_backup_source(source_profile)
        total_files = len(all_files)

        if total_files == 0:
            logger.warning("No files found on iPod — aborting backup")
            return None

        logger.info(f"Backup: found {total_files} files to process")

        if progress_callback:
            progress_callback(BackupProgress(
                "scanning", 0, total_files,
                message=f"Found {total_files:,} files, checking cache…"
            ))

        # Phase 2: Hash files and copy new blobs — parallelized
        #
        # Strategy: separate cached (stat-only) from uncached (need hash I/O).
        # Cached hits are processed instantly on the main thread.
        # Uncached files go to a thread pool for parallel hash + blob store.
        # This overlaps USB reads, SHA-256 CPU work, and local-disk writes.

        manifest_files: dict[str, dict] = {}
        total_size = 0
        new_blobs = 0
        skipped_files = 0
        skipped_samples: list[str] = []
        processed = 0

        # Pre-stat and partition into cached vs uncached
        cached_hits: list[tuple[str, Path, int, int, str]] = []   # rel, path, size, mtime_ns, hash
        uncached: list[tuple[str, Path, int, int]] = []           # rel, path, size, mtime_ns

        for rel_path, full_path in all_files:
            try:
                st = full_path.stat()
                # Use st_mtime_ns (integer nanoseconds) for the cache key.
                # Float st_mtime can lose precision across stat() calls on
                # Linux/macOS filesystems with nanosecond timestamps.
                cache_key = f"{rel_path}|{st.st_size}|{st.st_mtime_ns}"
                cached_hash = hash_cache.get(cache_key)
                if cached_hash:
                    cached_hits.append((rel_path, full_path, st.st_size, st.st_mtime_ns, cached_hash))
                else:
                    uncached.append((rel_path, full_path, st.st_size, st.st_mtime_ns))
            except (OSError, PermissionError) as e:
                skipped_files += 1
                if len(skipped_samples) < 5:
                    skipped_samples.append(f"{rel_path} ({e})")

        logger.info(
            f"Backup: {len(cached_hits)} cached, {len(uncached)} need hashing"
        )

        # 2a. Fast path — cached files (no hash I/O, just blob-exists check + copy)
        for rel_path, full_path, fsize, fmtime, file_hash in cached_hits:
            if is_cancelled and is_cancelled():
                logger.info("Backup cancelled by user")
                return None

            processed += 1
            if progress_callback and (processed == 1 or processed % 50 == 0):
                progress_callback(BackupProgress(
                    "hashing", processed, total_files,
                    current_file=rel_path,
                    message=f"Processing {processed:,}/{total_files:,}: {rel_path}"
                ))

            try:
                if self._store_blob(full_path, file_hash):
                    new_blobs += 1
                manifest_files[rel_path] = {
                    "hash": file_hash, "size": fsize, "mtime_ns": fmtime,
                }
                total_size += fsize
            except (OSError, PermissionError) as e:
                skipped_files += 1
                if len(skipped_samples) < 5:
                    skipped_samples.append(f"{rel_path} ({e})")

        if progress_callback and uncached:
            progress_callback(BackupProgress(
                "hashing", processed, total_files,
                message=f"{len(cached_hits):,} cached, hashing {len(uncached):,} remaining…"
            ))

        # 2b. Parallel hash + store for uncached files
        if uncached:
            lock = threading.Lock()

            def _process_file(rel_path: str, full_path: Path,
                              fsize: int, fmtime: int):
                """Hash a file and store its blob. Returns result tuple."""
                file_hash = self._hash_file(full_path)
                is_new = self._store_blob(full_path, file_hash)
                return rel_path, fsize, fmtime, file_hash, is_new

            with ThreadPoolExecutor(max_workers=_NUM_WORKERS) as pool:
                futures = {
                    pool.submit(_process_file, rp, fp, sz, mt): rp
                    for rp, fp, sz, mt in uncached
                }

                for future in as_completed(futures):
                    if is_cancelled and is_cancelled():
                        pool.shutdown(wait=False, cancel_futures=True)
                        logger.info("Backup cancelled by user")
                        return None

                    processed += 1
                    try:
                        rel_path, fsize, fmtime, file_hash, is_new = future.result()

                        with lock:
                            hash_cache[f"{rel_path}|{fsize}|{fmtime}"] = file_hash
                            manifest_files[rel_path] = {
                                "hash": file_hash, "size": fsize, "mtime_ns": fmtime,
                            }
                            total_size += fsize
                            if is_new:
                                new_blobs += 1

                        if progress_callback:
                            progress_callback(BackupProgress(
                                "hashing", processed, total_files,
                                current_file=rel_path,
                                message=f"Hashing {processed}/{total_files}: {rel_path}"
                            ))

                    except (OSError, PermissionError) as e:
                        rp = futures[future]
                        with lock:
                            skipped_files += 1
                            if len(skipped_samples) < 5:
                                skipped_samples.append(f"{rp} ({e})")

        if source_profile is not None:
            _revalidate_backup_source(source_profile)
            if skipped_files:
                examples = "; ".join(skipped_samples)
                raise DeviceWriteSafetyError(
                    f"The iPod backup could not read {skipped_files} file(s). "
                    f"iOpenPod discarded the incomplete snapshot. {examples}"
                )

        # Phase 2c: Check for duplicate — skip saving if nothing changed
        latest_snap = self._get_latest_snapshot_files()
        if latest_snap is not None:
            prev_hash_map = {rp: fi.get("hash") for rp, fi in latest_snap.items()}
            new_hash_map = {rp: fi.get("hash") for rp, fi in manifest_files.items()}
            if prev_hash_map == new_hash_map:
                logger.info("Backup: no changes since last snapshot — skipping")
                self._save_hash_cache(hash_cache)
                if progress_callback:
                    progress_callback(BackupProgress(
                        "no_changes", total_files, total_files,
                        message="No changes since last backup"
                    ))
                return None

        # Phase 3: Write manifest
        if source_profile is not None:
            _revalidate_backup_source(source_profile)
        now = datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S")

        # Avoid collision if two backups happen in the same second
        manifest_path = self.snapshots_dir / f"{timestamp}.json"
        if manifest_path.exists():
            timestamp = now.strftime("%Y%m%d_%H%M%S") + f"_{now.microsecond}"
            manifest_path = self.snapshots_dir / f"{timestamp}.json"

        manifest = {
            "version": 2,
            "id": timestamp,
            "timestamp": now.isoformat(),
            "device_id": self.device_id,
            "device_name": self.device_name,
            "device_meta": self.device_meta,
            "file_count": len(manifest_files),
            "total_size": total_size,
            "files": manifest_files,
        }

        tmp_path = manifest_path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, ensure_ascii=False)
            os.replace(str(tmp_path), str(manifest_path))
        except Exception as e:
            logger.error(f"Failed to write snapshot manifest: {e}")
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return None

        # Prune stale hash cache entries (files no longer in this manifest)
        live_keys = {
            f"{rp}|{fi['size']}|{fi['mtime_ns']}"
            for rp, fi in manifest_files.items()
        }
        stale = [k for k in hash_cache if k not in live_keys]
        if stale:
            for k in stale:
                del hash_cache[k]
            logger.debug(f"Hash cache: pruned {len(stale)} stale entries")

        # Save updated hash cache
        self._save_hash_cache(hash_cache)

        # Prune old snapshots
        if max_backups > 0:
            self._prune_snapshots(max_backups)

        info = SnapshotInfo(
            id=timestamp,
            timestamp=manifest["timestamp"],
            device_id=self.device_id,
            device_name=self.device_name,
            file_count=len(manifest_files),
            total_size=total_size,
            device_meta=self.device_meta,
        )

        if skipped_files:
            examples = "; examples: " + ", ".join(skipped_samples) if skipped_samples else ""
            logger.warning(
                f"Backup complete with {skipped_files} skipped files: "
                f"{len(manifest_files)} files stored, "
                f"{total_size / (1024**3):.2f} GB, {new_blobs} new blobs"
                f"{examples}"
            )
        else:
            logger.info(
                f"Backup complete: {len(manifest_files)} files, "
                f"{total_size / (1024**3):.2f} GB, {new_blobs} new blobs"
            )

        if progress_callback:
            msg = f"Backup complete — {len(manifest_files)} files, {new_blobs} new"
            if skipped_files:
                msg += f" ({skipped_files} files could not be read)"
            progress_callback(BackupProgress(
                "complete", total_files, total_files, message=msg
            ))

        return info

    def restore_backup(
        self,
        snapshot_id: str,
        ipod_path: str | Path,
        progress_callback: Callable[[BackupProgress], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        *,
        reported_volume_format: str = "",
        expected_volume_identity_key: str = "",
    ) -> bool:
        """Restore a snapshot with the existing delete-then-delta-copy phases."""
        ipod_root = Path(os.path.realpath(ipod_path))
        manifest = self._load_manifest(snapshot_id)
        if not manifest:
            logger.error("Snapshot %s not found", snapshot_id)
            return False

        if progress_callback:
            progress_callback(BackupProgress(
                "verifying",
                0,
                0,
                message="Verifying backup integrity…",
            ))
        target_files = self._validated_restore_files(ipod_root, manifest)
        if not target_files:
            logger.warning("Snapshot has no files — nothing to restore")
            return False

        filesystem_profile = inspect_device_write_readiness(
            ipod_root,
            reported_volume_format=reported_volume_format,
        )
        current_volume_key = volume_lock_key(filesystem_profile)
        if (
            expected_volume_identity_key
            and current_volume_key != expected_volume_identity_key
        ):
            raise DeviceWriteSafetyError(
                "A different volume is mounted at the selected iPod path. "
                "iOpenPod stopped before restoring the backup."
            )

        logger.info(
            "Restore: %s files from snapshot %s",
            len(target_files),
            snapshot_id,
        )
        with DeviceWriteGuard(ipod_root, volume_key=current_volume_key):
            session = _RestoreWriteSession(ipod_root, filesystem_profile)
            session.revalidate(probe_case_sensitivity=True)
            try:
                return self._restore_backup_guarded(
                    target_files,
                    session,
                    progress_callback=progress_callback,
                    is_cancelled=is_cancelled,
                )
            finally:
                if session.device_dirty and not session.finalize_attempted:
                    session.finalize()

    def _validated_restore_files(
        self,
        ipod_root: Path,
        manifest: dict,
    ) -> dict[str, _RestoreFile]:
        raw_files = manifest.get("files")
        if not isinstance(raw_files, dict):
            raise DeviceWriteSafetyError(
                "The backup manifest has an invalid files section."
            )

        result: dict[str, _RestoreFile] = {}
        casefold_paths: set[str] = set()
        verified_blobs: set[str] = set()
        for raw_relative_path, raw_info in raw_files.items():
            if not isinstance(raw_relative_path, str):
                raise DeviceWriteSafetyError(
                    "The backup manifest contains a non-text file path."
                )
            target = _resolve_restore_path(ipod_root, raw_relative_path)
            relative_path = target.relative_to(ipod_root).as_posix()
            folded = relative_path.casefold()
            if relative_path in result or folded in casefold_paths:
                raise DeviceWriteSafetyError(
                    f"The backup contains colliding file paths: {relative_path!r}."
                )
            if not isinstance(raw_info, dict):
                raise DeviceWriteSafetyError(
                    f"The backup entry for {relative_path!r} is invalid."
                )
            file_hash = raw_info.get("hash")
            size = raw_info.get("size")
            if not isinstance(file_hash, str) or not _SHA256_RE.fullmatch(file_hash):
                raise DeviceWriteSafetyError(
                    f"The backup entry for {relative_path!r} has an invalid SHA-256 hash."
                )
            if isinstance(size, bool) or not isinstance(size, int) or size < 0:
                raise DeviceWriteSafetyError(
                    f"The backup entry for {relative_path!r} has an invalid file size."
                )
            normalized_hash = file_hash.casefold()
            blob_path = self._blob_path(normalized_hash)
            try:
                blob_size = blob_path.stat().st_size
            except OSError as exc:
                raise DeviceWriteSafetyError(
                    f"The backup blob for {relative_path!r} is unavailable: {exc}"
                ) from exc
            if blob_size != size:
                raise DeviceWriteSafetyError(
                    f"The backup blob for {relative_path!r} has the wrong size."
                )
            if normalized_hash not in verified_blobs:
                try:
                    actual_hash = _hash_file(blob_path)
                except OSError as exc:
                    raise DeviceWriteSafetyError(
                        f"The backup blob for {relative_path!r} could not be verified: {exc}"
                    ) from exc
                if actual_hash != normalized_hash:
                    raise DeviceWriteSafetyError(
                        f"The backup blob for {relative_path!r} failed SHA-256 verification."
                    )
                verified_blobs.add(normalized_hash)

            result[relative_path] = _RestoreFile(
                relative_path=relative_path,
                file_hash=normalized_hash,
                size=size,
                blob_path=blob_path,
            )
            casefold_paths.add(folded)

        folded_files = {path.casefold() for path in result}
        for relative_path in result:
            parts = relative_path.split("/")
            if any(
                "/".join(parts[:depth]).casefold() in folded_files
                for depth in range(1, len(parts))
            ):
                raise DeviceWriteSafetyError(
                    f"The backup path {relative_path!r} is nested beneath another file."
                )
        return result

    def _restore_backup_guarded(
        self,
        target_files: dict[str, _RestoreFile],
        session: _RestoreWriteSession,
        *,
        progress_callback: Callable[[BackupProgress], None] | None,
        is_cancelled: Callable[[], bool] | None,
    ) -> bool:
        if progress_callback:
            progress_callback(BackupProgress(
                "scanning",
                0,
                0,
                message="Enumerating and verifying iPod files…",
            ))
        ipod_files = self._walk_device(session.mount_path, fail_on_error=True)
        current_hashes: dict[str, str] = {}
        total_current = len(ipod_files)
        for index, (relative_path, full_path) in enumerate(ipod_files, start=1):
            if is_cancelled and is_cancelled():
                logger.info("Restore cancelled during scan")
                return False
            session.revalidate()
            try:
                current_hashes[relative_path] = _hash_file(full_path)
            except OSError as exc:
                raise DeviceWriteSafetyError(
                    f"Could not verify existing iPod file {relative_path}: {exc}"
                ) from exc
            if progress_callback and (index == total_current or index % 10 == 0):
                progress_callback(BackupProgress(
                    "scanning",
                    index,
                    total_current,
                    current_file=relative_path,
                    message=f"Verifying {index:,}/{total_current:,} iPod files…",
                ))
        session.revalidate()

        target_keys = set(target_files)
        current_keys = set(current_hashes)
        to_add = target_keys - current_keys
        to_remove = current_keys - target_keys
        to_replace = {
            path
            for path in target_keys & current_keys
            if target_files[path].file_hash != current_hashes[path]
        }
        to_copy = to_add | to_replace
        skipped = len(target_keys & current_keys) - len(to_replace)
        logger.info(
            "Restore delta: %s add, %s replace, %s remove, %s unchanged",
            len(to_add),
            len(to_replace),
            len(to_remove),
            skipped,
        )

        self._preflight_restore_capacity(
            target_files,
            to_copy,
            to_remove,
            to_replace,
            session,
        )

        if to_remove and progress_callback:
            progress_callback(BackupProgress(
                "cleaning",
                0,
                len(to_remove),
                message=f"Removing {len(to_remove)} files…",
            ))
        for index, relative_path in enumerate(sorted(to_remove), start=1):
            if is_cancelled and is_cancelled():
                logger.warning("Restore cancelled after device changes began")
                return False
            session.delete(relative_path)
            session.remove_empty_parents(relative_path)
            if progress_callback:
                progress_callback(BackupProgress(
                    "cleaning",
                    index,
                    len(to_remove),
                    current_file=relative_path,
                    message=f"Removing {index}/{len(to_remove)}: {relative_path}",
                ))

        for index, relative_path in enumerate(sorted(to_copy), start=1):
            if is_cancelled and is_cancelled():
                logger.warning("Restore cancelled after device changes began")
                return False
            session.install(target_files[relative_path])
            if progress_callback:
                progress_callback(BackupProgress(
                    "restoring",
                    index,
                    len(to_copy),
                    current_file=relative_path,
                    message=f"Copying {index}/{len(to_copy)}: {relative_path}",
                ))

        self._verify_restored_device(target_files, session)
        session.finalize()
        logger.info(
            "Restore complete: +%s add, ~%s replace, −%s remove, %s skipped",
            len(to_add),
            len(to_replace),
            len(to_remove),
            skipped,
        )
        if progress_callback:
            parts = []
            if to_add:
                parts.append(f"+{len(to_add)} added")
            if to_replace:
                parts.append(f"~{len(to_replace)} replaced")
            if to_remove:
                parts.append(f"−{len(to_remove)} removed")
            parts.append(f"{skipped} unchanged")
            progress_callback(BackupProgress(
                "complete",
                len(target_files),
                len(target_files),
                message=f"Restore complete — {', '.join(parts)}",
            ))
        return True

    def _preflight_restore_capacity(
        self,
        target_files: dict[str, _RestoreFile],
        to_copy: set[str],
        to_remove: set[str],
        to_replace: set[str],
        session: _RestoreWriteSession,
    ) -> None:
        for relative_path in sorted(to_copy):
            restore_file = target_files[relative_path]
            session.validate_target(relative_path, restore_file.size)

        session.revalidate()
        try:
            free_now = shutil.disk_usage(session.mount_path).free
        except OSError as exc:
            raise DeviceWriteSafetyError(
                f"Could not verify iPod free space before restore: {exc}"
            ) from exc
        allocation_unit = session.filesystem_profile.allocation_unit_size
        freed_by_removals = 0
        for relative_path in to_remove:
            target = _resolve_restore_path(session.mount_path, relative_path)
            try:
                freed_by_removals += allocated_size(target.stat().st_size, allocation_unit)
            except OSError as exc:
                raise DeviceWriteSafetyError(
                    f"Could not inspect {relative_path} before restore: {exc}"
                ) from exc

        consumed = 0
        peak_required = 0
        for relative_path in sorted(to_copy):
            new_size = allocated_size(target_files[relative_path].size, allocation_unit)
            old_size = 0
            if relative_path in to_replace:
                target = _resolve_restore_path(session.mount_path, relative_path)
                try:
                    old_size = allocated_size(target.stat().st_size, allocation_unit)
                except OSError as exc:
                    raise DeviceWriteSafetyError(
                        f"Could not inspect {relative_path} before replacement: {exc}"
                    ) from exc
            peak_required = max(peak_required, consumed + new_size)
            consumed += new_size - old_size

        if free_now + freed_by_removals < peak_required:
            raise DeviceWriteSafetyError(
                "The iPod does not have enough free space for the restore's "
                "atomic temporary files. iOpenPod stopped before deleting anything."
            )

    def _verify_restored_device(
        self,
        target_files: dict[str, _RestoreFile],
        session: _RestoreWriteSession,
    ) -> None:
        session.revalidate()
        restored_files = self._walk_device(session.mount_path, fail_on_error=True)
        restored_paths = {relative_path for relative_path, _path in restored_files}
        if restored_paths != set(target_files):
            missing = sorted(set(target_files) - restored_paths)
            extra = sorted(restored_paths - set(target_files))
            detail = missing[0] if missing else extra[0]
            raise DeviceWriteSafetyError(
                f"The restored iPod does not match the backup manifest: {detail}."
            )
        for relative_path, full_path in restored_files:
            session.revalidate()
            try:
                actual_hash = _hash_file(full_path)
            except OSError as exc:
                raise DeviceWriteSafetyError(
                    f"Could not verify restored file {relative_path}: {exc}"
                ) from exc
            if actual_hash != target_files[relative_path].file_hash:
                raise DeviceWriteSafetyError(
                    f"The restored file {relative_path} failed final SHA-256 verification."
                )
        session.revalidate()

    def list_snapshots(self) -> list[SnapshotInfo]:
        """
        List all available snapshots for this device, newest first.

        Computes delta stats (files added/removed/changed) vs the
        previous snapshot for each entry.

        Optimised: only loads the full ``files`` dict for adjacent pairs
        that need delta computation, and discards them immediately to
        keep memory pressure low on large libraries.
        """
        if not self.snapshots_dir.exists():
            return []

        manifest_paths = sorted(
            self.snapshots_dir.glob("*.json"),
            key=lambda p: p.stem,
            reverse=True,
        )

        if not manifest_paths:
            return []

        # ── Build SnapshotInfo list ─────────────────────────────────
        #
        # Load manifests lazily one at a time for delta computation.
        # Each iteration loads the current manifest, extracts its file
        # dict for delta computation with the *previous* iteration,
        # then discards the file dict.  At most TWO file dicts are
        # in memory at once.
        snapshots: list[SnapshotInfo] = []
        prev_files: dict | None = None   # files dict of the "newer" snapshot

        for mf in manifest_paths:
            try:
                with open(mf, encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
                logger.warning(f"Could not read snapshot {mf.name}: {e}")
                continue

            info = SnapshotInfo(
                id=data.get("id", mf.stem),
                timestamp=data.get("timestamp", ""),
                device_id=data.get("device_id", self.device_id),
                device_name=data.get("device_name", "iPod"),
                file_count=data.get("file_count", 0),
                total_size=data.get("total_size", 0),
                device_meta=data.get("device_meta", {}),
            )

            # Delta: compare *previous* SnapshotInfo (newer) against this one
            cur_files = data.get("files", {})
            if prev_files is not None:
                # prev_files is the *newer* snapshot, cur_files the *older*
                snapshots[-1].files_added, snapshots[-1].files_removed, snapshots[-1].files_changed = (
                    self._compute_delta(cur_files, prev_files)
                )

            # Keep only the files dict, drop the full manifest to free memory
            prev_files = cur_files
            del data

            snapshots.append(info)

        return snapshots

    def garbage_collect(self):
        """Remove blob files not referenced by any snapshot."""
        self._gc_blobs()

    def delete_snapshot(self, snapshot_id: str) -> bool:
        """Delete a snapshot and garbage-collect unreferenced blobs."""
        manifest_path = self.snapshots_dir / f"{snapshot_id}.json"
        if not manifest_path.exists():
            logger.warning(f"Snapshot {snapshot_id} not found for deletion")
            return False

        try:
            manifest_path.unlink()
            logger.info(f"Deleted snapshot {snapshot_id}")
        except OSError as e:
            logger.error(f"Could not delete snapshot {snapshot_id}: {e}")
            return False

        # Garbage collect unreferenced blobs
        self._gc_blobs()
        return True

    def update_device_metadata(
        self,
        *,
        device_name: str | None = None,
        device_meta: dict | None = None,
    ) -> int:
        """Refresh device display metadata in existing snapshot manifests.

        Snapshot manifests store the display name so they can be shown without
        the device connected. When the iPod's name changes, update those
        manifests in place instead of waiting for the next content-changing
        snapshot.

        Returns the number of manifest files updated.
        """
        name = str(device_name if device_name is not None else self.device_name).strip()
        meta = self.device_meta if device_meta is None else (device_meta or {})
        should_update_meta = bool(meta)

        if not name and not should_update_meta:
            return 0
        if not self.snapshots_dir.exists():
            return 0

        updated = 0
        for manifest_path in sorted(self.snapshots_dir.glob("*.json")):
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    manifest = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
                logger.warning("Could not read snapshot %s for metadata refresh: %s", manifest_path.name, exc)
                continue

            changed = False
            if name and manifest.get("device_name") != name:
                manifest["device_name"] = name
                changed = True
            if should_update_meta and manifest.get("device_meta", {}) != meta:
                manifest["device_meta"] = meta
                changed = True
            if not changed:
                continue

            tmp_path = manifest_path.with_suffix(".tmp")
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, indent=2, ensure_ascii=False)
                os.replace(str(tmp_path), str(manifest_path))
                updated += 1
            except OSError as exc:
                logger.warning("Could not refresh metadata for snapshot %s: %s", manifest_path.name, exc)
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass

        if updated:
            logger.info("Updated device metadata in %s backup manifest(s) for %s", updated, self.device_id)
        return updated

    def get_backup_size(self) -> int:
        """Get total size of this device's backup data.

        Counts manifest/cache files directly, plus the size of all blobs
        referenced by this device's snapshots (shared blobs counted in full
        since they are required for restore).
        """
        if not self.device_dir.exists():
            return 0

        total = 0
        # Manifests + hash cache
        for root, _dirs, files in os.walk(self.device_dir):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass

        # Referenced blobs
        referenced: set[str] = set()
        if self.snapshots_dir.exists():
            for mf in self.snapshots_dir.glob("*.json"):
                try:
                    with open(mf, encoding="utf-8") as f:
                        data = json.load(f)
                except (json.JSONDecodeError, UnicodeDecodeError, OSError):
                    continue
                for file_info in data.get("files", {}).values():
                    h = file_info.get("hash")
                    if h:
                        referenced.add(h)

        for h in referenced:
            bp = self._blob_path(h)
            try:
                total += bp.stat().st_size
            except OSError:
                pass

        return total

    def has_snapshots(self) -> bool:
        """Quick check if any snapshots exist for this device."""
        if not self.snapshots_dir.exists():
            return False
        return any(self.snapshots_dir.glob("*.json"))

    @classmethod
    def list_all_devices(cls, backup_dir: str = "") -> list[dict]:
        """List all devices that have backups, without requiring a connected device.

        Returns a list of dicts:
            [{"device_id": str, "device_name": str, "snapshot_count": int,
              "device_meta": dict}]
        """
        root = Path(backup_dir or _DEFAULT_BACKUP_DIR)
        if not root.exists():
            return []

        devices: list[dict] = []
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            # Skip the shared blobs directory
            if child.name == "blobs":
                continue
            snap_dir = child / "snapshots"
            if not snap_dir.is_dir():
                continue
            manifests = sorted(snap_dir.glob("*.json"), key=lambda p: p.stem, reverse=True)
            if not manifests:
                continue

            # Read device_name and device_meta from the latest manifest
            device_name = child.name
            device_meta: dict = {}
            try:
                with open(manifests[0], encoding="utf-8") as f:
                    data = json.load(f)
                device_name = data.get("device_name", child.name)
                device_meta = data.get("device_meta", {})
            except (json.JSONDecodeError, UnicodeDecodeError, OSError):
                pass

            devices.append({
                "device_id": child.name,
                "device_name": device_name,
                "snapshot_count": len(manifests),
                "device_meta": device_meta,
            })

        return devices

    # ── Internal helpers ────────────────────────────────────────────────────

    def _get_latest_snapshot_files(self) -> dict | None:
        """Load the files dict from the most recent snapshot, or None."""
        if not self.snapshots_dir.exists():
            return None
        manifests = sorted(
            self.snapshots_dir.glob("*.json"),
            key=lambda p: p.stem,
            reverse=True,
        )
        if not manifests:
            return None
        try:
            with open(manifests[0], encoding="utf-8") as f:
                data = json.load(f)
            return data.get("files")
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return None

    def _walk_device(
        self,
        ipod_root: Path,
        *,
        fail_on_error: bool = False,
    ) -> list[tuple[str, Path]]:
        """
        Walk the entire iPod root and return (relative_path, full_path) pairs.

        Skips OS-managed directories (case-insensitive). Dot-directories like
        .iOpenPod are kept — only the explicit exclusion set is filtered.
        """
        results: list[tuple[str, Path]] = []

        def _raise_walk_error(exc: OSError) -> None:
            raise exc

        for root, dirs, files in os.walk(
            ipod_root,
            followlinks=False,
            onerror=_raise_walk_error if fail_on_error else None,
        ):
            # Filter out OS-managed directories in-place (single pass)
            dirs[:] = [d for d in dirs if not _is_excluded(d)]

            if fail_on_error:
                for dirname in dirs:
                    directory = Path(root) / dirname
                    if directory.is_symlink():
                        raise DeviceWriteSafetyError(
                            f"Restore stopped because {directory} is a symbolic link."
                        )

            for filename in files:
                if _is_excluded(filename):
                    continue

                full_path = Path(root) / filename

                # Skip symlinks — avoid following links outside the device,
                # and iPod filesystems (FAT32/exFAT) don't support them anyway.
                if full_path.is_symlink():
                    if fail_on_error:
                        raise DeviceWriteSafetyError(
                            f"Restore stopped because {full_path} is a symbolic link."
                        )
                    continue

                try:
                    rel_path = full_path.relative_to(ipod_root).as_posix()
                except ValueError:
                    continue

                results.append((rel_path, full_path))

        return results

    def _hash_file(self, path: Path) -> str:
        """Compute SHA-256 hash of a file."""
        sha = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(_HASH_BUF_SIZE)
                if not chunk:
                    break
                sha.update(chunk)
        return sha.hexdigest()

    def _blob_path(self, file_hash: str) -> Path:
        """Get the storage path for a blob by its hash."""
        return self.blobs_dir / file_hash[:2] / file_hash

    def _store_blob(self, source_path: Path, file_hash: str) -> bool:
        """
        Store a file as a blob if it doesn't already exist.

        Thread-safe: uses copy-to-temp + atomic rename so concurrent
        threads writing the same hash don't corrupt each other.

        Returns True if a new blob was created, False if it already existed.
        """
        blob_path = self._blob_path(file_hash)
        if blob_path.exists():
            return False

        blob_path.parent.mkdir(parents=True, exist_ok=True)

        # Write to a per-thread temp file, then atomically move into place.
        # If two threads race on the same hash the second os.replace is a
        # harmless overwrite (same content, same hash).
        fd, tmp_path = tempfile.mkstemp(
            dir=str(blob_path.parent), prefix=".blob_",
        )
        try:
            os.close(fd)
            shutil.copy2(str(source_path), tmp_path)
            os.replace(tmp_path, str(blob_path))
            return True
        except (OSError, PermissionError) as e:
            logger.error(f"Failed to store blob {file_hash[:16]}…: {e}")
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _load_manifest(self, snapshot_id: str) -> dict | None:
        """Load a snapshot manifest by its ID."""
        manifest_path = self.snapshots_dir / f"{snapshot_id}.json"
        if not manifest_path.exists():
            return None
        try:
            with open(manifest_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
            logger.error(f"Could not read snapshot {snapshot_id}: {e}")
            return None

    def _load_hash_cache(self) -> dict[str, str]:
        """Load the hash cache from disk."""
        if not self.hashcache_path.exists():
            return {}
        try:
            with open(self.hashcache_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return {}

    def _save_hash_cache(self, cache: dict[str, str]):
        """Save the hash cache to disk."""
        self.device_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.hashcache_path.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
            os.replace(str(tmp), str(self.hashcache_path))
        except Exception as e:
            logger.warning(f"Could not save hash cache: {e}")
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def _migrate_device_blobs(self):
        """One-time migration: move per-device blobs to the shared store.

        Old layout had blobs at <device_dir>/blobs/. If that directory exists,
        move all blobs to <backup_root>/blobs/ and remove the old directory.
        """
        old_blobs = self.device_dir / "blobs"
        if not old_blobs.exists() or not old_blobs.is_dir():
            return

        # Ensure shared blobs dir exists
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        migrated = 0

        for prefix_dir in old_blobs.iterdir():
            if not prefix_dir.is_dir():
                continue
            dest_prefix = self.blobs_dir / prefix_dir.name
            dest_prefix.mkdir(parents=True, exist_ok=True)
            for blob_file in prefix_dir.iterdir():
                dest = dest_prefix / blob_file.name
                if dest.exists():
                    # Already in shared store (e.g. another device had it)
                    try:
                        blob_file.unlink()
                    except OSError:
                        pass
                else:
                    try:
                        os.replace(str(blob_file), str(dest))
                        migrated += 1
                    except OSError:
                        # Cross-device move: copy + delete
                        try:
                            shutil.copy2(str(blob_file), str(dest))
                            blob_file.unlink()
                            migrated += 1
                        except OSError as e:
                            logger.warning(f"Blob migration failed for {blob_file.name}: {e}")
            # Remove empty prefix dir
            try:
                prefix_dir.rmdir()
            except OSError:
                pass

        # Remove old blobs directory
        try:
            old_blobs.rmdir()
        except OSError:
            pass

        if migrated:
            logger.info(f"Migrated {migrated} blobs from {self.device_id}/blobs/ to shared store")

    def _gc_blobs(self):
        """Garbage-collect blobs not referenced by any device's snapshots.

        Since the blob store is shared across all devices, we must scan
        every device's manifests before deciding a blob is unreferenced.
        """
        if not self.blobs_dir.exists():
            return

        # Build set of all referenced hashes across ALL devices
        referenced: set[str] = set()
        for device_dir in self.backup_root.iterdir():
            if not device_dir.is_dir() or device_dir.name == "blobs":
                continue
            snap_dir = device_dir / "snapshots"
            if not snap_dir.is_dir():
                continue
            for mf in snap_dir.glob("*.json"):
                try:
                    with open(mf, encoding="utf-8") as f:
                        data = json.load(f)
                except (json.JSONDecodeError, UnicodeDecodeError, OSError):
                    continue
                for file_info in data.get("files", {}).values():
                    h = file_info.get("hash")
                    if h:
                        referenced.add(h)

        # Walk blobs and delete unreferenced ones
        removed = 0
        for prefix_dir in self.blobs_dir.iterdir():
            if not prefix_dir.is_dir():
                continue
            for blob_file in prefix_dir.iterdir():
                if blob_file.name not in referenced:
                    try:
                        blob_file.unlink()
                        removed += 1
                    except OSError:
                        pass
            # Remove empty prefix directories
            try:
                prefix_dir.rmdir()  # Only succeeds if empty
            except OSError:
                pass

        if removed:
            logger.info(f"GC: removed {removed} unreferenced blobs")

    def _prune_snapshots(self, max_count: int):
        """Delete oldest snapshots beyond the configured max, then GC."""
        if not self.snapshots_dir.exists():
            return

        snapshots = sorted(
            self.snapshots_dir.glob("*.json"),
            key=lambda p: p.stem,
            reverse=True,
        )

        if len(snapshots) <= max_count:
            return

        pruned = 0
        for old_snapshot in snapshots[max_count:]:
            try:
                old_snapshot.unlink()
                pruned += 1
                logger.debug(f"Pruned old snapshot: {old_snapshot.stem}")
            except OSError as e:
                logger.warning(f"Could not prune snapshot {old_snapshot}: {e}")

        if pruned:
            logger.info(f"Pruned {pruned} old snapshots (keeping {max_count})")
            self._gc_blobs()

    @staticmethod
    def _compute_delta(
        older_files: dict[str, dict],
        newer_files: dict[str, dict],
    ) -> tuple[int, int, int]:
        """
        Compute file delta between two *files* dicts (path → {hash, …}).

        Args:
            older_files: The files dict from the older snapshot.
            newer_files: The files dict from the newer snapshot.

        Returns:
            (files_added, files_removed, files_changed)
        """
        old_keys = set(older_files.keys())
        new_keys = set(newer_files.keys())

        added = len(new_keys - old_keys)
        removed = len(old_keys - new_keys)

        # Changed = same path but different hash
        changed = 0
        for key in old_keys & new_keys:
            if older_files[key].get("hash") != newer_files[key].get("hash"):
                changed += 1

        return added, removed, changed


# ── Module-level helpers ────────────────────────────────────────────────────

def get_device_identifier(ipod_path: str | Path, discovered_ipod=None) -> str:
    """
    Get a stable identifier for a device, suitable for backup directory naming.

    Tries in order: serial number, FireWire GUID, folder name.
    """
    if discovered_ipod:
        if getattr(discovered_ipod, "serial", ""):
            return discovered_ipod.serial
        if getattr(discovered_ipod, "firewire_guid", ""):
            return discovered_ipod.firewire_guid

    # Fallback: use the folder/drive name
    p = Path(ipod_path)
    name = p.name or p.anchor.rstrip("\\/:")
    return name or "iPod"


def get_device_display_name(discovered_ipod=None, fallback: str = "iPod") -> str:
    """Get a human-readable device name for display in manifests.

    Prefers the user-assigned iPod name (from the master playlist title)
    when available, falling back to the model display name.
    """
    if discovered_ipod:
        ipod_name = getattr(discovered_ipod, "ipod_name", "")
        if ipod_name:
            return ipod_name
        return getattr(discovered_ipod, "display_name", fallback) or fallback
    return fallback
