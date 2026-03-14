"""
PC Library Scanner - Scans a folder for media files and extracts metadata.

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
import json
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


import math
import subprocess


def _replaygain_to_soundcheck(gain_db: float) -> int:
    """Convert ReplayGain dB value to iPod Sound Check value.

    Sound Check = round(10^(-gain_dB / 10) × 1000).
    A positive gain_dB (louder) yields a value < 1000 (attenuate).
    A negative gain_dB (quieter) yields a value > 1000 (boost).
    """
    try:
        return max(0, round(math.pow(10, -gain_db / 10) * 1000))
    except (OverflowError, ValueError):
        return 0


def _soundcheck_to_replaygain_db(sc: int) -> float:
    """Convert iPod Sound Check value back to ReplayGain dB.

    Inverse of _replaygain_to_soundcheck.
    """
    if sc <= 0:
        return 0.0
    return -10.0 * math.log10(sc / 1000.0)


def _parse_itunnorm(value: str) -> int:
    """Parse iTunNORM (iTunes normalization) string to Sound Check value.

    iTunNORM is a space-separated string of 10 hex values written by iTunes.
    The first two fields are the Sound Check values for left and right channels.
    We take max(left, right) as the Sound Check value.

    Format: " 00000A8C 00000A8C 00003F28 00003F28 00024CA8 ..."
    """
    try:
        parts = value.strip().split()
        if len(parts) < 2:
            return 0
        left = int(parts[0], 16)
        right = int(parts[1], 16)
        return max(left, right)
    except (ValueError, IndexError):
        return 0


def compute_sound_check(file_path: str, ffmpeg_path: str | None = None) -> int:
    """Compute Sound Check value for a file using ffmpeg EBU R128 loudness.

    Runs ffmpeg's ebur128 filter to measure integrated loudness (LUFS),
    then converts to the iPod Sound Check encoding.

    The target loudness for Sound Check is approximately -16.5 LUFS
    (empirically derived from iTunes' algorithm).

    Returns 0 on failure.
    """
    if not ffmpeg_path:
        from .transcoder import find_ffmpeg
        ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path:
        return 0

    try:
        cmd = [
            ffmpeg_path, "-i", str(file_path),
            "-af", "ebur128=framelog=verbose",
            "-f", "null", "-",
        ]
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
        # Parse integrated loudness from stderr
        # The line looks like: "    I:         -14.3 LUFS"
        integrated_lufs = None
        for line in proc.stderr.splitlines():
            stripped = line.strip()
            if stripped.startswith("I:") and "LUFS" in stripped:
                parts = stripped.split()
                for i, p in enumerate(parts):
                    if p == "LUFS" and i > 0:
                        try:
                            integrated_lufs = float(parts[i - 1])
                        except ValueError:
                            pass
                        break

        if integrated_lufs is None:
            return 0

        # Target loudness: -16.5 LUFS (iTunes reference level)
        # gain_db = target - measured → positive means track is too loud
        TARGET_LUFS = -16.5
        gain_db = TARGET_LUFS - integrated_lufs
        return _replaygain_to_soundcheck(gain_db)

    except (subprocess.TimeoutExpired, OSError, ValueError) as e:
        logging.debug("compute_sound_check failed for %s: %s", file_path, e)
        return 0


def write_sound_check_tag(file_path: str, sound_check: int) -> bool:
    """Write computed Sound Check value into file metadata tags.

    Stores as:
    - MP3: TXXX:REPLAYGAIN_TRACK_GAIN (dB string)
    - M4A: ----:com.apple.iTunes:replaygain_track_gain
    - FLAC/Ogg: REPLAYGAIN_TRACK_GAIN

    Returns True on success.
    """
    if not MUTAGEN_AVAILABLE or not sound_check:
        return False

    gain_db = _soundcheck_to_replaygain_db(sound_check)
    gain_str = f"{gain_db:+.2f} dB"

    try:
        audio = mutagen.File(file_path)  # type: ignore
        if audio is None:
            return False

        ext = Path(file_path).suffix.lower()

        if ext == ".mp3":
            from mutagen.id3 import TXXX  # type: ignore[attr-defined]
            # Remove existing if any
            for key in list(audio.tags or []):
                if key.startswith('TXXX:') and 'REPLAYGAIN_TRACK_GAIN' in key.upper():
                    del audio.tags[key]
            audio.tags.add(TXXX(
                encoding=3, desc='REPLAYGAIN_TRACK_GAIN', text=[gain_str]
            ))
            audio.save()

        elif ext in (".m4a", ".m4b", ".m4p", ".aac"):
            from mutagen.mp4 import MP4FreeForm, AtomDataType
            audio["----:com.apple.iTunes:replaygain_track_gain"] = [
                MP4FreeForm(gain_str.encode("utf-8"), dataformat=AtomDataType.UTF8)
            ]
            audio.save()

        elif ext in (".flac", ".ogg", ".opus"):
            audio["REPLAYGAIN_TRACK_GAIN"] = [gain_str]
            audio.save()

        else:
            return False

        return True
    except Exception as e:
        logging.debug("write_sound_check_tag failed for %s: %s", file_path, e)
        return False


def _parse_itun_smpb(value: str) -> dict:
    """Parse an iTunes iTunSMPB freeform atom into gapless components.

    Format: " 00000000 {pregap_hex} {postgap_hex} {total_pcm_samples_hex} ..."
    The first field is always 00000000 (reserved).  Fields 2/3/4 are the
    encoder delay (pregap), encoder padding (postgap), and the net PCM sample
    count of the actual audio content (excluding pregap + postgap).

    Written by iTunes and Apple's Core Audio AAC/ALAC encoder (aac_at on
    macOS).  Other FFmpeg encoders (libfdk_aac, built-in aac, alac) typically
    do not write this atom.

    Returns a dict with pregap, postgap, sample_count keys (only if valid).
    """
    parts = value.strip().split()
    if len(parts) < 4:
        return {}
    try:
        pregap = int(parts[1], 16)
        postgap = int(parts[2], 16)
        total_samples = int(parts[3], 16)
        result = {}
        if pregap >= 0:
            result["pregap"] = pregap
        if postgap >= 0:
            result["postgap"] = postgap
        if total_samples > 0:
            result["sample_count"] = total_samples
        return result
    except (ValueError, IndexError):
        return {}


def _coerce_mp4_freeform_text(value) -> str:
    """Convert mutagen MP4 freeform atom payload to plain text.

    MP4 freeform atoms may be returned as bytes-like objects.  Decoding them
    explicitly avoids ``str(bytes)`` representations like ``b'...`` which
    break downstream parsers.
    """
    try:
        if isinstance(value, (bytes, bytearray)):
            return bytes(value).decode("utf-8", errors="replace")
        return str(value)
    except Exception:
        return ""


def _extract_gapless_info(audio) -> dict:
    """Extract gapless playback info from mutagen audio object.

    Returns dict with pregap, postgap, sample_count keys.
    """
    result: dict = {}
    info = getattr(audio, "info", None)
    if info is None:
        return result

    sample_rate = getattr(info, "sample_rate", 0)

    # FLAC exposes an exact integer total_samples in STREAMINFO — prefer it
    # over length × sample_rate which has floating-point rounding error.
    total_samples = getattr(info, "total_samples", 0)
    if total_samples:
        result["sample_count"] = total_samples
    else:
        length = getattr(info, "length", 0)
        if sample_rate and length:
            # Use rounding to avoid systematic undercount from float truncation.
            result["sample_count"] = round(length * sample_rate)

    # MP3-specific: encoder delay / padding (LAME header)
    # mutagen stores these in info for LAME-encoded MP3s.
    encoder_delay = getattr(info, "encoder_delay", 0)
    encoder_padding = getattr(info, "encoder_padding", 0)
    if encoder_delay:
        result["pregap"] = encoder_delay
    # encoder_padding maps to iPod's postgap field (0xC8 in MHIT).
    if encoder_padding:
        result["postgap"] = encoder_padding

    # VBR detection — mutagen exposes bitrate_mode on MP3 info objects
    # BitrateMode.VBR = 2, BitrateMode.ABR = 1, BitrateMode.CBR = 0
    bitrate_mode = getattr(info, "bitrate_mode", None)
    if bitrate_mode is not None:
        # VBR or ABR both count as variable bitrate for iPod purposes
        result["vbr"] = int(bitrate_mode) >= 1

    return result


def _probe_sample_count_ffprobe(path) -> int:
    """Return sample_count from ffprobe stream timing when available.

    For MP4/M4A/AAC this can be more reliable than ``length * sample_rate``
    because it uses integer stream timing (duration_ts + time_base).
    """
    try:
        from .transcoder import find_ffmpeg

        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            return 0
        ffprobe = Path(ffmpeg).with_name("ffprobe")
        if not ffprobe.exists():
            return 0

        proc = subprocess.run(
            [
                str(ffprobe),
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=duration_ts,time_base,sample_rate",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if proc.returncode != 0:
            return 0

        payload = json.loads(proc.stdout)
        streams = payload.get("streams", [])
        if not streams:
            return 0
        stream = streams[0]

        duration_ts = int(stream.get("duration_ts", 0) or 0)
        sample_rate = int(stream.get("sample_rate", 0) or 0)
        time_base = str(stream.get("time_base", ""))
        if duration_ts <= 0 or sample_rate <= 0 or "/" not in time_base:
            return 0

        num_s, den_s = time_base.split("/", 1)
        num = int(num_s)
        den = int(den_s)
        if num <= 0 or den <= 0:
            return 0

        sample_count = round(duration_ts * sample_rate * num / den)
        return sample_count if sample_count > 0 else 0
    except Exception:
        return 0


def probe_gapless_info(path) -> dict:
    """Probe an audio file and return its gapless playback info.

    Works for any format mutagen supports.  For M4A files additionally parses
    the ``iTunSMPB`` freeform atom when present (written by iTunes and Apple's
    Core Audio AAC/ALAC encoder on macOS), which gives exact integer pregap,
    postgap, and net PCM sample count values.

    Returns a dict with any subset of: pregap, postgap, sample_count,
    sample_rate.  Returns an empty dict on any read error.
    """
    if not MUTAGEN_AVAILABLE or mutagen is None:
        return {}
    try:
        audio = mutagen.File(str(path))  # type: ignore[union-attr]
        if audio is None:
            return {}
        result = _extract_gapless_info(audio)
        # For M4A: iTunSMPB has exact integer values — prefer over float-math.
        ext = Path(path).suffix.lower()
        has_itun_smpb = False
        if ext in (".m4a", ".m4b", ".m4p", ".aac") and audio.tags:
            itun_smpb = audio.tags.get("----:com.apple.iTunes:iTunSMPB")
            if itun_smpb and len(itun_smpb) > 0:
                smpb = _parse_itun_smpb(_coerce_mp4_freeform_text(itun_smpb[0]))
                if smpb:
                    has_itun_smpb = True
                    result.update(smpb)
        # If iTunSMPB isn't present, use ffprobe stream timing for M4A/AAC.
        if ext in (".m4a", ".m4b", ".m4p", ".aac") and not has_itun_smpb:
            exact_samples = _probe_sample_count_ffprobe(path)
            if exact_samples:
                result["sample_count"] = exact_samples
        info = getattr(audio, "info", None)
        if info:
            sr = getattr(info, "sample_rate", 0)
            if sr:
                result["sample_rate"] = sr
        return result
    except Exception:
        return {}


# Supported audio extensions
AUDIO_EXTENSIONS = {
    ".mp3",
    ".m4a",
    ".m4p",
    ".aac",
    ".m4b",
    ".flac",
    ".wav",
    ".aif",
    ".aiff",
    ".ogg",
    ".opus",
    ".wma",
}

# Supported video extensions (iPod Video 5G+, Classic, Nano 3G+)
VIDEO_EXTENSIONS = {
    ".m4v",
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
}

# All supported media extensions (audio + video)
MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS

# Formats that need transcoding for iPod
NEEDS_TRANSCODING = {
    ".flac",
    ".wav",
    ".aif",
    ".aiff",
    ".ogg",
    ".opus",
    ".wma",
}

# Video formats that always need transcoding (non-iPod containers)
VIDEO_ALWAYS_TRANSCODE = {
    ".mov",
    ".mkv",
    ".avi",
}

# Video containers that MIGHT be iPod-native (need ffprobe to confirm)
# These are only truly native if they contain H.264 Baseline ≤640x480, 8-bit, stereo AAC
VIDEO_PROBE_CONTAINERS = {
    ".m4v",
    ".mp4",
}

# Formats iPod can play natively
IPOD_NATIVE = {
    ".mp3",
    ".m4a",
    ".m4p",
    ".m4b",
    ".aac",
}

# Video formats iPod can play natively (only if codec is compatible — use probe)
IPOD_NATIVE_VIDEO = {
    ".m4v",
    ".mp4",
}


@dataclass
class PCTrack:
    """A media track on the PC (audio, video, podcast, or audiobook)."""

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

    # Sort tags (for proper ordering on iPod)
    sort_artist: Optional[str] = None
    sort_name: Optional[str] = None
    sort_album: Optional[str] = None
    sort_album_artist: Optional[str] = None
    sort_composer: Optional[str] = None

    # Compilation flag (Various Artists albums)
    compilation: bool = False

    # Additional string metadata
    comment: Optional[str] = None
    composer: Optional[str] = None
    grouping: Optional[str] = None
    bpm: Optional[int] = None

    # Sound Check / ReplayGain (iPod volume normalization value)
    sound_check: int = 0

    # Gapless playback info (extracted from audio file)
    pregap: int = 0
    postgap: int = 0  # Encoder padding samples at end of track
    sample_count: int = 0  # Total decoded sample count
    gapless_data: int = 0  # Opaque iTunes gapless data (leave 0 for new tracks)

    # VBR flag (auto-detected from mutagen bitrate_mode)
    vbr: bool = False

    # Release date (Unix timestamp, 0 = not set)
    date_released: int = 0

    # Subtitle (TIT3 in ID3, desc atom in MP4 when description uses ldes)
    subtitle: Optional[str] = None

    # Content advisory / explicit flag
    explicit_flag: int = 0  # 0=none, 1=explicit, 2=clean
    has_lyrics: bool = False  # True if embedded lyrics exist
    lyrics: Optional[str] = None  # Full lyrics text (for iPod MHOD type 10)

    # Artwork hash (MD5 of embedded image bytes, for change detection)
    art_hash: Optional[str] = None

    # Video metadata (populated only for video files)
    is_video: bool = False  # True if file is a video
    video_kind: str = ""  # "movie", "music_video", "tv_show", or "" for audio
    show_name: Optional[str] = None  # TV show name
    season_number: Optional[int] = None  # TV show season
    episode_number: Optional[int] = None  # TV show episode number
    episode_id: Optional[str] = None  # Episode ID string
    description: Optional[str] = None  # Track/episode description
    long_description: Optional[str] = None  # Extended description
    network_name: Optional[str] = None  # TV network
    sort_show: Optional[str] = None  # Sort show name

    # Podcast/audiobook detection (populated from stik atom or file extension)
    is_podcast: bool = False     # True if stik=21 or pcst atom present
    is_audiobook: bool = False   # True if stik=2 or .m4b extension
    category: Optional[str] = None  # Podcast/audiobook category (from catg atom)
    podcast_url: Optional[str] = None  # Podcast feed URL (from purl atom)
    podcast_enclosure_url: Optional[str] = None  # Per-episode audio URL (enclosure)

    # Chapter markers (list of {"startpos": ms, "title": str})
    chapters: Optional[list] = None

    # Computed
    needs_transcoding: bool = False  # True if format not iPod-native

    @property
    def fingerprint(self) -> tuple:
        """Return a tuple for matching (artist, album, title, duration)."""
        return (self.artist.lower(), self.album.lower(), self.title.lower(), self.duration_ms)


class PCLibrary:
    """
    Scanner for PC media library.

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

    def count_audio_files(self, include_video: bool = True) -> int:
        """Count total media files in library (fast, no metadata reading).

        Args:
            include_video: When False, only count audio files (skip VIDEO_EXTENSIONS).
        """
        extensions = MEDIA_EXTENSIONS if include_video else AUDIO_EXTENSIONS
        count = 0
        for root, _, files in os.walk(self.root_path):
            for filename in files:
                if Path(filename).suffix.lower() in extensions:
                    count += 1
        return count

    def scan(
        self,
        progress_callback: Optional[Callable[[int, int, PCTrack], None]] = None,
        include_video: bool = True,
    ) -> Iterator[PCTrack]:
        """
        Scan the library and yield PCTrack objects.

        Args:
            progress_callback: Optional callback(current, total, track) for progress updates
            include_video: When False, skip video files entirely.
                           Set to False when syncing to iPods that don't support video.
        """
        if not MUTAGEN_AVAILABLE:
            raise RuntimeError("mutagen is required for library scanning. Install with: pip install mutagen")

        extensions = MEDIA_EXTENSIONS if include_video else AUDIO_EXTENSIONS

        # First count files for progress
        total = self.count_audio_files(include_video=include_video) if progress_callback else 0
        current = 0

        for root, _, files in os.walk(self.root_path):
            for filename in files:
                ext = Path(filename).suffix.lower()
                if ext not in extensions:
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
        """Read metadata from a single audio or video file."""
        stat = file_path.stat()
        ext = file_path.suffix.lower()
        is_video = ext in VIDEO_EXTENSIONS

        # Try to open with mutagen
        if mutagen is None:
            return None
        try:
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

        # Determine video kind from metadata or extension
        video_kind = ""
        if is_video:
            video_kind = metadata.get("video_kind", "movie")

        # Detect podcast and audiobook content
        is_podcast = metadata.get("is_podcast", False)
        is_audiobook = metadata.get("is_audiobook", False)
        # .m4b extension is always an audiobook container
        if ext == ".m4b" and not is_audiobook:
            is_audiobook = True

        # Extract chapter markers from audiobooks and podcasts
        chapters = None
        if is_audiobook or is_podcast:
            try:
                from PodcastManager.downloader import extract_chapters
                chapters = extract_chapters(str(file_path))
            except Exception as e:
                logging.debug(f"Chapter extraction failed for {file_path}: {e}")

        # Determine transcoding need
        if is_video:
            if ext in VIDEO_ALWAYS_TRANSCODE:
                needs_tc = True
            elif ext in VIDEO_PROBE_CONTAINERS:
                # Probe the actual codec to decide
                from .transcoder import probe_video_needs_transcode
                needs_tc = probe_video_needs_transcode(file_path)
            else:
                needs_tc = True  # Unknown video format, transcode to be safe
        else:
            needs_tc = ext in NEEDS_TRANSCODING

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
            sort_artist=metadata.get("sort_artist"),
            sort_name=metadata.get("sort_name"),
            sort_album=metadata.get("sort_album"),
            sort_album_artist=metadata.get("sort_album_artist"),
            sort_composer=metadata.get("sort_composer"),
            compilation=metadata.get("compilation", False),
            comment=metadata.get("comment"),
            composer=metadata.get("composer"),
            grouping=metadata.get("grouping"),
            bpm=metadata.get("bpm"),
            sound_check=metadata.get("sound_check", 0),
            pregap=metadata.get("pregap", 0),
            postgap=metadata.get("postgap", 0),
            sample_count=metadata.get("sample_count", 0),
            gapless_data=metadata.get("gapless_data", 0),
            vbr=metadata.get("vbr", False),
            date_released=metadata.get("date_released", 0),
            subtitle=metadata.get("subtitle"),
            explicit_flag=metadata.get("explicit_flag", 0),
            has_lyrics=metadata.get("has_lyrics", False),
            lyrics=metadata.get("lyrics"),
            art_hash=art_hash,
            needs_transcoding=needs_tc,
            is_video=is_video,
            video_kind=video_kind,
            show_name=metadata.get("show_name"),
            season_number=metadata.get("season_number"),
            episode_number=metadata.get("episode_number"),
            episode_id=metadata.get("episode_id"),
            description=metadata.get("description"),
            long_description=metadata.get("long_description"),
            network_name=metadata.get("network_name"),
            sort_show=metadata.get("sort_show"),
            is_podcast=is_podcast,
            is_audiobook=is_audiobook,
            category=metadata.get("category"),
            podcast_url=metadata.get("podcast_url"),
            chapters=chapters,
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
        elif ext in {".m4a", ".m4p", ".m4b", ".m4v", ".mp4", ".aac"}:
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

        # Gapless playback info (format-independent via mutagen info)
        gapless = _extract_gapless_info(audio)
        for k, v in gapless.items():
            if k not in metadata:  # don't overwrite format-specific values
                metadata[k] = v

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

    @staticmethod
    def _id3_text(tags, frame_id: str) -> Optional[str]:
        """Get first text value from an ID3 frame, or None."""
        frame = tags.get(frame_id)
        if frame and hasattr(frame, 'text') and frame.text:
            val = str(frame.text[0]).strip()
            if val:
                return val
        return None

    def _extract_id3(self, audio) -> dict:
        """Extract from ID3 tags (MP3, AIFF, WAV)."""
        metadata: dict = {}

        if not (hasattr(audio, 'tags') and audio.tags):
            return metadata

        tags = audio.tags

        def _t(fid):
            return self._id3_text(tags, fid)  # noqa: E731

        # Core metadata from standard ID3 frames
        metadata['title'] = _t('TIT2')
        metadata['artist'] = _t('TPE1')
        metadata['album'] = _t('TALB')
        metadata['album_artist'] = _t('TPE2')
        metadata['genre'] = _t('TCON')

        # Year — try TDRC (ID3v2.4 recording date) then TYER (ID3v2.3)
        for fid in ('TDRC', 'TYER'):
            yr = _t(fid)
            if yr:
                try:
                    metadata['year'] = int(str(yr)[:4])
                except (ValueError, TypeError):
                    pass
                break

        # Track number (TRCK: "3" or "3/12")
        trck = _t('TRCK')
        if trck:
            metadata.update(self._parse_track_number(trck))

        # Disc number (TPOS: "1" or "1/2")
        tpos = _t('TPOS')
        if tpos:
            metadata.update(self._parse_disc_number(tpos))

        # Sort tags
        for frame_id, meta_key in [
            ('TSOP', 'sort_artist'), ('TSOT', 'sort_name'), ('TSOA', 'sort_album'),
            ('TSO2', 'sort_album_artist'), ('TSOC', 'sort_composer'),
        ]:
            val = _t(frame_id)
            if val:
                metadata[meta_key] = val

        # Compilation flag (TCMP frame)
        metadata['compilation'] = _t('TCMP') == '1'

        # Composer (TCOM frame)
        val = _t('TCOM')
        if val:
            metadata['composer'] = val

        # Comment (COMM frame — first non-empty)
        for key in tags:
            if key.startswith('COMM'):
                comm = tags[key]
                if hasattr(comm, 'text') and comm.text:
                    val = str(comm.text[0]) if isinstance(comm.text, list) else str(comm.text)
                    if val:
                        metadata['comment'] = val
                        break

        # BPM (TBPM frame)
        bpm_val = _t('TBPM')
        if bpm_val:
            try:
                metadata['bpm'] = int(float(bpm_val))
            except (ValueError, TypeError):
                pass

        # Grouping (TIT1 or GRP1 frame)
        for frame_id in ('TIT1', 'GRP1'):
            val = _t(frame_id)
            if val:
                metadata['grouping'] = val
                break

        # Subtitle (TIT3 frame)
        val = _t('TIT3')
        if val:
            metadata['subtitle'] = val

        # Release date (TDRL = release date, TDRC = recording date fallback)
        # Convert to Unix timestamp for the iPod's dateReleased field.
        for date_frame_id in ('TDRL', 'TDRC'):
            date_frame = tags.get(date_frame_id)
            if date_frame and hasattr(date_frame, 'text') and date_frame.text:
                try:
                    from datetime import datetime
                    date_text = str(date_frame.text[0])
                    # mutagen ID3 date frames return YYYY, YYYY-MM, or YYYY-MM-DD
                    if len(date_text) >= 10:
                        dt = datetime.strptime(date_text[:10], '%Y-%m-%d')
                    elif len(date_text) >= 7:
                        dt = datetime.strptime(date_text[:7], '%Y-%m')
                    elif len(date_text) >= 4:
                        dt = datetime(int(date_text[:4]), 1, 1)
                    else:
                        continue
                    metadata['date_released'] = int(dt.timestamp())
                    break
                except (ValueError, TypeError, OSError):
                    continue

        # ReplayGain → Sound Check
        for key in tags:
            if key.startswith('TXXX:'):
                txxx = tags[key]
                desc = getattr(txxx, 'desc', '').upper()
                if desc == 'REPLAYGAIN_TRACK_GAIN' and hasattr(txxx, 'text') and txxx.text:
                    try:
                        gain_str = str(txxx.text[0]).replace(' dB', '').strip()
                        metadata['sound_check'] = _replaygain_to_soundcheck(float(gain_str))
                    except (ValueError, TypeError):
                        pass
                    break

        # Lyrics presence (USLT frame)
        for key in tags:
            if key.startswith('USLT'):
                uslt = tags[key]
                if hasattr(uslt, 'text') and uslt.text:
                    text = str(uslt.text).strip()
                    if text:
                        metadata['has_lyrics'] = True
                        metadata['lyrics'] = text
                break

        # Explicit flag — check TXXX:ITUNESADVISORY (iTunes convention)
        # Values: 1=explicit, 2=clean
        for key in tags:
            if key.startswith('TXXX:'):
                txxx = tags[key]
                desc = getattr(txxx, 'desc', '').upper()
                if desc in ('ITUNESADVISORY', 'CONTENTRATING'):
                    try:
                        val = int(str(txxx.text[0]))
                        if val in (1, 2, 4):
                            metadata['explicit_flag'] = 1 if val in (1, 4) else 2
                    except (ValueError, TypeError, IndexError):
                        pass
                    break

        # TXXX-based metadata (video/podcast fields, sort show)
        _txxx_map = {
            'DESCRIPTION': 'description',
            'SHOW': 'show_name',
            'TVSHOW': 'show_name',
            'EPISODE_ID': 'episode_id',
            'NETWORK': 'network_name',
            'TVNETWORK': 'network_name',
            'SORT_SHOW': 'sort_show',
            'SHOWSORT': 'sort_show',
        }
        for key in tags:
            if key.startswith('TXXX:'):
                txxx = tags[key]
                desc = getattr(txxx, 'desc', '').upper()
                target = _txxx_map.get(desc)
                if target and target not in metadata and hasattr(txxx, 'text') and txxx.text:
                    metadata[target] = str(txxx.text[0]).strip()

        # TXXX numeric fields: season/episode number
        for key in tags:
            if key.startswith('TXXX:'):
                txxx = tags[key]
                desc = getattr(txxx, 'desc', '').upper()
                if desc in ('SEASON', 'SEASON_NUMBER', 'TVSEASONNUMBER') and 'season_number' not in metadata:
                    try:
                        metadata['season_number'] = int(str(txxx.text[0]))
                    except (ValueError, TypeError, IndexError):
                        pass
                elif desc in ('EPISODE', 'EPISODE_NUMBER', 'TVEPISODENUMBER') and 'episode_number' not in metadata:
                    try:
                        metadata['episode_number'] = int(str(txxx.text[0]))
                    except (ValueError, TypeError, IndexError):
                        pass

        # Podcast flag (PCST frame — Apple non-standard ID3)
        pcst = tags.get('PCST')
        if pcst and hasattr(pcst, 'text') and pcst.text:
            metadata['is_podcast'] = True

        # Podcast category (TCAT frame — Apple non-standard ID3)
        val = _t('TCAT')
        if val:
            metadata['category'] = val

        # Podcast feed URL (WFED frame — Apple non-standard ID3)
        wfed = tags.get('WFED')
        if wfed:
            if hasattr(wfed, 'url') and wfed.url:
                metadata['podcast_url'] = str(wfed.url)
            elif hasattr(wfed, 'text') and wfed.text:
                metadata['podcast_url'] = str(wfed.text[0])

        # Extract rating from POPM (Popularimeter) frame
        # POPM rating is 0-255, convert to 0-100 (iPod style: stars × 20)
        for key in tags:
            if key.startswith('POPM'):
                popm = tags[key]
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

        # Content advisory (explicit/clean) from rtng atom
        # NOTE: rtng is the Content Advisory flag, NOT the star rating.
        # Values: 0=none, 1=explicit, 2=clean, 4=explicit (old)
        if audio.tags:
            rtng = audio.tags.get("rtng")
            if rtng and len(rtng) > 0:
                try:
                    val = int(rtng[0])
                    if val in (1, 2, 4):
                        metadata["explicit_flag"] = 1 if val in (1, 4) else 2
                except (ValueError, TypeError):
                    pass

            # Sort tags
            sort_map = {
                "soar": "sort_artist",   # Sort Artist
                "sonm": "sort_name",     # Sort Name/Title
                "soal": "sort_album",    # Sort Album
                "soaa": "sort_album_artist",  # Sort Album Artist
                "soco": "sort_composer",      # Sort Composer
            }
            for mp4_key, meta_key in sort_map.items():
                val = audio.tags.get(mp4_key)
                if val and len(val) > 0:
                    metadata[meta_key] = str(val[0])

            # Compilation flag
            cpil = audio.tags.get("cpil")
            if cpil and len(cpil) > 0:
                metadata["compilation"] = bool(cpil[0])

            # Composer
            wrt = audio.tags.get("\xa9wrt")
            if wrt and len(wrt) > 0:
                metadata["composer"] = str(wrt[0])

            # Comment
            cmt = audio.tags.get("\xa9cmt")
            if cmt and len(cmt) > 0:
                metadata["comment"] = str(cmt[0])

            # BPM (tmpo atom stores integer)
            tmpo = audio.tags.get("tmpo")
            if tmpo and len(tmpo) > 0:
                try:
                    metadata["bpm"] = int(tmpo[0])
                except (ValueError, TypeError):
                    pass

            # Grouping
            grp = audio.tags.get("\xa9grp")
            if grp and len(grp) > 0:
                metadata["grouping"] = str(grp[0])

            # ReplayGain → Sound Check (iTunes freeform atom or standard RG tag)
            for rg_key in [
                "----:com.apple.iTunes:replaygain_track_gain",
                "----:com.apple.iTunes:REPLAYGAIN_TRACK_GAIN",
            ]:
                rg = audio.tags.get(rg_key)
                if rg and len(rg) > 0:
                    try:
                        gain_str = str(rg[0]).replace(" dB", "").strip()
                        metadata["sound_check"] = _replaygain_to_soundcheck(float(gain_str))
                    except (ValueError, TypeError):
                        pass
                    break

            # iTunNORM → Sound Check (native iTunes normalization atom)
            # Only use if ReplayGain wasn't found above
            if not metadata.get("sound_check"):
                itunnorm = audio.tags.get("----:com.apple.iTunes:iTunNORM")
                if itunnorm and len(itunnorm) > 0:
                    sc = _parse_itunnorm(str(itunnorm[0]))
                    if sc:
                        metadata["sound_check"] = sc

            # Lyrics presence (©lyr atom)
            lyr = audio.tags.get("\xa9lyr")
            if lyr and len(lyr) > 0 and str(lyr[0]).strip():
                metadata["has_lyrics"] = True
                metadata["lyrics"] = str(lyr[0]).strip()

            # --- Video-specific atoms ---
            # stik: media kind (0/1=Normal/Music, 2=Audiobook, 6=Music Video,
            #                   9=Movie, 10=TV Show, 21=Podcast)
            stik = audio.tags.get("stik")
            if stik and len(stik) > 0:
                try:
                    kind = int(stik[0])
                    _STIK_MAP = {6: "music_video", 9: "movie", 10: "tv_show"}
                    metadata["video_kind"] = _STIK_MAP.get(kind, "")
                    if kind == 2:
                        metadata["is_audiobook"] = True
                    elif kind == 21:
                        metadata["is_podcast"] = True
                except (ValueError, TypeError):
                    pass

            # pcst: Podcast flag atom (boolean, present = podcast)
            pcst = audio.tags.get("pcst")
            if pcst and len(pcst) > 0:
                try:
                    if int(pcst[0]):
                        metadata["is_podcast"] = True
                except (ValueError, TypeError):
                    pass

            # catg: Category (podcasts/audiobooks)
            catg = audio.tags.get("catg")
            if catg and len(catg) > 0:
                metadata["category"] = str(catg[0])

            # purl: Podcast URL
            purl = audio.tags.get("purl")
            if purl and len(purl) > 0:
                metadata["podcast_url"] = str(purl[0])

            # tvsh: TV Show name
            tvsh = audio.tags.get("tvsh")
            if tvsh and len(tvsh) > 0:
                metadata["show_name"] = str(tvsh[0])

            # tven: Episode ID (e.g. "S01E05")
            tven = audio.tags.get("tven")
            if tven and len(tven) > 0:
                metadata["episode_id"] = str(tven[0])

            # tves: Episode number
            tves = audio.tags.get("tves")
            if tves and len(tves) > 0:
                try:
                    metadata["episode_number"] = int(tves[0])
                except (ValueError, TypeError):
                    pass

            # tvsn: Season number
            tvsn = audio.tags.get("tvsn")
            if tvsn and len(tvsn) > 0:
                try:
                    metadata["season_number"] = int(tvsn[0])
                except (ValueError, TypeError):
                    pass

            # tvnn: Network name
            tvnn = audio.tags.get("tvnn")
            if tvnn and len(tvnn) > 0:
                metadata["network_name"] = str(tvnn[0])

            # desc: Short description
            desc_val = audio.tags.get("desc")
            if desc_val and len(desc_val) > 0:
                metadata["description"] = str(desc_val[0])
                # If ldes (long description) is also present, use desc as subtitle
                # (iTunes convention: desc → subtitle, ldes → description)
                ldes_for_sub = audio.tags.get("ldes")
                if ldes_for_sub and len(ldes_for_sub) > 0:
                    metadata["subtitle"] = str(desc_val[0])

            # ldes: Long description
            ldes = audio.tags.get("ldes")
            if ldes and len(ldes) > 0:
                metadata["long_description"] = str(ldes[0])

            # Release date from ©day atom (may contain full ISO date or just year)
            # Year was already extracted above; here we extract the full date for
            # the dateReleased timestamp if it contains month/day info.
            day_val = audio.tags.get("\xa9day")
            if day_val and len(day_val) > 0:
                try:
                    from datetime import datetime
                    date_text = str(day_val[0])
                    if len(date_text) >= 10:
                        dt = datetime.strptime(date_text[:10], '%Y-%m-%d')
                        metadata['date_released'] = int(dt.timestamp())
                    elif len(date_text) >= 7:
                        dt = datetime.strptime(date_text[:7], '%Y-%m')
                        metadata['date_released'] = int(dt.timestamp())
                    elif len(date_text) >= 4:
                        dt = datetime(int(date_text[:4]), 1, 1)
                        metadata['date_released'] = int(dt.timestamp())
                except (ValueError, TypeError, OSError):
                    pass

            # sosn: Sort Show
            sosn = audio.tags.get("sosn")
            if sosn and len(sosn) > 0:
                metadata["sort_show"] = str(sosn[0])

            # iTunSMPB: gapless info written by iTunes / Core Audio (aac_at).
            # Contains exact integer pregap, postgap, and net PCM sample count.
            # Only present in files encoded by Apple's toolchain.
            itun_smpb = audio.tags.get("----:com.apple.iTunes:iTunSMPB")
            if itun_smpb and len(itun_smpb) > 0:
                smpb = _parse_itun_smpb(_coerce_mp4_freeform_text(itun_smpb[0]))
                metadata.update(smpb)

        return metadata

    def _extract_vorbis(self, audio) -> dict:
        """Extract from Vorbis comments (FLAC, OGG, Opus)."""
        metadata = self._extract_easy(audio)

        # Sort tags (Vorbis comment names)
        if hasattr(audio, 'tags') and audio.tags:
            sort_map = {
                "artistsort": "sort_artist",
                "titlesort": "sort_name",
                "albumsort": "sort_album",
                "albumartistsort": "sort_album_artist",
                "composersort": "sort_composer",
            }
            for tag_key, meta_key in sort_map.items():
                val = audio.tags.get(tag_key)
                if val and len(val) > 0:
                    metadata[meta_key] = str(val[0])

            # Compilation flag
            comp = audio.tags.get("compilation")
            if comp and len(comp) > 0:
                metadata["compilation"] = str(comp[0]) == "1"

            # Composer
            composer = audio.tags.get("composer")
            if composer and len(composer) > 0:
                metadata["composer"] = str(composer[0])

            # Comment
            comment = audio.tags.get("comment")
            if comment and len(comment) > 0:
                metadata["comment"] = str(comment[0])

            # BPM
            bpm_val = audio.tags.get("bpm")
            if bpm_val and len(bpm_val) > 0:
                try:
                    metadata["bpm"] = int(float(str(bpm_val[0])))
                except (ValueError, TypeError):
                    pass

            # Grouping
            grouping = audio.tags.get("grouping")
            if grouping and len(grouping) > 0:
                metadata["grouping"] = str(grouping[0])

            # ReplayGain → Sound Check
            rg = audio.tags.get("replaygain_track_gain")
            if rg and len(rg) > 0:
                try:
                    gain_str = str(rg[0]).replace(" dB", "").strip()
                    metadata["sound_check"] = _replaygain_to_soundcheck(float(gain_str))
                except (ValueError, TypeError):
                    pass

            # Lyrics presence
            lyrics = audio.tags.get("lyrics")
            if lyrics and len(lyrics) > 0 and str(lyrics[0]).strip():
                metadata["has_lyrics"] = True
                metadata["lyrics"] = str(lyrics[0]).strip()

            # Subtitle (vorbis comment)
            subtitle_val = audio.tags.get("subtitle")
            if subtitle_val and len(subtitle_val) > 0:
                metadata["subtitle"] = str(subtitle_val[0])

            # Description
            desc_val = audio.tags.get("description")
            if desc_val and len(desc_val) > 0:
                metadata["description"] = str(desc_val[0])

            # Explicit / content advisory
            for adv_key in ("itunesadvisory", "contentrating"):
                adv = audio.tags.get(adv_key)
                if adv and len(adv) > 0:
                    try:
                        val = int(str(adv[0]))
                        if val in (1, 2, 4):
                            metadata["explicit_flag"] = 1 if val in (1, 4) else 2
                    except (ValueError, TypeError):
                        pass
                    break

            # TV Show / Podcast metadata (de facto Vorbis conventions)
            for tag_key, meta_key in [
                ("show", "show_name"), ("tvshow", "show_name"),
                ("episode_id", "episode_id"),
                ("network", "network_name"), ("tvnetwork", "network_name"),
                ("showsort", "sort_show"),
                ("category", "category"),
                ("podcasturl", "podcast_url"),
            ]:
                if meta_key not in metadata:
                    val = audio.tags.get(tag_key)
                    if val and len(val) > 0:
                        metadata[meta_key] = str(val[0])

            # Season / episode numbers
            for tag_key in ("season", "tvseasonnumber"):
                sn = audio.tags.get(tag_key)
                if sn and len(sn) > 0 and "season_number" not in metadata:
                    try:
                        metadata["season_number"] = int(str(sn[0]))
                    except (ValueError, TypeError):
                        pass
            for tag_key in ("episode", "tvepisodenumber"):
                ep = audio.tags.get(tag_key)
                if ep and len(ep) > 0 and "episode_number" not in metadata:
                    try:
                        metadata["episode_number"] = int(str(ep[0]))
                    except (ValueError, TypeError):
                        pass

            # Release date (DATE or ORIGINALDATE vorbis comment)
            for date_key in ("date", "originaldate"):
                date_val = audio.tags.get(date_key)
                if date_val and len(date_val) > 0:
                    try:
                        from datetime import datetime
                        date_text = str(date_val[0])
                        if len(date_text) >= 10:
                            dt = datetime.strptime(date_text[:10], '%Y-%m-%d')
                        elif len(date_text) >= 7:
                            dt = datetime.strptime(date_text[:7], '%Y-%m')
                        elif len(date_text) >= 4:
                            dt = datetime(int(date_text[:4]), 1, 1)
                        else:
                            continue
                        metadata['date_released'] = int(dt.timestamp())
                        break
                    except (ValueError, TypeError, OSError):
                        continue

        return metadata

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
