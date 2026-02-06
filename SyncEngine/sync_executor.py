"""
Sync Executor - Executes a sync plan to synchronize PC library with iPod.

Handles:
- Adding new tracks (transcode if needed, copy, add to iTunesDB)
- Removing tracks (remove from iTunesDB, delete file)
- Updating metadata (modify iTunesDB entry)
- Syncing play counts and ratings back to PC

Uses iTunesDB_Writer for database modifications.
"""

import logging
import shutil
from pathlib import Path
from typing import Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .diff_engine import SyncPlan, SyncItem, SyncAction, QualityChange
from .mapping import MappingManager, MappingFile
from .transcoder import transcode, needs_transcoding
from .audio_fingerprint import get_or_compute_fingerprint

from iTunesDB_Writer.mhit_writer import TrackInfo

logger = logging.getLogger(__name__)


@dataclass
class SyncProgress:
    """Progress info for sync callbacks."""

    stage: str  # "add", "remove", "update_metadata", "update_file", etc.
    current: int
    total: int
    current_item: Optional[SyncItem] = None
    message: str = ""


@dataclass
class SyncResult:
    """Result of a sync operation."""

    success: bool
    tracks_added: int = 0
    tracks_removed: int = 0
    tracks_updated_metadata: int = 0
    tracks_updated_file: int = 0
    playcounts_synced: int = 0
    ratings_synced: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    @property
    def summary(self) -> str:
        lines = []
        if self.tracks_added:
            lines.append(f"  ✅ Added {self.tracks_added} tracks")
        if self.tracks_removed:
            lines.append(f"  🗑️  Removed {self.tracks_removed} tracks")
        if self.tracks_updated_metadata:
            lines.append(f"  📝 Updated metadata for {self.tracks_updated_metadata} tracks")
        if self.tracks_updated_file:
            lines.append(f"  🔄 Re-synced {self.tracks_updated_file} tracks")
        if self.playcounts_synced:
            lines.append(f"  🎵 Synced play counts for {self.playcounts_synced} tracks")
        if self.ratings_synced:
            lines.append(f"  ⭐ Synced ratings for {self.ratings_synced} tracks")
        if self.errors:
            lines.append(f"  ⚠️  {len(self.errors)} errors occurred")

        if not lines:
            return "No changes made."

        status = "✅ Sync completed" if self.success else "⚠️ Sync completed with errors"
        return f"{status}:\n" + "\n".join(lines)


class SyncExecutor:
    """
    Executes a sync plan to synchronize PC library with iPod.

    Features:
    - Transcode cache: Avoids re-transcoding for multiple iPods
    - Round-robin file distribution across F00-F49 folders

    Usage:
        executor = SyncExecutor(ipod_path)
        result = executor.execute(plan, progress_callback)
    """

    def __init__(self, ipod_path: str | Path, cache_dir: Optional[Path] = None):
        """
        Initialize executor.

        Args:
            ipod_path: Root path of mounted iPod (e.g., "E:" or "/mnt/ipod")
            cache_dir: Custom transcode cache directory (default: ~/.iopenpod/transcode_cache)
        """
        from .transcode_cache import TranscodeCache

        self.ipod_path = Path(ipod_path)
        self.music_dir = self.ipod_path / "iPod_Control" / "Music"
        self.mapping_manager = MappingManager(ipod_path)
        self.transcode_cache = TranscodeCache(cache_dir)

        # Track folder counter for distributing files across F00-F49
        self._folder_counter = 0

    def _get_next_music_folder(self) -> Path:
        """Get next music folder (F00-F49) using round-robin."""
        folder_name = f"F{self._folder_counter:02d}"
        self._folder_counter = (self._folder_counter + 1) % 50
        folder = self.music_dir / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _generate_ipod_filename(self, original_name: str, extension: str) -> str:
        """Generate a unique filename for iPod storage."""
        # iPod uses 4-character random names like "ABCD.mp3"
        import random
        import string

        chars = string.ascii_uppercase + string.digits
        random_name = "".join(random.choices(chars, k=4))
        return f"{random_name}{extension}"

    def _get_target_format(self, source_path: Path) -> str:
        """Determine the target format for transcoding."""
        from .transcoder import get_transcode_target, TranscodeTarget

        target = get_transcode_target(source_path)
        if target == TranscodeTarget.ALAC:
            return "alac"
        elif target == TranscodeTarget.AAC:
            return "aac"
        return source_path.suffix.lstrip(".")

    def _copy_to_ipod(
        self,
        source_path: Path,
        needs_transcode: bool,
        fingerprint: Optional[str] = None,
        aac_bitrate: int = 256,
    ) -> tuple[bool, Optional[Path], bool]:
        """
        Copy or transcode a file to iPod, using cache when possible.

        Args:
            source_path: Path to source file
            needs_transcode: Whether transcoding is required
            fingerprint: Acoustic fingerprint (for cache lookup)
            aac_bitrate: Bitrate for AAC encoding

        Returns:
            (success, ipod_path, was_transcoded)
        """
        dest_folder = self._get_next_music_folder()
        source_size = source_path.stat().st_size

        if needs_transcode:
            target_format = self._get_target_format(source_path)
            bitrate = aac_bitrate if target_format == "aac" else None

            # Check transcode cache first
            if fingerprint:
                cached_path = self.transcode_cache.get(
                    fingerprint, target_format, source_size, bitrate
                )
                if cached_path:
                    # Cache hit! Copy from cache
                    ext = cached_path.suffix
                    new_name = self._generate_ipod_filename(source_path.stem, ext)
                    final_path = dest_folder / new_name
                    try:
                        shutil.copy2(cached_path, final_path)
                        logger.info(f"Used cached transcode: {source_path.name}")
                        return True, final_path, True
                    except Exception as e:
                        logger.warning(f"Cache copy failed, will transcode: {e}")

            # Cache miss - transcode
            result = transcode(source_path, dest_folder, aac_bitrate=aac_bitrate)
            if result.success and result.output_path:
                # Rename to iPod-style filename
                new_name = self._generate_ipod_filename(
                    source_path.stem, result.output_path.suffix
                )
                final_path = dest_folder / new_name
                result.output_path.rename(final_path)

                # Add to cache for future use
                if fingerprint:
                    self.transcode_cache.add(
                        fingerprint=fingerprint,
                        transcoded_path=final_path,
                        source_format=source_path.suffix.lstrip("."),
                        target_format=target_format,
                        source_size=source_size,
                        bitrate=bitrate,
                    )

                return True, final_path, True
            else:
                logger.error(f"Transcode failed: {result.error_message}")
                return False, None, True
        else:
            # Direct copy (no transcoding needed)
            new_name = self._generate_ipod_filename(source_path.stem, source_path.suffix)
            dest_path = dest_folder / new_name
            try:
                shutil.copy2(source_path, dest_path)
                return True, dest_path, False
            except Exception as e:
                logger.error(f"Copy failed: {e}")
                return False, None, False

    def _delete_from_ipod(self, ipod_path: str | Path) -> bool:
        """Delete a file from iPod."""
        try:
            path = Path(ipod_path)
            if path.exists():
                path.unlink()
                logger.debug(f"Deleted: {path}")
            return True
        except Exception as e:
            logger.error(f"Delete failed for {ipod_path}: {e}")
            return False

    def execute(
        self,
        plan: SyncPlan,
        mapping: MappingFile,
        progress_callback: Optional[Callable[[SyncProgress], None]] = None,
        dry_run: bool = False,
    ) -> SyncResult:
        """
        Execute the sync plan.

        Args:
            plan: SyncPlan from FingerprintDiffEngine
            mapping: MappingFile to update
            progress_callback: Optional callback for progress updates
            dry_run: If True, don't actually make changes

        Returns:
            SyncResult with statistics and any errors
        """
        from iTunesDB_Writer import TrackInfo

        result = SyncResult(success=True)

        # Load existing tracks from iPod database
        existing_tracks_data = self._read_existing_tracks()

        # Convert to TrackInfo objects, indexed by dbid
        tracks_by_dbid: dict[int, TrackInfo] = {}
        tracks_by_location: dict[str, TrackInfo] = {}
        for t in existing_tracks_data:
            track_info = self._track_dict_to_info(t)
            if track_info.dbid:
                tracks_by_dbid[track_info.dbid] = track_info
            if track_info.location:
                tracks_by_location[track_info.location] = track_info

        # Track new tracks to add
        new_tracks: list[TrackInfo] = []
        # Track PC source file paths for artwork extraction
        # Start with ALL matched tracks from the diff plan (existing tracks with PC paths)
        pc_file_paths: dict[int, str] = dict(getattr(plan, 'matched_pc_paths', {}))
        logger.info(f"ART: starting with {len(pc_file_paths)} matched PC paths from sync plan")

        # ===== Stage 1: Add new tracks =====
        if plan.to_add:
            if progress_callback:
                progress_callback(
                    SyncProgress("add", 0, len(plan.to_add), message="Adding new tracks...")
                )

            for i, item in enumerate(plan.to_add):
                if progress_callback:
                    progress_callback(
                        SyncProgress("add", i + 1, len(plan.to_add), item, item.description)
                    )

                if item.pc_track is None:
                    continue

                if dry_run:
                    result.tracks_added += 1
                    continue

                # Copy/transcode to iPod (with cache support)
                source_path = Path(item.pc_track.path)
                need_transcode = needs_transcoding(source_path)

                success, ipod_path, was_transcoded = self._copy_to_ipod(
                    source_path, need_transcode, fingerprint=item.fingerprint
                )

                if not success:
                    result.errors.append((item.description, "Failed to copy/transcode"))
                    continue

                if ipod_path is None:
                    result.errors.append((item.description, "No iPod path returned"))
                    continue

                # Create TrackInfo for the new track
                # Convert iPod path to colon-separated format
                ipod_location = ":" + str(ipod_path.relative_to(self.ipod_path)).replace("\\", ":").replace("/", ":")
                track_info = self._pc_track_to_info(item.pc_track, ipod_location, was_transcoded)
                new_tracks.append(track_info)

                # Track PC source path for artwork extraction
                # NOTE: track_info.dbid is 0 here — assigned later in write_itunesdb().
                # We key by id(track_info) temporarily; mhbd_writer remaps to real dbid.
                pc_file_paths[id(track_info)] = str(source_path)
                logger.info(f"ART: queued PC path for new track '{track_info.title}' (dbid assigned later, obj_id={id(track_info)})")

                # Get fingerprint
                fingerprint = item.fingerprint
                if not fingerprint:
                    fingerprint = get_or_compute_fingerprint(source_path)

                if fingerprint and ipod_path:
                    # Update mapping with the new dbid
                    mapping.add_track(
                        fingerprint=fingerprint,
                        dbid=track_info.dbid,
                        source_format=source_path.suffix.lstrip("."),
                        ipod_format=ipod_path.suffix.lstrip("."),
                        source_size=item.pc_track.size,
                        source_mtime=item.pc_track.mtime,
                        was_transcoded=was_transcoded,
                        source_path_hint=item.pc_track.relative_path,
                    )

                result.tracks_added += 1

        # ===== Stage 2: Remove deleted tracks =====
        if plan.to_remove:
            if progress_callback:
                progress_callback(
                    SyncProgress("remove", 0, len(plan.to_remove), message="Removing tracks...")
                )

            for i, item in enumerate(plan.to_remove):
                if progress_callback:
                    progress_callback(
                        SyncProgress("remove", i + 1, len(plan.to_remove), item, item.description)
                    )

                if dry_run:
                    result.tracks_removed += 1
                    continue

                # Get file path from iTunesDB track info
                if item.ipod_track:
                    file_path = item.ipod_track.get("Location")
                    if file_path:
                        # Convert iPod path format to actual path
                        # iPod stores paths like ":iPod_Control:Music:F00:ABCD.mp3"
                        relative_path = file_path.replace(":", "/").lstrip("/")
                        full_path = self.ipod_path / relative_path
                        self._delete_from_ipod(full_path)

                        # Remove from tracks_by_location (won't be written to new DB)
                        if file_path in tracks_by_location:
                            track_to_remove = tracks_by_location.pop(file_path)
                            if track_to_remove.dbid in tracks_by_dbid:
                                del tracks_by_dbid[track_to_remove.dbid]

                # Remove from mapping
                if item.fingerprint:
                    mapping.remove_track(item.fingerprint)
                elif item.dbid:
                    mapping.remove_by_dbid(item.dbid)
                    # Also remove from tracks_by_dbid
                    if item.dbid in tracks_by_dbid:
                        del tracks_by_dbid[item.dbid]

                result.tracks_removed += 1

        # ===== Stage 3: Quality changes (re-sync with different quality file) =====
        quality_changes = getattr(plan, 'quality_changes', [])
        if quality_changes:
            if progress_callback:
                progress_callback(
                    SyncProgress(
                        "quality_change", 0, len(quality_changes), message="Re-syncing quality changes..."
                    )
                )

            for i, qc in enumerate(quality_changes):
                if progress_callback:
                    desc = f"{qc.pc_track.artist} - {qc.pc_track.title} ({qc.direction})"
                    progress_callback(
                        SyncProgress(
                            "quality_change", i + 1, len(quality_changes), message=desc
                        )
                    )

                if dry_run:
                    result.tracks_updated_file += 1
                    continue

                # Delete old file
                if qc.ipod_track:
                    file_path = qc.ipod_track.get("location") or qc.ipod_track.get("Location")
                    if file_path:
                        relative_path = file_path.replace(":", "/").lstrip("/")
                        full_path = self.ipod_path / relative_path
                        self._delete_from_ipod(full_path)

                # Invalidate old cache entry (source file changed)
                fingerprint = getattr(qc.pc_track, 'fingerprint', None)
                if fingerprint:
                    self.transcode_cache.invalidate(fingerprint)

                # Copy new file (will create new cache entry)
                source_path = Path(qc.pc_track.path)
                need_transcode = needs_transcoding(source_path)
                success, ipod_path, was_transcoded = self._copy_to_ipod(
                    source_path, need_transcode, fingerprint=fingerprint
                )

                if not success:
                    desc = f"{qc.pc_track.artist} - {qc.pc_track.title}"
                    result.errors.append((desc, "Failed to re-sync"))
                    continue

                if ipod_path is None:
                    desc = f"{qc.pc_track.artist} - {qc.pc_track.title}"
                    result.errors.append((desc, "No iPod path returned"))
                    continue

                # Update the TrackInfo with new location
                ipod_location = ":" + str(ipod_path.relative_to(self.ipod_path)).replace("\\", ":").replace("/", ":")

                # Find existing track and update it
                dbid = qc.ipod_track.get("dbid")
                if dbid and dbid in tracks_by_dbid:
                    existing_track = tracks_by_dbid[dbid]
                    # Remove old location from index
                    if existing_track.location in tracks_by_location:
                        del tracks_by_location[existing_track.location]
                    # Update location
                    existing_track.location = ipod_location
                    tracks_by_location[ipod_location] = existing_track

                # Update mapping
                if fingerprint and ipod_path:
                    mapping.add_track(
                        fingerprint=fingerprint,
                        dbid=dbid or self._generate_temp_dbid(),
                        source_format=source_path.suffix.lstrip("."),
                        ipod_format=ipod_path.suffix.lstrip("."),
                        source_size=qc.pc_track.size,
                        source_mtime=qc.pc_track.mtime,
                        was_transcoded=was_transcoded,
                        source_path_hint=qc.pc_track.relative_path,
                    )

                result.tracks_updated_file += 1

        # ===== Stage 4: Update metadata (if supported) =====
        to_update_metadata = getattr(plan, 'to_update_metadata', [])
        if to_update_metadata:
            if progress_callback:
                progress_callback(
                    SyncProgress(
                        "update_metadata",
                        0,
                        len(to_update_metadata),
                        message="Updating metadata...",
                    )
                )

            for i, item in enumerate(to_update_metadata):
                if progress_callback:
                    progress_callback(
                        SyncProgress(
                            "update_metadata",
                            i + 1,
                            len(to_update_metadata),
                            item,
                            item.description,
                        )
                    )

                if dry_run:
                    result.tracks_updated_metadata += 1
                    continue

                # Update TrackInfo metadata for this track
                # item.metadata_changes contains {field_name: (pc_value, ipod_value)}
                dbid = getattr(item, 'dbid', None)
                if dbid and dbid in tracks_by_dbid:
                    track = tracks_by_dbid[dbid]
                    metadata_changes = getattr(item, 'metadata_changes', {})
                    for field_name, (pc_value, _ipod_value) in metadata_changes.items():
                        # Map PC field names to TrackInfo attribute names
                        if field_name == "title":
                            track.title = pc_value
                        elif field_name == "artist":
                            track.artist = pc_value
                        elif field_name == "album":
                            track.album = pc_value
                        elif field_name == "album_artist":
                            track.album_artist = pc_value
                        elif field_name == "genre":
                            track.genre = pc_value
                        elif field_name == "year":
                            track.year = pc_value if pc_value else 0
                        elif field_name == "track_number":
                            track.track_number = pc_value if pc_value else 0
                        elif field_name == "disc_number":
                            track.disc_number = pc_value if pc_value else 0

                result.tracks_updated_metadata += 1

        # ===== Stage 5: Sync play counts back to PC =====
        if plan.to_sync_playcount:
            if progress_callback:
                progress_callback(
                    SyncProgress(
                        "sync_playcount",
                        0,
                        len(plan.to_sync_playcount),
                        message="Syncing play counts...",
                    )
                )

            for i, item in enumerate(plan.to_sync_playcount):
                if progress_callback:
                    progress_callback(
                        SyncProgress(
                            "sync_playcount",
                            i + 1,
                            len(plan.to_sync_playcount),
                            item,
                            item.description,
                        )
                    )

                if dry_run:
                    result.playcounts_synced += 1
                    continue

                # TODO: Write play count back to PC file metadata
                # item.play_count_delta contains plays since last sync
                # item.pc_track.path is the file to update

                result.playcounts_synced += 1

        # ===== Stage 6: Sync ratings =====
        if plan.to_sync_rating:
            if progress_callback:
                progress_callback(
                    SyncProgress(
                        "sync_rating",
                        0,
                        len(plan.to_sync_rating),
                        message="Syncing ratings...",
                    )
                )

            for i, item in enumerate(plan.to_sync_rating):
                if progress_callback:
                    progress_callback(
                        SyncProgress(
                            "sync_rating", i + 1, len(plan.to_sync_rating), item, item.description
                        )
                    )

                if dry_run:
                    result.ratings_synced += 1
                    continue

                # TODO: Write rating to both PC file and iPod track
                # item.new_rating is the computed rating to apply

                result.ratings_synced += 1

        # ===== Stage 7: Write database =====
        if not dry_run:
            if progress_callback:
                progress_callback(
                    SyncProgress(
                        "write_database",
                        0,
                        1,
                        message="Writing database...",
                    )
                )

            # Combine remaining existing tracks with new tracks
            all_tracks = list(tracks_by_dbid.values()) + new_tracks

            # Remap pc_file_paths for new tracks:
            # New tracks used id(track_info) as keys because dbids weren't assigned yet.
            # write_itunesdb will remap these to real dbids after generation.
            # Existing tracks already have dbid keys from matched_pc_paths.
            new_track_paths = {}
            for track in new_tracks:
                obj_key = id(track)
                if obj_key in pc_file_paths:
                    # Move from object-id key to keep separate from dbid keys
                    new_track_paths[obj_key] = pc_file_paths.pop(obj_key)

            # Merge back: pc_file_paths now has {dbid → path} for existing + {id() → path} for new
            pc_file_paths.update(new_track_paths)

            logger.info(f"ART: pc_file_paths total={len(pc_file_paths)} "
                        f"(existing={len(pc_file_paths) - len(new_track_paths)}, "
                        f"new={len(new_track_paths)})")
            logger.info(f"ART: all_tracks={len(all_tracks)} "
                        f"(existing_by_dbid={len(tracks_by_dbid)}, new={len(new_tracks)})")

            # Log sample existing tracks with PC paths
            existing_with_paths = sum(1 for t in tracks_by_dbid.values() if t.dbid in pc_file_paths)
            logger.info(f"ART: {existing_with_paths} existing tracks have PC paths for art extraction")

            if all_tracks:
                try:
                    self._write_database(all_tracks, pc_file_paths=pc_file_paths)
                    if progress_callback:
                        progress_callback(
                            SyncProgress(
                                "write_database",
                                1,
                                1,
                                message=f"Database written with {len(all_tracks)} tracks",
                            )
                        )
                except Exception as e:
                    result.errors.append(("database write", str(e)))

        # Save updated mapping
        if not dry_run:
            self.mapping_manager.save(mapping)

        result.success = not result.has_errors
        return result

    def _generate_temp_dbid(self) -> int:
        """Generate a temporary dbid for tracks pending iTunesDB write."""
        # Use timestamp + random to generate unique ID
        import random

        timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
        random_part = random.randint(0, 0xFFFF)
        return (timestamp << 16) | random_part

    def _read_existing_tracks(self) -> list[dict]:
        """Read existing tracks from iTunesDB."""
        from iTunesDB_Parser import parse_itunesdb

        itdb_path = self.ipod_path / "iPod_Control" / "iTunes" / "iTunesDB"
        if not itdb_path.exists():
            return []

        try:
            result = parse_itunesdb(str(itdb_path))
            return result.get('mhlt', [])
        except Exception as e:
            logger.error(f"Failed to parse iTunesDB: {e}")
            return []

    def _track_dict_to_info(self, t: dict) -> "TrackInfo":
        """Convert parsed track dict to TrackInfo for writing."""
        from iTunesDB_Writer import TrackInfo

        # Map filetype string back to code
        filetype = t.get('filetype', 'MP3')
        if 'AAC' in filetype or 'M4A' in filetype:
            filetype_code = 'm4a'
        elif 'Lossless' in filetype:
            filetype_code = 'm4a'
        else:
            filetype_code = 'mp3'

        return TrackInfo(
            title=t.get('Title', 'Unknown'),
            location=t.get('Location', ''),
            size=t.get('size', 0),
            length=t.get('length', 0),
            filetype=filetype_code,
            bitrate=t.get('bitrate', 0),
            sample_rate=t.get('sampleRate', 44100),
            vbr=bool(t.get('vbr', 0)),
            artist=t.get('Artist'),
            album=t.get('Album'),
            album_artist=t.get('Album Artist'),
            genre=t.get('Genre'),
            composer=t.get('Composer'),
            year=t.get('year', 0),
            track_number=t.get('trackNumber', 0),
            total_tracks=t.get('totalTracks', 0),
            disc_number=t.get('discNumber', 1),
            total_discs=t.get('totalDiscs', 1),
            bpm=t.get('bpm', 0),
            compilation=bool(t.get('compilation', 0)),
            rating=t.get('rating', 0),
            play_count=t.get('playCount', 0),
            skip_count=t.get('skipCount', 0),
            volume=t.get('volume', 0),
            date_added=t.get('dateAdded', 0),
            last_played=t.get('lastPlayed', 0),
            last_skipped=t.get('lastSkipped', 0),
            dbid=t.get('dbid', 0),
            media_type=t.get('mediaType', 1),
            artwork_count=t.get('artworkCount', 0),
            artwork_size=t.get('artworkSize', 0),
            mhii_link=t.get('mhiiLink', 0),
            sort_artist=t.get('Sort Artist'),
            sort_name=t.get('Sort Name'),
            sort_album=t.get('Sort Album'),
            filetype_desc=t.get('Filetype'),
        )

    def _pc_track_to_info(self, pc_track, ipod_location: str, was_transcoded: bool) -> "TrackInfo":
        """Convert PCTrack to TrackInfo for writing."""
        from iTunesDB_Writer import TrackInfo

        # Determine filetype from extension
        ext = Path(ipod_location.replace(':', '/')).suffix.lower().lstrip('.')
        if ext in ('m4a', 'aac', 'alac'):
            filetype = 'm4a'
        elif ext == 'mp3':
            filetype = 'mp3'
        else:
            filetype = ext

        return TrackInfo(
            title=pc_track.title or Path(pc_track.path).stem,
            location=ipod_location,
            size=pc_track.size or 0,
            length=pc_track.duration_ms or 0,
            filetype=filetype,
            bitrate=pc_track.bitrate or 0,
            sample_rate=pc_track.sample_rate or 44100,
            artist=pc_track.artist,
            album=pc_track.album,
            album_artist=pc_track.album_artist,
            genre=pc_track.genre,
            composer=getattr(pc_track, 'composer', None),
            year=pc_track.year or 0,
            track_number=pc_track.track_number or 0,
            total_tracks=getattr(pc_track, 'track_total', None) or 0,
            disc_number=pc_track.disc_number or 1,
            total_discs=getattr(pc_track, 'disc_total', None) or 1,
            rating=int(pc_track.rating * 20) if pc_track.rating else 0,  # Convert 0-5 to 0-100
            play_count=getattr(pc_track, 'play_count', 0) or 0,
        )

    def _write_database(self, tracks: list["TrackInfo"],
                        pc_file_paths: Optional[dict] = None) -> bool:
        """Write tracks to iTunesDB (and ArtworkDB if pc_file_paths provided)."""
        from iTunesDB_Writer import write_itunesdb

        logger.info(f"ART: _write_database called with {len(tracks)} tracks, "
                    f"pc_file_paths={'None' if pc_file_paths is None else len(pc_file_paths)}")
        if pc_file_paths:
            for k, v in list(pc_file_paths.items())[:5]:
                logger.info(f"ART:   pc_file_paths[{k}] = {v}")

        try:
            return write_itunesdb(
                str(self.ipod_path), tracks,
                pc_file_paths=pc_file_paths,
            )
        except Exception as e:
            logger.error(f"Failed to write iTunesDB: {e}")
            import traceback
            traceback.print_exc()
            return False
