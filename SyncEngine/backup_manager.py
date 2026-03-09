"""
Content-Addressable Backup Manager for iPod devices.

Creates git-like snapshots of the ENTIRE iPod filesystem. Each snapshot is
a manifest listing every file and its SHA-256 hash. Files are stored once
by hash in a blob store — subsequent backups only store new/changed files.

Storage layout on PC:
    <backup_dir>/<device_id>/
        blobs/<aa>/<aabbccddee...>      # Content-addressable files
        snapshots/<timestamp>.json      # Manifest per backup
        hashcache.json                  # Speed cache: (path,size,mtime) → hash

Restore is a full wipe-and-replace: the iPod is returned to the exact state
captured by the snapshot.
"""

import hashlib
import json
import logging
import os
import shutil
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# Default backup directory
_DEFAULT_BACKUP_DIR = os.path.join(os.path.expanduser("~"), "iOpenPod", "backups")

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
    "thumbs.db",
    "desktop.ini",
})


def _is_excluded(name: str) -> bool:
    """Check if a filename/dirname should be excluded (case-insensitive)."""
    return name.lower() in _OS_EXCLUDE_LOWER


# SHA-256 read buffer
_HASH_BUF_SIZE = 1024 * 1024  # 1 MB


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
                 device_name: str = "iPod"):
        self.device_id = self._sanitize_id(device_id)
        self.device_name = device_name
        self.backup_root = Path(backup_dir or _DEFAULT_BACKUP_DIR)
        self.device_dir = self.backup_root / self.device_id
        self.blobs_dir = self.device_dir / "blobs"
        self.snapshots_dir = self.device_dir / "snapshots"
        self.hashcache_path = self.device_dir / "hashcache.json"

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
        progress_callback: Optional[Callable[[BackupProgress], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
        max_backups: int = 10,
    ) -> Optional[SnapshotInfo]:
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

        # Ensure directories exist
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

        # Load hash cache for speed
        hash_cache = self._load_hash_cache()

        # Phase 1: Discover all files
        if progress_callback:
            progress_callback(BackupProgress("scanning", 0, 0, message="Scanning iPod files…"))

        all_files = self._walk_device(ipod_root)
        total_files = len(all_files)

        if total_files == 0:
            logger.warning("No files found on iPod — aborting backup")
            return None

        logger.info(f"Backup: found {total_files} files to process")

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
                logger.warning(f"Backup: could not stat {rel_path}: {e}")

        logger.info(
            f"Backup: {len(cached_hits)} cached, {len(uncached)} need hashing"
        )

        # 2a. Fast path — cached files (no hash I/O, just blob-exists check + copy)
        for rel_path, full_path, fsize, fmtime, file_hash in cached_hits:
            if is_cancelled and is_cancelled():
                logger.info("Backup cancelled by user")
                return None

            processed += 1
            if progress_callback and (processed == 1 or processed % 200 == 0):
                progress_callback(BackupProgress(
                    "hashing", processed, total_files,
                    current_file=rel_path,
                    message=f"Processing {processed}/{total_files}: {rel_path}"
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
                logger.warning(f"Backup: could not store cached {rel_path}: {e}")

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
                        logger.warning(f"Backup: could not process {rp}: {e}")

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
        now = datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S")

        # Avoid collision if two backups happen in the same second
        manifest_path = self.snapshots_dir / f"{timestamp}.json"
        if manifest_path.exists():
            timestamp = now.strftime("%Y%m%d_%H%M%S") + f"_{now.microsecond}"
            manifest_path = self.snapshots_dir / f"{timestamp}.json"

        manifest = {
            "version": 1,
            "id": timestamp,
            "timestamp": now.isoformat(),
            "device_id": self.device_id,
            "device_name": self.device_name,
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
        )

        if skipped_files:
            logger.warning(
                f"Backup complete with {skipped_files} skipped files: "
                f"{len(manifest_files)} files stored, "
                f"{total_size / (1024**3):.2f} GB, {new_blobs} new blobs"
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
        progress_callback: Optional[Callable[[BackupProgress], None]] = None,
        is_cancelled: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """
        Restore a snapshot to the iPod device using **delta transfer**.

        Instead of wiping the entire iPod and re-copying everything, this
        method compares the snapshot manifest with the current device state
        and only transfers differences:

        - Files already on the iPod with the correct hash → **skipped**
        - Files in the snapshot but not on the iPod → **copied**
        - Files on the iPod but not in the snapshot → **deleted**
        - Files with different hashes → **replaced**

        This dramatically reduces USB transfer time when restoring a snapshot
        that is close to the current device state.

        Args:
            snapshot_id: The snapshot timestamp ID to restore.
            ipod_path: Root path of the iPod.
            progress_callback: Called with progress updates.
            is_cancelled: Optional cancellation check.

        Returns:
            True if restore completed successfully.
        """
        ipod_root = Path(ipod_path)
        manifest = self._load_manifest(snapshot_id)
        if not manifest:
            logger.error(f"Snapshot {snapshot_id} not found")
            return False

        target_files = manifest.get("files", {})
        total_target = len(target_files)

        if total_target == 0:
            logger.warning("Snapshot has no files — nothing to restore")
            return False

        logger.info(f"Restore: {total_target} files from snapshot {snapshot_id}")

        # Phase 0a: Validate paths — reject manifests with traversal attacks.
        ipod_root_resolved = ipod_root.resolve()

        bad_paths: list[str] = []
        for rel_path in target_files:
            dest = (ipod_root / rel_path).resolve()
            try:
                dest.relative_to(ipod_root_resolved)
            except ValueError:
                bad_paths.append(rel_path)

        if bad_paths:
            logger.error(
                f"Restore aborted: {len(bad_paths)} paths escape the iPod root. "
                f"First offender: {bad_paths[0]!r}"
            )
            return False

        # Phase 0b: Verify ALL blobs exist BEFORE touching the device.
        if progress_callback:
            progress_callback(BackupProgress(
                "verifying", 0, 0, message="Verifying backup integrity…"
            ))

        missing_blobs: list[str] = []
        for rel_path, file_info in target_files.items():
            blob_path = self._blob_path(file_info["hash"])
            if not blob_path.exists():
                missing_blobs.append(rel_path)

        if missing_blobs:
            logger.error(
                f"Restore aborted: {len(missing_blobs)} files have missing blobs. "
                f"First missing: {missing_blobs[0]}"
            )
            return False

        # Phase 1: Scan iPod to build current state map (path → hash).
        # Uses the hash cache where possible to avoid re-hashing unchanged
        # files over slow USB. New/uncached files are hashed in parallel.
        if progress_callback:
            progress_callback(BackupProgress(
                "scanning", 0, 0, message="Scanning current iPod files…"
            ))

        hash_cache = self._load_hash_cache()
        ipod_files = self._walk_device(ipod_root)
        ipod_total = len(ipod_files)

        # Build current state: {rel_path: hash}
        current_hashes: dict[str, str] = {}
        scanned = 0

        # Partition into cached vs uncached (same pattern as backup)
        cached_scan: list[tuple[str, str]] = []       # (rel_path, hash)
        uncached_scan: list[tuple[str, Path]] = []     # (rel_path, full_path)

        for rel_path, full_path in ipod_files:
            try:
                st = full_path.stat()
                cache_key = f"{rel_path}|{st.st_size}|{st.st_mtime_ns}"
                cached_hash = hash_cache.get(cache_key)
                if cached_hash:
                    cached_scan.append((rel_path, cached_hash))
                else:
                    uncached_scan.append((rel_path, full_path))
            except (OSError, PermissionError):
                uncached_scan.append((rel_path, full_path))

        # Fast path: cached files
        for rel_path, file_hash in cached_scan:
            current_hashes[rel_path] = file_hash
            scanned += 1

        # Slow path: hash uncached files in parallel
        if uncached_scan:
            lock = threading.Lock()

            def _hash_ipod_file(rel_path: str, full_path: Path) -> tuple[str, str]:
                file_hash = self._hash_file(full_path)
                return rel_path, file_hash

            with ThreadPoolExecutor(max_workers=_NUM_WORKERS) as pool:
                futures = {
                    pool.submit(_hash_ipod_file, rp, fp): rp
                    for rp, fp in uncached_scan
                }
                for future in as_completed(futures):
                    if is_cancelled and is_cancelled():
                        pool.shutdown(wait=False, cancel_futures=True)
                        logger.info("Restore cancelled during scan")
                        return False

                    scanned += 1
                    try:
                        rel_path, file_hash = future.result()
                        with lock:
                            current_hashes[rel_path] = file_hash
                    except (OSError, PermissionError) as e:
                        rp = futures[future]
                        logger.warning(f"Restore scan: could not hash {rp}: {e}")

                    if progress_callback and scanned % 100 == 0:
                        progress_callback(BackupProgress(
                            "scanning", scanned, ipod_total,
                            message=f"Scanning {scanned}/{ipod_total} iPod files…"
                        ))

        logger.info(
            f"Restore scan: {len(cached_scan)} cached, "
            f"{len(uncached_scan)} hashed, {len(current_hashes)} total on device"
        )

        # Phase 2: Compute delta
        target_keys = set(target_files.keys())
        current_keys = set(current_hashes.keys())

        to_add = target_keys - current_keys          # New files
        to_remove = current_keys - target_keys        # Files to delete
        # Changed: same path, different hash
        to_replace: set[str] = set()
        for rp in target_keys & current_keys:
            if target_files[rp].get("hash") != current_hashes.get(rp):
                to_replace.add(rp)

        to_copy = to_add | to_replace   # Files that need blob → iPod transfer
        skipped = len(target_keys & current_keys) - len(to_replace)

        logger.info(
            f"Restore delta: {len(to_add)} add, {len(to_replace)} replace, "
            f"{len(to_remove)} remove, {skipped} unchanged (skipped)"
        )

        if not to_copy and not to_remove:
            logger.info("Restore: iPod already matches snapshot — nothing to do")
            if progress_callback:
                progress_callback(BackupProgress(
                    "complete", total_target, total_target,
                    message="iPod already matches this snapshot — no changes needed"
                ))
            return True

        # Phase 3: Delete files that are NOT in the snapshot.
        # Files being *replaced* (same path, different hash) are NOT deleted
        # here — Phase 4's shutil.copy2 overwrites them in place.  This
        # avoids a dangerous window where a replaced file has been deleted
        # but its new version hasn't been copied yet (USB disconnect, disk
        # full, power loss would leave the iPod missing those files).

        if to_remove:
            if progress_callback:
                progress_callback(BackupProgress(
                    "cleaning", 0, 0,
                    message=f"Removing {len(to_remove)} files…"
                ))

            for rel_path in to_remove:
                if is_cancelled and is_cancelled():
                    logger.warning("Restore cancelled — iPod may be in incomplete state!")
                    return False

                dest = ipod_root / rel_path
                try:
                    if dest.exists():
                        dest.unlink()
                except PermissionError:
                    if sys.platform == "win32":
                        try:
                            os.chmod(dest, 0o777)
                            dest.unlink()
                        except OSError as e:
                            logger.warning(f"Restore: could not remove {rel_path}: {e}")
                    else:
                        logger.warning(f"Restore: could not remove {rel_path}")
                except OSError as e:
                    logger.warning(f"Restore: could not remove {rel_path}: {e}")

            # Clean up empty directories left behind by removals.
            # Walk bottom-up: try to rmdir each parent up to (but not including)
            # the iPod root. rmdir only succeeds on empty dirs, so this is safe.
            for rel_path in to_remove:
                parent = (ipod_root / rel_path).parent
                while parent != ipod_root:
                    try:
                        parent.rmdir()  # Only removes empty dirs
                        parent = parent.parent
                    except OSError:
                        break

        # Phase 4: Copy new + replaced files from blob store → iPod
        if to_copy:
            # Pre-create directory tree for new files
            needed_dirs: set[Path] = set()
            for rel_path in to_copy:
                needed_dirs.add((ipod_root / rel_path).parent)
            for d in sorted(needed_dirs):
                d.mkdir(parents=True, exist_ok=True)

            errors = 0
            copied = 0
            lock = threading.Lock()

            def _restore_file(rel_path: str, file_hash: str) -> tuple[str, bool, str]:
                """Copy one blob to its destination."""
                blob_path = self._blob_path(file_hash)
                dest_path = ipod_root / rel_path
                if not blob_path.exists():
                    return rel_path, False, f"missing blob {file_hash[:16]}…"
                try:
                    shutil.copy2(str(blob_path), str(dest_path))
                    return rel_path, True, ""
                except (OSError, PermissionError) as exc:
                    return rel_path, False, str(exc)

            with ThreadPoolExecutor(max_workers=_NUM_WORKERS) as pool:
                futures = {
                    pool.submit(_restore_file, rp, target_files[rp]["hash"]): rp
                    for rp in to_copy
                }

                for future in as_completed(futures):
                    if is_cancelled and is_cancelled():
                        pool.shutdown(wait=False, cancel_futures=True)
                        logger.warning("Restore cancelled — iPod may be in incomplete state!")
                        return False

                    with lock:
                        copied += 1

                    rel_path, ok, err = future.result()
                    if not ok:
                        logger.error(f"Restore: {err} for {rel_path}")
                        with lock:
                            errors += 1

                    if progress_callback:
                        progress_callback(BackupProgress(
                            "restoring", copied, len(to_copy),
                            current_file=rel_path,
                            message=f"Copying {copied}/{len(to_copy)}: {rel_path}"
                        ))
        else:
            errors = 0

        if progress_callback:
            parts = []
            if to_add:
                parts.append(f"+{len(to_add)} added")
            if to_replace:
                parts.append(f"~{len(to_replace)} replaced")
            if to_remove:
                parts.append(f"−{len(to_remove)} removed")
            parts.append(f"{skipped} unchanged")
            msg = f"Restore complete — {', '.join(parts)}"
            if errors:
                msg += f" ({errors} errors)"
            progress_callback(BackupProgress(
                "complete", total_target, total_target, message=msg
            ))

        if errors:
            logger.warning(f"Restore completed with {errors} errors")
        else:
            logger.info(
                f"Restore complete: +{len(to_add)} add, ~{len(to_replace)} replace, "
                f"−{len(to_remove)} remove, {skipped} skipped"
            )

        return errors == 0

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
        prev_files: Optional[dict] = None   # files dict of the "newer" snapshot

        for mf in manifest_paths:
            try:
                with open(mf, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Could not read snapshot {mf.name}: {e}")
                continue

            info = SnapshotInfo(
                id=data.get("id", mf.stem),
                timestamp=data.get("timestamp", ""),
                device_id=data.get("device_id", self.device_id),
                device_name=data.get("device_name", "iPod"),
                file_count=data.get("file_count", 0),
                total_size=data.get("total_size", 0),
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

    def get_backup_size(self) -> int:
        """Get total size of all backup data (blobs + manifests) in bytes."""
        if not self.device_dir.exists():
            return 0
        total = 0
        for root, _dirs, files in os.walk(self.device_dir):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
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
            [{"device_id": str, "device_name": str, "snapshot_count": int}]
        """
        root = Path(backup_dir or _DEFAULT_BACKUP_DIR)
        if not root.exists():
            return []

        devices: list[dict] = []
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            snap_dir = child / "snapshots"
            if not snap_dir.is_dir():
                continue
            manifests = sorted(snap_dir.glob("*.json"), key=lambda p: p.stem, reverse=True)
            if not manifests:
                continue

            # Read device_name from the latest manifest
            device_name = child.name
            try:
                with open(manifests[0], "r", encoding="utf-8") as f:
                    data = json.load(f)
                device_name = data.get("device_name", child.name)
            except (json.JSONDecodeError, OSError):
                pass

            devices.append({
                "device_id": child.name,
                "device_name": device_name,
                "snapshot_count": len(manifests),
            })

        return devices

    # ── Internal helpers ────────────────────────────────────────────────────

    def _get_latest_snapshot_files(self) -> Optional[dict]:
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
            with open(manifests[0], "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("files")
        except (json.JSONDecodeError, OSError):
            return None

    def _walk_device(self, ipod_root: Path) -> list[tuple[str, Path]]:
        """
        Walk the entire iPod root and return (relative_path, full_path) pairs.

        Skips OS-managed directories (case-insensitive). Dot-directories like
        .iOpenPod are kept — only the explicit exclusion set is filtered.
        """
        results: list[tuple[str, Path]] = []

        for root, dirs, files in os.walk(ipod_root, followlinks=False):
            # Filter out OS-managed directories in-place (single pass)
            dirs[:] = [d for d in dirs if not _is_excluded(d)]

            for filename in files:
                if _is_excluded(filename):
                    continue

                full_path = Path(root) / filename

                # Skip symlinks — avoid following links outside the device,
                # and iPod filesystems (FAT32/exFAT) don't support them anyway.
                if full_path.is_symlink():
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

    def _load_manifest(self, snapshot_id: str) -> Optional[dict]:
        """Load a snapshot manifest by its ID."""
        manifest_path = self.snapshots_dir / f"{snapshot_id}.json"
        if not manifest_path.exists():
            return None
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Could not read snapshot {snapshot_id}: {e}")
            return None

    def _load_hash_cache(self) -> dict[str, str]:
        """Load the hash cache from disk."""
        if not self.hashcache_path.exists():
            return {}
        try:
            with open(self.hashcache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
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

    def _gc_blobs(self):
        """Garbage-collect blobs not referenced by any remaining snapshot."""
        if not self.blobs_dir.exists():
            return

        # Build set of all referenced hashes
        referenced: set[str] = set()
        for mf in self.snapshots_dir.glob("*.json"):
            try:
                with open(mf, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
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
