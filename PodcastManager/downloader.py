"""Episode downloader with progress and cancellation support.

Downloads podcast episodes as streaming HTTP transfers, reporting
progress via callback.  Supports cancellation through a token pattern
compatible with the app's DeviceManager cancellation tokens.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urlparse

import requests

from .models import STATUS_DOWNLOADED, STATUS_DOWNLOADING, PodcastEpisode

log = logging.getLogger(__name__)

_TIMEOUT = 30  # seconds (connect timeout; read is streaming)
_CHUNK_SIZE = 64 * 1024  # 64 KB


class CancelToken(Protocol):
    """Protocol for cancellation tokens."""

    def is_cancelled(self) -> bool:
        ...


def download_episode(
    episode: PodcastEpisode,
    dest_dir: str,
    progress_cb: Callable[[int, int], None] | None = None,
    cancel_token: CancelToken | None = None,
) -> str:
    """Download a single podcast episode.

    Args:
        episode: The episode to download.
        dest_dir: Directory to save the file into.
        progress_cb: Called with (bytes_downloaded, total_bytes).
                     total_bytes is 0 if the server doesn't send
                     Content-Length.
        cancel_token: Optional cancellation token.  Download aborts
                      if ``is_cancelled()`` returns True.

    Returns:
        Absolute path to the downloaded file.

    Raises:
        requests.RequestException: On network errors.
        RuntimeError: If cancelled during download.
    """
    if not episode.audio_url:
        raise ValueError(f"Episode '{episode.title}' has no audio URL")

    os.makedirs(dest_dir, exist_ok=True)

    filename = _safe_filename(episode)
    dest_path = os.path.join(dest_dir, filename)

    # If already fully downloaded, return existing path
    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
        episode.downloaded_path = dest_path
        episode.status = STATUS_DOWNLOADED
        return dest_path

    episode.status = STATUS_DOWNLOADING

    resp = requests.get(
        episode.audio_url,
        stream=True,
        timeout=_TIMEOUT,
        headers={"User-Agent": "iOpenPod (Podcast Manager)"},
    )
    resp.raise_for_status()

    # Correct the file extension from the server's Content-Type if the
    # URL-based guess was wrong (common with CDN redirect URLs).
    ct_ext = _ext_from_content_type(resp.headers.get("Content-Type", ""))
    if ct_ext and not dest_path.endswith(ct_ext):
        dest_path = os.path.splitext(dest_path)[0] + ct_ext

    total = int(resp.headers.get("Content-Length", 0))
    downloaded = 0

    # Write to temp file, then rename (atomic-ish on same filesystem)
    fd, tmp_path = tempfile.mkstemp(dir=dest_dir, suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            for chunk in resp.iter_content(chunk_size=_CHUNK_SIZE):
                if cancel_token and cancel_token.is_cancelled():
                    raise RuntimeError("Download cancelled")
                f.write(chunk)
                downloaded += len(chunk)
                if progress_cb:
                    progress_cb(downloaded, total)

        os.replace(tmp_path, dest_path)
    except Exception:
        # Clean up partial download
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise

    episode.downloaded_path = dest_path
    episode.status = STATUS_DOWNLOADED
    if total > 0:
        episode.size_bytes = total

    return dest_path


def embed_feed_artwork(file_path: str, artwork_url: str) -> bool:
    """Download feed artwork and embed it into the audio file.

    Skips silently if the file already has embedded artwork, if the
    download fails, or if the format is unsupported.

    Returns True if artwork was embedded.
    """
    if not artwork_url or not os.path.exists(file_path):
        return False

    ext = Path(file_path).suffix.lower()
    if ext not in (".mp3", ".m4a", ".m4b", ".aac"):
        return False

    try:
        from mutagen import File as MutagenFile  # type: ignore[attr-defined]
        audio = MutagenFile(file_path)
        if audio is None:
            return False

        # Skip if already has artwork
        if ext == ".mp3":
            if any(k.startswith("APIC") for k in (audio.tags or {})):
                return False
        elif hasattr(audio, "tags") and audio.tags and "covr" in audio.tags:
            return False

        if os.path.exists(artwork_url):
            with open(artwork_url, "rb") as f:
                art_data = f.read()
        else:
            parsed = urlparse(artwork_url)
            if parsed.scheme.lower() not in {"http", "https"}:
                return False
            # Download the artwork image
            resp = requests.get(
                artwork_url, timeout=15,
                headers={"User-Agent": "iOpenPod (Podcast Manager)"},
            )
            resp.raise_for_status()
            art_data = resp.content

        from PodcastManager.artwork import prepare_artwork_bytes

        prepared = prepare_artwork_bytes(art_data)
        if not prepared:
            return False
        art_data = prepared
        mime = "image/jpeg"

        if ext == ".mp3":
            from mutagen.id3 import APIC, PictureType  # type: ignore[attr-defined]
            if audio.tags is None:
                audio.add_tags()
            audio.tags.add(APIC(
                encoding=0,
                mime=mime,
                type=PictureType.COVER_FRONT,
                desc="Cover",
                data=art_data,
            ))
            audio.save()
        else:
            # M4A / AAC / M4B
            from mutagen.mp4 import MP4Cover
            if audio.tags is None:
                audio.add_tags()
            fmt = MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
            audio.tags["covr"] = [MP4Cover(art_data, imageformat=fmt)]
            audio.save()

        log.info("Embedded feed artwork into %s", Path(file_path).name)
        return True

    except Exception as exc:
        log.debug("Failed to embed artwork into %s: %s", file_path, exc)
        return False


@dataclass
class DownloadedEpisodeInfo:
    """Metadata returned by download_and_probe_episode."""
    path: str
    size: int
    mtime: float
    extension: str
    bitrate: int | None = None
    sample_rate: int | None = None
    duration_ms: int | None = None
    art_hash: str | None = None


def download_and_probe_episode(
    audio_url: str,
    title: str,
    dest_dir: str,
    *,
    feed_url: str = "",
    artwork_url: str = "",
    progress_cb: Callable[[int, int], None] | None = None,
    cancel_token: CancelToken | None = None,
) -> DownloadedEpisodeInfo:
    """Download an episode, embed artwork, and probe its audio metadata.

    This is the high-level entry point used by the sync executor.  It
    combines download_episode + embed_feed_artwork + mutagen probing
    into a single call.

    Args:
        audio_url: Enclosure URL for the episode audio.
        title: Episode title (used for filename).
        dest_dir: Directory to save the file into.
        feed_url: Feed URL (unused here, reserved for future use).
        artwork_url: Feed artwork URL to embed into the file.
        progress_cb: Called with (bytes_downloaded, total_bytes) while
                     downloading. total_bytes is 0 when unknown.
        cancel_token: Optional cancellation token checked during download.

    Returns:
        DownloadedEpisodeInfo with file info and probed metadata.

    Raises:
        Same exceptions as download_episode.
    """
    ep = PodcastEpisode(guid=audio_url, title=title, audio_url=audio_url)
    path = download_episode(
        ep,
        dest_dir,
        progress_cb=progress_cb,
        cancel_token=cancel_token,
    )
    return probe_episode_file(path, artwork_url=artwork_url)


def probe_episode_file(
    file_path: str,
    *,
    artwork_url: str = "",
) -> DownloadedEpisodeInfo:
    """Embed missing feed artwork if available, then probe file metadata."""
    if artwork_url:
        embed_feed_artwork(file_path, artwork_url)

    real_path = Path(file_path)
    st = real_path.stat()
    info = DownloadedEpisodeInfo(
        path=file_path,
        size=st.st_size,
        mtime=st.st_mtime,
        extension=real_path.suffix.lower(),
    )

    # Probe audio metadata
    try:
        from mutagen import File as MutagenFile  # type: ignore[import-untyped]
        audio = MutagenFile(file_path)
        if audio and audio.info:
            if hasattr(audio.info, 'bitrate') and audio.info.bitrate:
                info.bitrate = int(audio.info.bitrate / 1000)
            if hasattr(audio.info, 'sample_rate') and audio.info.sample_rate:
                info.sample_rate = audio.info.sample_rate
            if hasattr(audio.info, 'length') and audio.info.length:
                info.duration_ms = int(audio.info.length * 1000)
    except Exception:
        pass

    try:
        from ArtworkDB_Writer.art_extractor import art_hash, extract_art_with_folder

        art_bytes = extract_art_with_folder(file_path)
        if art_bytes:
            info.art_hash = art_hash(art_bytes)
    except Exception:
        pass

    return info


def extract_chapters(file_path: str) -> list[dict] | None:
    """Extract embedded chapter markers from a media file.

    The iPod database chapter timeline is separate from file metadata and can
    be written for any track.  This helper only imports chapters when a source
    file/container exposes them.  Supports:
      - MP4/M4A/M4B: Nero chapters (``chpl`` atom) and QuickTime chapter tracks
      - MP3: ID3v2 CHAP frames
      - Any ffprobe-readable container with chapter entries

    Returns a list of ``{"startpos": ms, "title": str}`` dicts sorted by
    start position, or None if no chapters found.
    """
    if not file_path or not os.path.exists(file_path):
        return None

    ext = Path(file_path).suffix.lower()
    try:
        if ext in (".m4a", ".m4b", ".mp4", ".aac"):
            return _chapters_from_mp4(file_path)
        if ext == ".mp3":
            return _chapters_from_mp3(file_path) or _read_ffprobe_chapters(file_path)
        return _read_ffprobe_chapters(file_path)
    except Exception as exc:
        log.debug("Chapter extraction failed for %s: %s", file_path, exc)
    return None


def _chapters_from_mp4(file_path: str) -> list[dict] | None:
    """Extract chapters from MP4 containers (Nero chpl or QT chapter track)."""
    # --- Nero chapters (stored as raw 'chpl' atom) ---
    # The chpl atom lives under moov.udta.chpl but mutagen doesn't expose
    # it directly.  Fall back to reading the raw file.
    chapters = _read_nero_chapters(file_path)
    if chapters:
        return chapters

    # --- QuickTime chapter track (text track referenced by chap tref) ---
    # mutagen doesn't expose chapter tracks, but ffprobe can.
    chapters = _read_ffprobe_chapters(file_path)
    if chapters:
        return chapters

    return None


def _read_nero_chapters(file_path: str) -> list[dict] | None:
    """Read Nero-style chpl chapters from raw MP4 bytes."""
    import struct
    with open(file_path, "rb") as f:
        data = f.read()

    # Find 'chpl' atom
    idx = data.find(b"chpl")
    if idx < 4:
        return None

    # chpl atom: 4-byte size before 'chpl', then version(4), unk(1),
    # chapter_count(4 for v1, 1 for v0), then entries.
    pos = idx + 4  # skip 'chpl' fourcc

    if pos + 5 > len(data):
        return None
    version = data[pos]
    pos += 5  # version(4) + unknown(1)

    if version == 1:
        if pos + 4 > len(data):
            return None
        count = struct.unpack(">I", data[pos:pos + 4])[0]
        pos += 4
    else:
        count = data[pos]
        pos += 1

    if count == 0 or count > 500:
        return None

    chapters = []
    for _ in range(count):
        if pos + 9 > len(data):
            break
        # timestamp: 8 bytes (100-nanosecond units)
        ts = struct.unpack(">Q", data[pos:pos + 8])[0]
        ms = ts // 10_000
        name_len = data[pos + 8]
        pos += 9
        if pos + name_len > len(data):
            break
        title = data[pos:pos + name_len].decode("utf-8", errors="replace")
        pos += name_len
        chapters.append({"startpos": int(ms), "title": title})

    return chapters if chapters else None


def _read_ffprobe_chapters(file_path: str) -> list[dict] | None:
    """Use ffprobe to extract container chapter entries."""
    import json as _json
    import subprocess
    import sys as _sys

    # Resolve ffprobe via the same search cascade as the transcoder
    ffprobe_bin: str | None = None
    try:
        from SyncEngine.transcoder import find_ffmpeg
        ffmpeg = find_ffmpeg()
        if ffmpeg:
            from pathlib import Path as _Path
            candidate = _Path(ffmpeg).parent / (
                "ffprobe.exe" if _sys.platform == "win32" else "ffprobe"
            )
            if candidate.exists():
                ffprobe_bin = str(candidate)
    except Exception:
        pass
    if not ffprobe_bin:
        import shutil as _shutil
        ffprobe_bin = _shutil.which("ffprobe")
    if not ffprobe_bin:
        return None

    _sp_kwargs: dict = (
        {"creationflags": subprocess.CREATE_NO_WINDOW} if _sys.platform == "win32" else {}
    )

    try:
        proc = subprocess.run(
            [ffprobe_bin, "-v", "quiet", "-print_format", "json",
             "-show_chapters", file_path],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10,
            **_sp_kwargs,
        )
        if proc.returncode != 0:
            return None
        info = _json.loads(proc.stdout)
        raw_chapters = info.get("chapters", [])
        if not raw_chapters:
            return None
        chapters = []
        for ch in raw_chapters:
            start_s = float(ch.get("start_time", 0))
            title = (ch.get("tags", {}).get("title")
                     or ch.get("tags", {}).get("Title")
                     or f"Chapter {len(chapters) + 1}")
            chapters.append({"startpos": int(start_s * 1000), "title": title})
        return chapters if chapters else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _chapters_from_mp3(file_path: str) -> list[dict] | None:
    """Extract ID3v2 CHAP frames from MP3 files."""
    from mutagen.id3 import ID3
    try:
        tags = ID3(file_path)
    except Exception:
        return None

    chapters = []
    for key, frame in tags.items():
        if not key.startswith("CHAP"):
            continue
        start_ms = getattr(frame, "start_time", None)
        if start_ms is None:
            continue
        # CHAP frame may have a TIT2 sub-frame for the chapter title
        title = ""
        for sub in getattr(frame, "sub_frames", []):
            if hasattr(sub, "text") and sub.text:
                title = str(sub.text[0])
                break
        if not title:
            title = f"Chapter {len(chapters) + 1}"
        chapters.append({"startpos": int(start_ms), "title": title})

    chapters.sort(key=lambda c: c["startpos"])
    return chapters if chapters else None


_KNOWN_AUDIO_EXTS = {".mp3", ".m4a", ".m4b", ".aac", ".ogg", ".opus", ".wav", ".flac"}

_CONTENT_TYPE_MAP = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/x-m4b": ".m4b",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/flac": ".flac",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
}


def _ext_from_content_type(content_type: str) -> str:
    """Return a file extension for a Content-Type, or '' if unknown."""
    mime = content_type.split(";")[0].strip().lower()
    return _CONTENT_TYPE_MAP.get(mime, "")


def _safe_filename(episode: PodcastEpisode) -> str:
    """Generate a filesystem-safe filename for the episode."""
    # Try to get extension from the audio URL
    parsed = urlparse(episode.audio_url)
    path = unquote(parsed.path)
    ext = Path(path).suffix.lower()
    if ext not in _KNOWN_AUDIO_EXTS:
        ext = ".mp3"  # Fallback — corrected later from Content-Type

    # Build a clean filename from the guid
    safe = re.sub(r'[^\w\-.]', '_', episode.guid)
    # Limit length
    if len(safe) > 120:
        import hashlib
        safe = hashlib.sha256(episode.guid.encode()).hexdigest()[:24]

    return safe + ext
