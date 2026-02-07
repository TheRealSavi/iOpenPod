"""
iPod Integrity Checker — validates consistency between three sources of truth:

  1. **Filesystem**: actual audio files under /iPod_Control/Music/F**/
  2. **iTunesDB**: the binary database the iPod firmware reads
  3. **iOpenPod.json**: our mapping file (fingerprint → dbid)

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
   For every dbid in the mapping, verify the dbid exists in iTunesDB.
   If stale → remove from mapping so the diff engine treats the PC
   track as a fresh add.

C. Filesystem → iTunesDB  (orphan detection)
   Scan /iPod_Control/Music/F** for files not referenced by any track.
   Orphans are deleted to reclaim space.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable

from .mapping import MappingFile

logger = logging.getLogger(__name__)

# Audio extensions the iPod can contain
_AUDIO_EXTS = frozenset({
    ".mp3", ".m4a", ".m4b", ".m4p", ".mp4",
    ".aac", ".wav", ".aif", ".aiff", ".alac",
})


@dataclass
class IntegrityReport:
    """Summary of what the integrity check found and fixed."""

    # Tracks in iTunesDB whose file is missing from the iPod filesystem
    missing_files: list[dict] = field(default_factory=list)

    # Mapping entries whose dbid is not present in the iTunesDB
    stale_mappings: list[tuple[str, int]] = field(default_factory=list)  # (fingerprint, dbid)

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
    progress_callback: Optional[Callable] = None,
) -> IntegrityReport:
    """
    Run all three consistency checks and repair discrepancies.

    This mutates ``ipod_tracks`` (removes entries whose files are missing)
    and ``mapping`` (removes stale dbids).  Orphan files are deleted from
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

    # ── A. iTunesDB → Filesystem ────────────────────────────────────────────
    if progress_callback:
        progress_callback("integrity", 0, 0, "Checking iTunesDB against filesystem…")

    _check_db_files_exist(ipod_root, ipod_tracks, report)

    # ── B. iOpenPod.json → iTunesDB ────────────────────────────────────────
    if progress_callback:
        progress_callback("integrity", 0, 0, "Checking mapping against iTunesDB…")

    _check_mapping_dbids(ipod_tracks, mapping, report)

    # ── C. Filesystem → iTunesDB  (orphan scan) ────────────────────────────
    if progress_callback:
        progress_callback("integrity", 0, 0, "Scanning for orphan files…")

    _check_orphan_files(ipod_root, music_dir, ipod_tracks, report, delete_orphans)

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

        # iTunesDB Location format:  :iPod_Control:Music:F00:FILE.mp3
        relative = location.replace(":", "/").lstrip("/")
        full_path = ipod_root / relative

        if not full_path.exists():
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


# ── Check B: mapping dbids → iTunesDB ─────────────────────────────────────


def _check_mapping_dbids(
    ipod_tracks: list[dict],
    mapping: MappingFile,
    report: IntegrityReport,
) -> None:
    """Remove mapping entries whose dbid is not in *ipod_tracks*."""
    # Build set of valid dbids from the (already-cleaned) track list
    valid_dbids: set[int] = set()
    for track in ipod_tracks:
        dbid = track.get("dbid")
        if dbid:
            valid_dbids.add(dbid)

    mapping_dbids = mapping.all_dbids()
    stale_dbids = mapping_dbids - valid_dbids

    for dbid in stale_dbids:
        result = mapping.get_by_dbid(dbid)
        if result:
            fp, _entry = result
            report.stale_mappings.append((fp, dbid))
            mapping.remove_track(fp, dbid=dbid)
            logger.warning(f"Integrity: removed stale mapping dbid={dbid} (fingerprint {fp[:20]}…)")

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
) -> None:
    """Find and optionally delete files in Music/F** not referenced by iTunesDB."""
    if not music_dir.exists():
        return

    # Build set of absolute paths referenced by iTunesDB
    referenced_paths: set[Path] = set()
    for track in ipod_tracks:
        location = track.get("Location")
        if not location:
            continue
        relative = location.replace(":", "/").lstrip("/")
        full_path = (ipod_root / relative).resolve()
        referenced_paths.add(full_path)

    # Scan F00–F49 for actual audio files
    orphans: list[Path] = []
    for folder in sorted(music_dir.iterdir()):
        if not folder.is_dir():
            continue
        # Only look in F## folders
        if not (len(folder.name) >= 2 and folder.name[0] == "F" and folder.name[1:].isdigit()):
            continue
        for file in folder.iterdir():
            if not file.is_file():
                continue
            if file.suffix.lower() not in _AUDIO_EXTS:
                continue
            if file.resolve() not in referenced_paths:
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
            for orphan in orphans:
                try:
                    orphan.unlink()
                    deleted += 1
                    logger.debug(f"Integrity: deleted orphan {orphan}")
                except Exception as e:
                    report.errors.append(f"Failed to delete orphan {orphan}: {e}")
                    logger.error(f"Integrity: failed to delete orphan {orphan}: {e}")

            logger.info(f"Integrity: deleted {deleted}/{len(orphans)} orphan files")
