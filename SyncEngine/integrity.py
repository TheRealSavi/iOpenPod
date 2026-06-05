"""
iPod Integrity Checker — validates consistency between three sources of truth:

  1. **Filesystem**: actual audio files under /iPod_Control/Music/F**/
  2. **iTunesDB**: the binary database the iPod firmware reads
  3. **iOpenPod.json**: our mapping file (fingerprint → db_track_id)

Run this BEFORE the diff engine so the sync plan is built on accurate data.
Any discrepancies are repaired automatically (conservative: never delete files
the user can't re-sync).

Checks performed
────────────────
A. iTunesDB → Filesystem
   For every track Location in iTunesDB, verify the file exists.
   If missing → remove that track from the working tracks list so the
   diff engine doesn't think it's on the iPod.

B. iOpenPod.json → iTunesDB
   For every db_track_id in the mapping, verify the db_track_id exists in iTunesDB.
   If stale → remove from mapping so the diff engine treats the PC
   track as a fresh add.

C. Filesystem → iTunesDB  (orphan detection)
   Scan /iPod_Control/Music/F** for files not referenced by any track.
   Orphans are deleted to reclaim space.
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ._formats import MEDIA_EXTENSIONS as _MEDIA_EXTS
from .mapping import MappingFile

logger = logging.getLogger(__name__)


def _is_appledouble_sidecar(path: Path) -> bool:
    """Return True for macOS AppleDouble metadata files like ._TRACK.m4a."""
    return path.name.startswith("._")


@dataclass
class IntegrityReport:
    """Summary of what the integrity check found and fixed."""

    # Tracks in iTunesDB whose file is missing from the iPod filesystem
    missing_files: list[dict] = field(default_factory=list)

    # Mapping entries whose db_track_id is not present in the iTunesDB
    stale_mappings: list[tuple[str, int]] = field(default_factory=list)  # (fingerprint, db_track_id)

    # Files on iPod not referenced by any iTunesDB track
    orphan_files: list[Path] = field(default_factory=list)

    # Errors encountered during the check
    errors: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not (self.missing_files or self.stale_mappings or self.orphan_files)

    @property
    def summary(self) -> str:
        if self.is_clean:
            return "Integrity check passed — all data is consistent."
        parts = []
        if self.missing_files:
            parts.append(f"{len(self.missing_files)} tracks in DB but file missing on iPod")
        if self.stale_mappings:
            parts.append(f"{len(self.stale_mappings)} stale entries in iOpenPod.json")
        if self.orphan_files:
            parts.append(f"{len(self.orphan_files)} orphan files on iPod (not in DB)")
        if self.errors:
            parts.append(f"{len(self.errors)} errors")
        return "Integrity issues found: " + ", ".join(parts)


def check_integrity(
    ipod_path: str | Path,
    ipod_tracks: list[dict],
    mapping: MappingFile,
    *,
    delete_orphans: bool = True,
    progress_callback: Callable | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> IntegrityReport:
    """
    Run all three consistency checks and repair discrepancies.

    This mutates ``ipod_tracks`` (removes entries whose files are missing)
    and ``mapping`` (removes stale db_track_ids).  Orphan files are deleted from
    the iPod filesystem if *delete_orphans* is True.

    Args:
        ipod_path: Mount point / root of the iPod.
        ipod_tracks: Track dicts parsed from iTunesDB (mutated in place).
        mapping: The loaded iOpenPod.json MappingFile (mutated in place).
        delete_orphans: If True, delete orphan files from iPod. Default True.
        progress_callback: Optional callback(stage, current, total, message).

    Returns:
        IntegrityReport with details of what was found and fixed.
    """
    ipod_root = Path(ipod_path)
    music_dir = ipod_root / "iPod_Control" / "Music"
    report = IntegrityReport()

    def _cancelled() -> bool:
        return is_cancelled is not None and is_cancelled()

    # ── A. iTunesDB → Filesystem ────────────────────────────────────────────
    if progress_callback:
        progress_callback("integrity", 0, 0, "Checking iTunesDB against filesystem…")

    _check_db_files_exist(ipod_root, ipod_tracks, report)

    if _cancelled():
        return report

    # ── B. iOpenPod.json → iTunesDB ────────────────────────────────────────
    if progress_callback:
        progress_callback("integrity", 0, 0, "Checking mapping against iTunesDB…")

    _check_mapping_db_track_ids(ipod_tracks, mapping, report)

    if _cancelled():
        return report

    # ── C. Filesystem → iTunesDB  (orphan scan) ────────────────────────────
    if progress_callback:
        progress_callback("integrity", 0, 0, "Scanning for orphan files…")

    _check_orphan_files(ipod_root, music_dir, ipod_tracks, report, delete_orphans, _cancelled)

    if not report.is_clean:
        logger.warning(report.summary)
    else:
        logger.info(report.summary)

    return report


# ── Check A: DB tracks → filesystem ────────────────────────────────────────


def _check_db_files_exist(
    ipod_root: Path,
    ipod_tracks: list[dict],
    report: IntegrityReport,
) -> None:
    """Remove tracks from *ipod_tracks* whose audio file is missing."""
    to_remove_indices: list[int] = []

    for idx, track in enumerate(ipod_tracks):
        location = track.get("Location")
        if not location:
            continue

        full_path = _resolve_location_to_path(ipod_root, location)
        if full_path is None:
            logger.debug(
                "Integrity: could not resolve Location for track '%s' — skipping missing-file check",
                track.get("Title", "?"),
            )
            continue

        if not full_path.is_file():
            logger.warning(
                f"Integrity: file missing for track "
                f"'{track.get('Title', '?')}' — {location}"
            )
            report.missing_files.append(track)
            to_remove_indices.append(idx)

    # Remove from back to front so indices stay valid
    for idx in reversed(to_remove_indices):
        ipod_tracks.pop(idx)

    if report.missing_files:
        logger.info(
            f"Integrity: removed {len(report.missing_files)} tracks with missing files from working set"
        )


# ── Check B: mapping db_track_ids → iTunesDB ─────────────────────────────────────


def _check_mapping_db_track_ids(
    ipod_tracks: list[dict],
    mapping: MappingFile,
    report: IntegrityReport,
) -> None:
    """Remove mapping entries whose db_track_id is not in *ipod_tracks*."""
    # Build set of valid db_track_ids from the (already-cleaned) track list
    valid_db_track_ids: set[int] = set()
    for track in ipod_tracks:
        db_track_id = track.get("db_track_id", track.get("db_id"))
        if db_track_id:
            valid_db_track_ids.add(db_track_id)

    mapping_db_track_ids = mapping.all_db_track_ids()
    stale_db_track_ids = mapping_db_track_ids - valid_db_track_ids

    for db_track_id in stale_db_track_ids:
        result = mapping.get_by_db_track_id(db_track_id)
        if result:
            fp, _entry = result
            report.stale_mappings.append((fp, db_track_id))
            mapping.remove_track(fp, db_track_id=db_track_id)
            logger.warning(f"Integrity: removed stale mapping db_track_id={db_track_id} (fingerprint {fp[:20]}…)")

    if report.stale_mappings:
        logger.info(
            f"Integrity: cleaned {len(report.stale_mappings)} stale mapping entries"
        )


# ── Check C: filesystem → iTunesDB (orphan detection) ─────────────────────


def _check_orphan_files(
    ipod_root: Path,
    music_dir: Path,
    ipod_tracks: list[dict],
    report: IntegrityReport,
    delete_orphans: bool,
    is_cancelled: Callable[[], bool] = lambda: False,
) -> None:
    """Find and optionally delete files in Music/F** not referenced by iTunesDB."""
    if not music_dir.exists():
        return

    # Build set of normalised paths referenced by iTunesDB.
    # Use os.path.normcase(os.path.join(...)) instead of Path.resolve() to
    # avoid a stat() syscall per path — the iPod filesystem is case-preserving
    # so normalised string comparison is sufficient.
    import os
    referenced: set[str] = set()
    for track in ipod_tracks:
        location = track.get("Location")
        if not location:
            continue
        resolved = _resolve_location_to_path(ipod_root, location)
        if resolved is None:
            continue
        referenced.add(os.path.normcase(str(resolved)))

    # Scan F00–F## for actual audio files
    orphans: list[Path] = []
    for folder in sorted(music_dir.iterdir()):
        if is_cancelled():
            return
        if not folder.is_dir():
            continue
        # Only look in F## folders
        if not (len(folder.name) >= 2 and folder.name[0] == "F" and folder.name[1:].isdigit()):
            continue
        for file in folder.iterdir():
            if is_cancelled():
                return
            if not file.is_file():
                continue
            if _is_appledouble_sidecar(file):
                continue
            if file.suffix.lower() not in _MEDIA_EXTS:
                continue
            if os.path.normcase(str(file)) not in referenced:
                orphans.append(file)

    report.orphan_files = orphans

    if orphans:
        total_bytes = sum(f.stat().st_size for f in orphans if f.exists())
        logger.info(
            f"Integrity: found {len(orphans)} orphan files "
            f"({total_bytes / (1024 * 1024):.1f} MB)"
        )

        if delete_orphans:
            deleted = 0
            delete_error_count = 0
            delete_error_samples: list[str] = []
            for orphan in orphans:
                try:
                    orphan.unlink()
                    deleted += 1
                    logger.debug(f"Integrity: deleted orphan {orphan}")
                except FileNotFoundError:
                    logger.debug("Integrity: orphan already gone %s", orphan)
                except Exception as e:
                    error_text = f"Failed to delete orphan {orphan}: {e}"
                    report.errors.append(error_text)
                    delete_error_count += 1
                    if len(delete_error_samples) < 5:
                        delete_error_samples.append(error_text)

            logger.info(f"Integrity: deleted {deleted}/{len(orphans)} orphan files")
            if delete_error_samples:
                logger.warning(
                    "Integrity: failed to delete %d orphan file(s); examples: %s",
                    delete_error_count,
                    "; ".join(delete_error_samples),
                )


def _resolve_location_to_path(ipod_root: Path, location: str) -> Path | None:
    """Resolve a track Location field to an expected on-device file path.

    The returned path may not exist; callers decide whether absence is a
    missing-file integrity issue.

    Supports:
      - iTunes colon paths: :iPod_Control:Music:F00:FILE.mp3
      - Absolute Windows paths: X:\\iPod_Control\\Music\\F00\\FILE.mp3
      - Absolute/relative POSIX-style paths containing iPod_Control
    """
    if not location:
        return None

    loc = str(location).strip()

    direct = Path(loc)
    if direct.is_file():
        return direct

    unified = loc.replace("\\", "/")
    lower = unified.lower()
    is_windows_abs = bool(re.match(r"^[a-zA-Z]:[\\/]", loc))

    # Colon-delimited iTunes path.  Handle this before the generic
    # iPod_Control marker branch so :iPod_Control:Music:... becomes slashes.
    if not is_windows_abs and ":" in loc:
        rel_colon = loc.replace(":", "/").lstrip("/")
        return ipod_root / rel_colon

    marker = "ipod_control"
    marker_idx = lower.find(marker)
    if marker_idx >= 0:
        rel_from_marker = unified[marker_idx:].lstrip("/")
        return ipod_root / rel_from_marker

    if not direct.is_absolute() and not is_windows_abs:
        return ipod_root / unified.lstrip("/")

    return None
