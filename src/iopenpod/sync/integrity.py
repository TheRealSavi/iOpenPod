"""
iPod Integrity Checker — validates consistency between three sources of truth:

  1. **Filesystem**: actual audio files under /iPod_Control/Music/F**/
  2. **iTunesDB**: the binary database the iPod firmware reads
  3. **iOpenPod.json**: our mapping file (fingerprint → db_track_id)

Run this BEFORE the diff engine so the sync plan is built on accurate data.
This module is deliberately read-only: it reports discrepancies for the sync
plan, and the guarded executor performs any requested repair later.

Checks performed
────────────────
A. iTunesDB → Filesystem
   For every track Location in iTunesDB, verify the file exists.
   If missing → report that track so the planner can exclude it from its
   private working set and schedule a database removal.

B. iOpenPod.json → iTunesDB
   For every db_track_id in the mapping, verify the db_track_id exists in iTunesDB.
   If stale → report it so the planner can use a cleaned in-memory mapping
   and the guarded executor can persist that cleanup.

C. Filesystem → iTunesDB  (orphan detection)
   Scan /iPod_Control/Music/F** for files not referenced by any track.
   Orphans are reported for guarded deletion during execution.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ._formats import MEDIA_EXTENSIONS as _MEDIA_EXTS
from .ipod_track_paths import expected_ipod_track_file_path
from .mapping import MappingFile

logger = logging.getLogger(__name__)


def _is_appledouble_sidecar(path: Path) -> bool:
    """Return True for macOS AppleDouble metadata files like ._TRACK.m4a."""
    return path.name.startswith("._")


@dataclass
class IntegrityReport:
    """Summary of discrepancies found without mutating the iPod."""

    # Tracks in iTunesDB whose file is missing from the iPod filesystem
    missing_files: list[dict] = field(default_factory=list)

    # Mapping entries whose db_track_id is not present in the iTunesDB
    stale_mappings: list[tuple[str, int]] = field(default_factory=list)  # (fingerprint, db_track_id)

    # Files on iPod not referenced by any iTunesDB track
    orphan_files: list[Path] = field(default_factory=list)

    # The mapping file could not be parsed and must be rebuilt under the
    # device writer guard.  The original remains untouched during planning.
    mapping_rebuild_required: bool = False

    # Errors encountered during the check
    errors: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not (
            self.missing_files
            or self.stale_mappings
            or self.orphan_files
            or self.mapping_rebuild_required
            or self.errors
        )

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
        if self.mapping_rebuild_required:
            parts.append("iOpenPod.json needs a guarded rebuild")
        if self.errors:
            parts.append(f"{len(self.errors)} errors")
        return "Integrity issues found: " + ", ".join(parts)


def check_integrity(
    ipod_path: str | Path,
    ipod_tracks: list[dict],
    mapping: MappingFile,
    *,
    delete_orphans: bool | None = None,
    progress_callback: Callable | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> IntegrityReport:
    """
    Run all three consistency checks without modifying the iPod or inputs.

    Args:
        ipod_path: Mount point / root of the iPod.
        ipod_tracks: Track dicts parsed from iTunesDB.
        mapping: The loaded iOpenPod.json MappingFile.
        delete_orphans: Deprecated compatibility argument.  Orphans are never
                        deleted by this read-only check.
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

    missing_track_objects = {id(track) for track in report.missing_files}
    existing_tracks = [
        track for track in ipod_tracks if id(track) not in missing_track_objects
    ]
    _check_mapping_db_track_ids(existing_tracks, mapping, report)

    if _cancelled():
        return report

    # ── C. Filesystem → iTunesDB  (orphan scan) ────────────────────────────
    if progress_callback:
        progress_callback("integrity", 0, 0, "Scanning for orphan files…")

    _check_orphan_files(ipod_root, music_dir, ipod_tracks, report, _cancelled)

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
    """Report tracks whose referenced audio file is missing."""
    for track in ipod_tracks:
        location = track.get("Location")
        if not location:
            continue

        full_path = expected_ipod_track_file_path(ipod_root, location)
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

    if report.missing_files:
        logger.info(
            "Integrity: found %d database tracks with missing files",
            len(report.missing_files),
        )


# ── Check B: mapping db_track_ids → iTunesDB ─────────────────────────────────────


def _check_mapping_db_track_ids(
    ipod_tracks: list[dict],
    mapping: MappingFile,
    report: IntegrityReport,
) -> None:
    """Report mapping entries whose db_track_id is not in *ipod_tracks*."""
    # Build set of valid db_track_ids from tracks whose media files exist.
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
            logger.warning(
                "Integrity: found stale mapping db_track_id=%s (fingerprint %s…)",
                db_track_id,
                fp[:20],
            )

    if report.stale_mappings:
        logger.info(
            "Integrity: found %d stale mapping entries",
            len(report.stale_mappings),
        )


# ── Check C: filesystem → iTunesDB (orphan detection) ─────────────────────


def _check_orphan_files(
    ipod_root: Path,
    music_dir: Path,
    ipod_tracks: list[dict],
    report: IntegrityReport,
    is_cancelled: Callable[[], bool] = lambda: False,
) -> None:
    """Find media in Music/F** that is not referenced by iTunesDB."""
    if not music_dir.exists():
        return

    try:
        root_resolved = ipod_root.resolve(strict=False)
        music_resolved = music_dir.resolve(strict=False)
    except OSError as exc:
        report.errors.append(f"Could not resolve the iPod music directory: {exc}")
        return
    if not music_resolved.is_relative_to(root_resolved):
        report.errors.append(
            "The iPod music directory resolves outside the selected device root"
        )
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
        resolved = expected_ipod_track_file_path(ipod_root, location)
        if resolved is None:
            continue
        referenced.add(os.path.normcase(str(resolved)))

    # Scan F00–F## for actual audio files
    orphans: list[Path] = []
    try:
        folders = sorted(music_dir.iterdir())
    except OSError as exc:
        report.errors.append(f"Could not scan the iPod music directory: {exc}")
        return

    for folder in folders:
        if is_cancelled():
            return
        if not folder.is_dir():
            continue
        # Only look in F## folders
        if not (len(folder.name) >= 2 and folder.name[0] == "F" and folder.name[1:].isdigit()):
            continue
        try:
            folder_resolved = folder.resolve(strict=False)
        except OSError as exc:
            report.errors.append(f"Could not resolve iPod music folder {folder}: {exc}")
            continue
        if not folder_resolved.is_relative_to(music_resolved):
            report.errors.append(
                f"Skipped iPod music folder that resolves outside Music: {folder}"
            )
            continue
        try:
            files = tuple(folder.iterdir())
        except OSError as exc:
            report.errors.append(f"Could not scan iPod music folder {folder}: {exc}")
            continue
        for file in files:
            if is_cancelled():
                return
            if not file.is_file():
                continue
            if _is_appledouble_sidecar(file):
                continue
            if file.suffix.lower() not in _MEDIA_EXTS:
                continue
            try:
                if not file.resolve(strict=False).is_relative_to(music_resolved):
                    report.errors.append(
                        f"Skipped iPod media path that resolves outside Music: {file}"
                    )
                    continue
            except OSError as exc:
                report.errors.append(f"Could not resolve iPod media file {file}: {exc}")
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
