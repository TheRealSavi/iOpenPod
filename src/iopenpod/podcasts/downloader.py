"""Episode downloader with progress and cancellation support.

Downloads podcast episodes as streaming HTTP transfers, reporting
progress via callback.  Supports cancellation through a token pattern
compatible with the app's DeviceManager cancellation tokens.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urlparse

import requests

from iopenpod.device.durability import (
    durable_replace,
    durable_unlink,
    flush_parent_directory,
    flush_written_file,
)
from iopenpod.device.storage_safety import allocated_size, require_file_size_supported
from iopenpod.device.write_guard import DeviceWriteSafetyError

from .models import STATUS_DOWNLOADED, STATUS_DOWNLOADING, PodcastEpisode

log = logging.getLogger(__name__)

_TIMEOUT = 30  # seconds (connect timeout; read is streaming)
_CHUNK_SIZE = 64 * 1024  # 64 KB
_MAX_CHAPTER_COUNT = 500
_MAX_CHAPTER_START_MS = 0xFFFFFFFE

_MP4_CONTAINER_ATOMS = {b"moov", b"udta"}


class CancelToken(Protocol):
    """Protocol for cancellation tokens."""

    def is_cancelled(self) -> bool:
        ...


@dataclass(frozen=True, slots=True)
class DeviceDownloadSafety:
    """Scan-time limits and revalidation for a podcast file on the iPod.

    Normal podcast downloads use the host transcode cache and do not need this
    policy.  The sync executor supplies it only for a legacy cache path that
    resolves inside the selected iPod's contained podcast subtree.
    """

    before_device_io: Callable[[], None]
    free_space_path: str | Path
    max_file_size_bytes: int | None = None
    max_component_length: int | None = None
    allocation_unit_size: int | None = None

    def revalidate(self) -> None:
        """Revalidate the retained volume immediately before device I/O."""
        self.before_device_io()

    def require_component_supported(self, name: str) -> None:
        """Reject a filename that the inspected filesystem cannot represent."""
        limit = int(self.max_component_length or 0)
        if limit > 0 and len(name) > limit:
            raise DeviceWriteSafetyError(
                f"The podcast filename {name!r} exceeds this iPod "
                f"filesystem's {limit}-character component limit."
            )

    def require_size_supported(self, logical_size: int, display_name: str) -> None:
        """Reject a file size beyond the retained device/filesystem limit."""
        require_file_size_supported(
            logical_size,
            max_file_size_bytes=self.max_file_size_bytes,
            display_name=display_name,
        )

    def available_bytes(self, display_name: str) -> int:
        """Return current free space, failing closed if it cannot be read."""
        self.revalidate()
        try:
            return int(shutil.disk_usage(self.free_space_path).free)
        except OSError as exc:
            raise DeviceWriteSafetyError(
                "Could not verify iPod free space before writing podcast "
                f"file {display_name}: {exc}"
            ) from exc

    def require_space_within(self, logical_size: int, available: int, display_name: str) -> None:
        """Reject a streamed size that exceeds a previously verified budget."""
        required = allocated_size(logical_size, self.allocation_unit_size)
        if required > max(0, int(available)):
            raise DeviceWriteSafetyError(
                "The iPod does not have enough free space to safely write "
                f"podcast file {display_name}. iOpenPod stopped the download."
            )


def download_episode(
    episode: PodcastEpisode,
    dest_dir: str,
    progress_cb: Callable[[int, int], None] | None = None,
    cancel_token: CancelToken | None = None,
    *,
    device_safety: DeviceDownloadSafety | None = None,
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
        device_safety: Optional retained-volume policy.  This is only used
                       when a legacy episode cache path is on the iPod.

    Returns:
        Absolute path to the downloaded file.

    Raises:
        requests.RequestException: On network errors.
        RuntimeError: If cancelled during download.
    """
    if not episode.audio_url:
        raise ValueError(f"Episode '{episode.title}' has no audio URL")

    if device_safety is not None:
        device_safety.revalidate()
    os.makedirs(dest_dir, exist_ok=True)
    if device_safety is not None:
        flush_parent_directory(dest_dir)

    filename = _safe_filename(episode)
    dest_path = os.path.join(dest_dir, filename)
    if device_safety is not None:
        device_safety.require_component_supported(filename)

    # If already fully downloaded, return existing path
    if device_safety is not None:
        device_safety.revalidate()
        try:
            existing_size = Path(dest_path).stat().st_size
        except FileNotFoundError:
            existing_size = 0
        except OSError:
            raise
        if existing_size > 0:
            device_safety.require_size_supported(existing_size, filename)
    else:
        existing_size = os.path.getsize(dest_path) if os.path.exists(dest_path) else 0
    if existing_size > 0:
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
    free_space_budget: int | None = None
    if device_safety is not None:
        device_safety.require_component_supported(Path(dest_path).name)
        device_safety.require_component_supported(".iop-12345678.part")
        device_safety.require_size_supported(total, Path(dest_path).name)
        free_space_budget = device_safety.available_bytes(Path(dest_path).name)
        if total > 0:
            device_safety.require_space_within(
                total,
                free_space_budget,
                Path(dest_path).name,
            )

    # Write to temp file, then rename (atomic-ish on same filesystem)
    if device_safety is not None:
        device_safety.revalidate()
    fd, tmp_path = tempfile.mkstemp(dir=dest_dir, prefix=".iop-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            for chunk in resp.iter_content(chunk_size=_CHUNK_SIZE):
                if cancel_token and cancel_token.is_cancelled():
                    raise RuntimeError("Download cancelled")
                next_size = downloaded + len(chunk)
                if device_safety is not None:
                    device_safety.require_size_supported(
                        next_size,
                        Path(dest_path).name,
                    )
                    assert free_space_budget is not None
                    device_safety.require_space_within(
                        next_size,
                        free_space_budget,
                        Path(dest_path).name,
                    )
                f.write(chunk)
                downloaded = next_size
                if progress_cb:
                    progress_cb(downloaded, total)
            if device_safety is not None:
                flush_written_file(f)

        if device_safety is not None:
            device_safety.revalidate()
            durable_replace(tmp_path, dest_path)
        else:
            os.replace(tmp_path, dest_path)
    except Exception:
        # Clean up partial download
        if device_safety is not None:
            device_safety.revalidate()
            durable_unlink(tmp_path, missing_ok=True)
        else:
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


def embed_feed_artwork(
    file_path: str,
    artwork_url: str,
    *,
    device_safety: DeviceDownloadSafety | None = None,
) -> bool:
    """Download feed artwork and embed it into the audio file.

    Skips silently if the file already has embedded artwork, if the
    download fails, or if the format is unsupported.

    Returns True if artwork was embedded.
    """
    if not artwork_url:
        return False

    target_size = 0
    if device_safety is not None:
        device_safety.revalidate()
        try:
            target_size = Path(file_path).stat().st_size
        except FileNotFoundError:
            return False
        except OSError:
            raise
        device_safety.require_component_supported(Path(file_path).name)
        device_safety.require_size_supported(target_size, Path(file_path).name)
    elif not os.path.exists(file_path):
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

    except DeviceWriteSafetyError:
        raise
    except OSError:
        if device_safety is not None:
            raise
        return False
    except Exception as exc:
        log.debug("Failed to inspect artwork in %s: %s", file_path, exc)
        return False

    try:
        if device_safety is not None:
            device_safety.revalidate()
        local_artwork = Path(artwork_url)
        try:
            local_artwork_size = local_artwork.stat().st_size
        except FileNotFoundError:
            local_artwork_size = 0
        if local_artwork_size > 0:
            with open(local_artwork, "rb") as f:
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
    except OSError:
        if device_safety is not None:
            raise
        return False
    except Exception as exc:
        log.debug("Failed to load artwork for %s: %s", file_path, exc)
        return False

    try:
        from iopenpod.podcasts.artwork import prepare_artwork_bytes

        prepared = prepare_artwork_bytes(art_data)
        if not prepared:
            return False
        art_data = prepared
        mime = "image/jpeg"

        if device_safety is not None:
            projected_size = target_size + len(art_data)
            device_safety.require_size_supported(
                projected_size,
                Path(file_path).name,
            )
            available = device_safety.available_bytes(Path(file_path).name)
            growth = max(
                0,
                allocated_size(projected_size, device_safety.allocation_unit_size)
                - allocated_size(target_size, device_safety.allocation_unit_size),
            )
            if growth > available:
                raise DeviceWriteSafetyError(
                    "The iPod does not have enough free space to safely embed "
                    f"artwork in podcast file {Path(file_path).name}."
                )

        if ext == ".mp3":
            from mutagen.id3 import APIC, PictureType  # type: ignore[attr-defined]
            if audio.tags is None:
                audio.add_tags()
            mp3_tags = audio.tags
            if mp3_tags is None:
                return False
            mp3_tags.add(APIC(
                encoding=0,
                mime=mime,
                type=PictureType.COVER_FRONT,
                desc="Cover",
                data=art_data,
            ))
            if device_safety is not None:
                device_safety.revalidate()
            audio.save()
        else:
            # M4A / AAC / M4B
            from mutagen.mp4 import MP4Cover
            if audio.tags is None:
                audio.add_tags()
            mp4_tags = audio.tags
            if mp4_tags is None:
                return False
            fmt = MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
            mp4_tags["covr"] = [MP4Cover(art_data, imageformat=fmt)]
            if device_safety is not None:
                device_safety.revalidate()
            audio.save()

        if device_safety is not None:
            device_safety.revalidate()
            with open(file_path, "rb+") as written_file:
                flush_written_file(written_file)
            flush_parent_directory(file_path)

        log.info("Embedded feed artwork into %s", Path(file_path).name)
        return True

    except DeviceWriteSafetyError:
        raise
    except OSError:
        if device_safety is not None:
            raise
        return False
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
    device_safety: DeviceDownloadSafety | None = None,
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
        device_safety: Optional retained-volume policy for an iPod-resident
                       legacy cache path.

    Returns:
        DownloadedEpisodeInfo with file info and probed metadata.

    Raises:
        Same exceptions as download_episode.
    """
    ep = PodcastEpisode(guid=audio_url, title=title, audio_url=audio_url)
    if device_safety is None:
        path = download_episode(
            ep,
            dest_dir,
            progress_cb=progress_cb,
            cancel_token=cancel_token,
        )
        return probe_episode_file(path, artwork_url=artwork_url)

    path = download_episode(
        ep,
        dest_dir,
        progress_cb=progress_cb,
        cancel_token=cancel_token,
        device_safety=device_safety,
    )
    return probe_episode_file(
        path,
        artwork_url=artwork_url,
        device_safety=device_safety,
    )


def probe_episode_file(
    file_path: str,
    *,
    artwork_url: str = "",
    device_safety: DeviceDownloadSafety | None = None,
) -> DownloadedEpisodeInfo:
    """Embed missing feed artwork if available, then probe file metadata."""
    if artwork_url:
        embed_feed_artwork(
            file_path,
            artwork_url,
            device_safety=device_safety,
        )

    real_path = Path(file_path)
    if device_safety is not None:
        device_safety.revalidate()
    st = real_path.stat()
    if device_safety is not None:
        device_safety.require_component_supported(real_path.name)
        device_safety.require_size_supported(st.st_size, real_path.name)
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
    except OSError:
        if device_safety is not None:
            raise
    except Exception:
        pass

    try:
        from iopenpod.artworkdb_writer.art_extractor import art_hash, extract_art_with_folder

        art_bytes = extract_art_with_folder(file_path)
        if art_bytes:
            info.art_hash = art_hash(art_bytes)
    except OSError:
        if device_safety is not None:
            raise
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

    body = _find_mp4_atom_body(data, (b"moov", b"udta", b"chpl"))
    if body is None:
        return None

    # chpl atom body: version/flags(4), unk(1),
    # chapter_count(4 for v1, 1 for v0), then entries.
    pos = 0

    if pos + 5 > len(body):
        return None
    version = body[pos]
    pos += 5  # version(4) + unknown(1)

    if version == 1:
        if pos + 4 > len(body):
            return None
        count = struct.unpack(">I", body[pos:pos + 4])[0]
        pos += 4
    else:
        if pos >= len(body):
            return None
        count = body[pos]
        pos += 1

    if count == 0 or count > _MAX_CHAPTER_COUNT:
        return None

    chapters = []
    for _ in range(count):
        if pos + 9 > len(body):
            return None
        # timestamp: 8 bytes (100-nanosecond units)
        ts = struct.unpack(">Q", body[pos:pos + 8])[0]
        ms = ts // 10_000
        name_len = body[pos + 8]
        pos += 9
        if pos + name_len > len(body):
            return None
        title = body[pos:pos + name_len].decode("utf-8", errors="replace")
        pos += name_len
        chapters.append({"startpos": int(ms), "title": title})

    return _plausible_chapters(chapters)


def _find_mp4_atom_body(data: bytes, path: tuple[bytes, ...]) -> bytes | None:
    """Return the body for an MP4 atom at *path*.

    This deliberately walks the MP4 atom tree instead of searching for a raw
    fourcc byte sequence. Audio payloads can contain arbitrary ``chpl`` bytes
    that are not metadata atoms.
    """
    if not path:
        return data

    needle = path[0]
    for atom_type, body_start, body_end in _iter_mp4_atoms(data, 0, len(data)):
        if atom_type != needle:
            continue
        body = data[body_start:body_end]
        if len(path) == 1:
            return body
        if atom_type not in _MP4_CONTAINER_ATOMS:
            return None
        found = _find_mp4_atom_body(body, path[1:])
        if found is not None:
            return found
    return None


def _iter_mp4_atoms(data: bytes, start: int, end: int):
    import struct

    pos = start
    while pos + 8 <= end:
        size = struct.unpack(">I", data[pos:pos + 4])[0]
        atom_type = data[pos + 4:pos + 8]
        header_size = 8

        if size == 1:
            if pos + 16 > end:
                return
            size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
            header_size = 16
        elif size == 0:
            size = end - pos

        if size < header_size or pos + size > end:
            return

        yield atom_type, pos + header_size, pos + size
        pos += size


def _plausible_chapters(chapters: list[dict]) -> list[dict] | None:
    if not chapters or len(chapters) > _MAX_CHAPTER_COUNT:
        return None

    previous = -1
    normalized: list[dict] = []
    for index, chapter in enumerate(chapters, start=1):
        try:
            start_ms = int(chapter.get("startpos", 0))
        except (TypeError, ValueError, OverflowError):
            return None
        if start_ms < 0 or start_ms > _MAX_CHAPTER_START_MS:
            return None
        if start_ms <= previous:
            return None

        title = str(chapter.get("title") or f"Chapter {index}").strip()
        if _suspicious_chapter_title(title):
            return None
        normalized.append({"startpos": start_ms, "title": title or f"Chapter {index}"})
        previous = start_ms

    return normalized


def _suspicious_chapter_title(title: str) -> bool:
    if "\x00" in title:
        return True
    if title.count("\ufffd") > max(1, len(title) // 10):
        return True
    control_count = sum(
        1 for ch in title
        if ord(ch) < 32 and ch not in "\t\r\n"
    )
    return control_count > 0


def _read_ffprobe_chapters(file_path: str) -> list[dict] | None:
    """Use ffprobe to extract container chapter entries."""
    import json as _json
    import subprocess
    import sys as _sys

    # Resolve ffprobe via the same search cascade as the transcoder.
    try:
        from iopenpod.sync.transcoder import find_ffprobe
        ffprobe_bin = find_ffprobe()
    except Exception:
        ffprobe_bin = None
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
        return _plausible_chapters(chapters)
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
    return _plausible_chapters(chapters)


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
