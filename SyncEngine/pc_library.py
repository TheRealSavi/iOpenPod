"""
PC Library Scanner - Scans a folder for music files and extracts metadata.

Uses mutagen for metadata extraction. Supports:
- MP3 (.mp3)
- AAC/M4A (.m4a, .m4p, .aac)
- FLAC (.flac)
- ALAC (in .m4a container)
- WAV (.wav)
- AIFF (.aif, .aiff)
- Ogg Vorbis (.ogg)
- Opus (.opus)
"""

import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Iterator, Callable
import logging

try:
    import mutagen

    MUTAGEN_AVAILABLE = True
except ImportError:
    mutagen = None  # type: ignore
    MUTAGEN_AVAILABLE = False
    logging.warning("mutagen not installed - PC library scanning disabled")


# Supported audio extensions
AUDIO_EXTENSIONS = {
    ".mp3",
    ".m4a",
    ".m4p",
    ".aac",
    ".flac",
    ".wav",
    ".aif",
    ".aiff",
    ".ogg",
    ".opus",
    ".wma",
    ".alac",
}

# Formats that need transcoding for iPod
NEEDS_TRANSCODING = {
    ".flac",
    ".wav",
    ".aif",
    ".aiff",
    ".ogg",
    ".opus",
    ".wma",
    ".alac",
}

# Formats iPod can play natively
IPOD_NATIVE = {
    ".mp3",
    ".m4a",
    ".m4p",
    ".aac",
}


@dataclass
class PCTrack:
    """A music track on the PC."""

    # File info
    path: str  # Absolute path
    relative_path: str  # Relative to library root
    filename: str
    extension: str
    mtime: float  # Modification time
    size: int  # File size in bytes

    # Metadata (from tags)
    title: str
    artist: str
    album: str
    album_artist: Optional[str]
    genre: Optional[str]
    year: Optional[int]
    track_number: Optional[int]
    track_total: Optional[int]
    disc_number: Optional[int]
    disc_total: Optional[int]
    duration_ms: int  # Duration in milliseconds
    bitrate: Optional[int]  # Bitrate in kbps
    sample_rate: Optional[int]  # Sample rate in Hz
    rating: Optional[int]  # Rating 0-100 (stars × 20, same as iPod)

    # Artwork hash (MD5 of embedded image bytes, for change detection)
    art_hash: Optional[str] = None

    # Computed
    needs_transcoding: bool = False  # True if format not iPod-native

    @property
    def fingerprint(self) -> tuple:
        """Return a tuple for matching (artist, album, title, duration)."""
        return (self.artist.lower(), self.album.lower(), self.title.lower(), self.duration_ms)


class PCLibrary:
    """
    Scanner for PC music library.

    Usage:
        library = PCLibrary("D:/Music")

        # Scan all tracks
        for track in library.scan():
            print(f"{track.artist} - {track.title}")

        # Get track count first
        count = library.count_audio_files()

        # Scan with progress callback
        def on_progress(current, total, track):
            print(f"{current}/{total}: {track.title}")

        tracks = list(library.scan(progress_callback=on_progress))
    """

    def __init__(self, root_path: str | Path):
        self.root_path = Path(root_path).resolve()
        if not self.root_path.exists():
            raise ValueError(f"Library path does not exist: {self.root_path}")
        if not self.root_path.is_dir():
            raise ValueError(f"Library path is not a directory: {self.root_path}")

    def count_audio_files(self) -> int:
        """Count total audio files in library (fast, no metadata reading)."""
        count = 0
        for root, _, files in os.walk(self.root_path):
            for filename in files:
                if Path(filename).suffix.lower() in AUDIO_EXTENSIONS:
                    count += 1
        return count

    def scan(
        self,
        progress_callback: Optional[Callable[[int, int, PCTrack], None]] = None,
    ) -> Iterator[PCTrack]:
        """
        Scan the library and yield PCTrack objects.

        Args:
            progress_callback: Optional callback(current, total, track) for progress updates
        """
        if not MUTAGEN_AVAILABLE:
            raise RuntimeError("mutagen is required for library scanning. Install with: pip install mutagen")

        # First count files for progress
        total = self.count_audio_files() if progress_callback else 0
        current = 0

        for root, _, files in os.walk(self.root_path):
            for filename in files:
                ext = Path(filename).suffix.lower()
                if ext not in AUDIO_EXTENSIONS:
                    continue

                file_path = Path(root) / filename
                try:
                    track = self._read_track(file_path)
                    if track:
                        current += 1
                        if progress_callback:
                            progress_callback(current, total, track)
                        yield track
                except Exception as e:
                    logging.warning(f"Failed to read {file_path}: {e}")
                    current += 1
                    continue

    def _read_track(self, file_path: Path) -> Optional[PCTrack]:
        """Read metadata from a single audio file."""
        stat = file_path.stat()
        ext = file_path.suffix.lower()

        # Try to open with mutagen
        if mutagen is None:
            return None
        try:
            audio = mutagen.File(file_path, easy=True)  # type: ignore[union-attr]
            if audio is None:
                # Try without easy mode for some formats
                audio = mutagen.File(file_path)  # type: ignore[union-attr]
                if audio is None:
                    return None
        except Exception as e:
            logging.debug(f"mutagen failed on {file_path}: {e}")
            return None

        # Extract metadata based on file type
        metadata = self._extract_metadata(audio, ext)

        # Extract art hash for artwork change detection
        art_hash = self._compute_art_hash(file_path)

        return PCTrack(
            path=str(file_path),
            relative_path=str(file_path.relative_to(self.root_path)),
            filename=file_path.name,
            extension=ext,
            mtime=stat.st_mtime,
            size=stat.st_size,
            title=metadata.get("title", file_path.stem),
            artist=metadata.get("artist", "Unknown Artist"),
            album=metadata.get("album", "Unknown Album"),
            album_artist=metadata.get("album_artist"),
            genre=metadata.get("genre"),
            year=metadata.get("year"),
            track_number=metadata.get("track_number"),
            track_total=metadata.get("track_total"),
            disc_number=metadata.get("disc_number"),
            disc_total=metadata.get("disc_total"),
            duration_ms=metadata.get("duration_ms", 0),
            bitrate=metadata.get("bitrate"),
            sample_rate=metadata.get("sample_rate"),
            rating=metadata.get("rating"),
            art_hash=art_hash,
            needs_transcoding=ext in NEEDS_TRANSCODING,
        )

    def _compute_art_hash(self, file_path: Path) -> Optional[str]:
        """Compute MD5 hash of embedded album art for change detection."""
        try:
            from ArtworkDB_Writer.art_extractor import extract_art, art_hash
            art_bytes = extract_art(str(file_path))
            if art_bytes:
                return art_hash(art_bytes)
        except Exception as e:
            logging.debug(f"Could not extract art from {file_path}: {e}")
        return None

    def _extract_metadata(self, audio, ext: str) -> dict:
        """Extract metadata from mutagen object."""
        metadata: dict = {}

        # Duration (always available from audio info)
        if hasattr(audio, "info") and audio.info:
            if hasattr(audio.info, "length"):
                metadata["duration_ms"] = int(audio.info.length * 1000)
            if hasattr(audio.info, "bitrate"):
                metadata["bitrate"] = audio.info.bitrate // 1000 if audio.info.bitrate else None
            if hasattr(audio.info, "sample_rate"):
                metadata["sample_rate"] = audio.info.sample_rate

        # Handle different tag formats
        if ext == ".mp3":
            metadata.update(self._extract_id3(audio))
        elif ext in {".m4a", ".m4p", ".aac"}:
            metadata.update(self._extract_mp4(audio))
        elif ext == ".flac":
            metadata.update(self._extract_vorbis(audio))
        elif ext in {".ogg", ".opus"}:
            metadata.update(self._extract_vorbis(audio))
        elif ext in {".aif", ".aiff"}:
            metadata.update(self._extract_id3(audio))
        elif ext == ".wav":
            metadata.update(self._extract_id3(audio))
        else:
            # Try easy interface as fallback
            metadata.update(self._extract_easy(audio))

        return metadata

    def _extract_easy(self, audio) -> dict:
        """Extract from mutagen easy interface."""
        metadata = {}

        def get_first(key: str) -> Optional[str]:
            val = audio.get(key)
            if val and len(val) > 0:
                return str(val[0])
            return None

        metadata["title"] = get_first("title")
        metadata["artist"] = get_first("artist")
        metadata["album"] = get_first("album")
        metadata["album_artist"] = get_first("albumartist") or get_first("album artist")
        metadata["genre"] = get_first("genre")

        # Year
        date = get_first("date") or get_first("year")
        if date:
            try:
                metadata["year"] = int(date[:4])
            except (ValueError, TypeError):
                pass

        # Track number
        track = get_first("tracknumber")
        if track:
            metadata.update(self._parse_track_number(track))

        # Disc number
        disc = get_first("discnumber")
        if disc:
            metadata.update(self._parse_disc_number(disc))

        return metadata

    def _extract_id3(self, audio) -> dict:
        """Extract from ID3 tags (MP3, AIFF, WAV)."""
        metadata = self._extract_easy(audio)

        # Extract rating from POPM (Popularimeter) frame
        # POPM rating is 0-255, convert to 0-100 (iPod style: stars × 20)
        if hasattr(audio, 'tags') and audio.tags:
            for key in audio.tags:
                if key.startswith('POPM'):
                    popm = audio.tags[key]
                    if hasattr(popm, 'rating'):
                        # Convert 0-255 to 0-100
                        # Common mappings: 1=1star, 64=2star, 128=3star, 196=4star, 255=5star
                        rating_255 = popm.rating
                        if rating_255 == 0:
                            metadata['rating'] = 0
                        elif rating_255 <= 31:
                            metadata['rating'] = 20  # 1 star
                        elif rating_255 <= 95:
                            metadata['rating'] = 40  # 2 stars
                        elif rating_255 <= 159:
                            metadata['rating'] = 60  # 3 stars
                        elif rating_255 <= 223:
                            metadata['rating'] = 80  # 4 stars
                        else:
                            metadata['rating'] = 100  # 5 stars
                    break
        return metadata

    def _extract_mp4(self, audio) -> dict:
        """Extract from MP4/M4A tags."""
        metadata = {}

        # MP4 uses different tag names
        tag_map = {
            "\xa9nam": "title",
            "\xa9ART": "artist",
            "\xa9alb": "album",
            "aART": "album_artist",
            "\xa9gen": "genre",
            "\xa9day": "year",
        }

        for mp4_key, our_key in tag_map.items():
            val = audio.tags.get(mp4_key) if audio.tags else None
            if val:
                if our_key == "year":
                    try:
                        metadata[our_key] = int(str(val[0])[:4])
                    except (ValueError, TypeError, IndexError):
                        pass
                else:
                    metadata[our_key] = str(val[0])

        # Track number (trkn is a tuple: (track, total))
        trkn = audio.tags.get("trkn") if audio.tags else None
        if trkn and len(trkn) > 0:
            track_info = trkn[0]
            if isinstance(track_info, tuple) and len(track_info) >= 1:
                metadata["track_number"] = track_info[0]
                if len(track_info) >= 2:
                    metadata["track_total"] = track_info[1]

        # Disc number (disk is a tuple: (disc, total))
        disk = audio.tags.get("disk") if audio.tags else None
        if disk and len(disk) > 0:
            disc_info = disk[0]
            if isinstance(disc_info, tuple) and len(disc_info) >= 1:
                metadata["disc_number"] = disc_info[0]
                if len(disc_info) >= 2:
                    metadata["disc_total"] = disc_info[1]

        # Rating - try rtng atom (used by some apps) or iTunes-style
        if audio.tags:
            # rtng atom stores 0-100 directly
            rtng = audio.tags.get("rtng")
            if rtng and len(rtng) > 0:
                try:
                    # rtng is typically 0, 20, 40, 60, 80, 100
                    metadata["rating"] = int(rtng[0])
                except (ValueError, TypeError):
                    pass

        return metadata

    def _extract_vorbis(self, audio) -> dict:
        """Extract from Vorbis comments (FLAC, OGG, Opus)."""
        return self._extract_easy(audio)

    def _parse_track_number(self, value: str) -> dict:
        """Parse track number string like '3' or '3/12'."""
        result = {}
        if "/" in value:
            parts = value.split("/")
            try:
                result["track_number"] = int(parts[0])
                result["track_total"] = int(parts[1])
            except (ValueError, IndexError):
                pass
        else:
            try:
                result["track_number"] = int(value)
            except ValueError:
                pass
        return result

    def _parse_disc_number(self, value: str) -> dict:
        """Parse disc number string like '1' or '1/2'."""
        result = {}
        if "/" in value:
            parts = value.split("/")
            try:
                result["disc_number"] = int(parts[0])
                result["disc_total"] = int(parts[1])
            except (ValueError, IndexError):
                pass
        else:
            try:
                result["disc_number"] = int(value)
            except ValueError:
                pass
        return result
