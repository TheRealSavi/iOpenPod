"""Photo sync support for the iPod photo database and ithmb thumbnails."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import os
import re
import struct
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from PIL import Image, ImageOps, UnidentifiedImageError

from iopenpod.artworkdb_writer.ithmb_codecs import (
    decode_pixels_for_format,
    encode_image_for_format,
    expected_size_bytes,
)
from iopenpod.device import ITHMB_FORMAT_MAP, photo_formats_for_device
from iopenpod.device.capabilities import ArtworkFormat
from iopenpod.device.durability import (
    durable_replace,
    durable_unlink,
    flush_parent_directory,
    flush_written_file,
    open_unique_sibling_temp,
)
from iopenpod.device.filesystem_profile import FilesystemProfile
from iopenpod.device.path_safety import UnsafeDevicePathError, resolve_device_path
from iopenpod.device.storage_safety import require_file_size_supported
from iopenpod.infrastructure.media_folders import (
    MEDIA_TYPE_PHOTO,
    MediaFolderEntry,
    normalize_media_folder_entries,
)

from ._formats import PHOTO_EXTENSIONS

logger = logging.getLogger(__name__)

_PHOTO_DB_RELATIVE = Path("Photos") / "Photo Database"
_PHOTO_THUMBS_RELATIVE = Path("Photos") / "Thumbs"
_PHOTO_FULL_RES_RELATIVE = Path("Photos") / "Full Resolution"
_PHOTO_MAPPING_RELATIVE = Path("iPod_Control") / "iOpenPod" / "photo_sync.json"

_MHFD_HEADER_SIZE = 132
_MHSD_HEADER_SIZE = 96
_MHLI_HEADER_SIZE = 92
_MHLA_HEADER_SIZE = 92
_MHLF_HEADER_SIZE = 92
_MHII_HEADER_SIZE = 152
_MHOD_HEADER_SIZE = 24
_MHNI_HEADER_SIZE = 76
_MHIF_HEADER_SIZE = 124
_MHBA_HEADER_SIZE = 148
_MHIA_HEADER_SIZE = 40

_MASTER_ALBUM_NAME = "Photo Library"
_ROOT_ALBUM_LABEL = "All Photos"
_MIN_PHOTO_ID = 100
_DEFAULT_MHFD_UNKNOWN2 = 6
_DEFAULT_NON_MASTER_ALBUM_TYPE = 2
_NANO_67_NON_MASTER_ALBUM_TYPE = 6
_PHOTO_MAPPING_SETTINGS_KEY = "__photo_sync_settings__"
_ROTATE_TALL_PHOTO_ASPECT_THRESHOLD = 1.15
_ROTATE_TALL_PHOTO_GAIN_THRESHOLD = 1.2
_ROTATABLE_PHOTO_ROLES = frozenset({"photo_full", "photo_preview", "photo_large", "tv_out"})
_FULL_RES_ROTATION_ROLES = frozenset({"photo_full", "photo_preview", "photo_large"})
_PHOTO_BASENAME_MAX_LENGTH = 180
PhotoMappingEntry = dict[str, object]
_THUMBNAIL_PHOTO_ROLES = frozenset({"photo_thumb", "photo_list"})
_SUPPORTED_IMAGE_EXTENSIONS = PHOTO_EXTENSIONS
_DECOMPRESSION_BOMB_ERROR = getattr(Image, "DecompressionBombError", None)
_PIL_LOAD_ERRORS = tuple(
    err
    for err in (UnidentifiedImageError, OSError, _DECOMPRESSION_BOMB_ERROR)
    if err is not None
)


class PhotoMetadataSafetyError(RuntimeError):
    """Raised when existing iPod photo metadata cannot be trusted for a write."""


def _photo_db_path(ipod_path: str | Path) -> Path:
    return resolve_device_path(ipod_path, _PHOTO_DB_RELATIVE, allowed_subtree="Photos")


def _photo_thumbs_dir(ipod_path: str | Path) -> Path:
    return resolve_device_path(
        ipod_path,
        _PHOTO_THUMBS_RELATIVE,
        allowed_subtree=_PHOTO_THUMBS_RELATIVE,
    )


def _photo_full_res_dir(ipod_path: str | Path) -> Path:
    return resolve_device_path(
        ipod_path,
        _PHOTO_FULL_RES_RELATIVE,
        allowed_subtree=_PHOTO_FULL_RES_RELATIVE,
    )


def _photo_mapping_path(ipod_path: str | Path) -> Path:
    return resolve_device_path(
        ipod_path,
        _PHOTO_MAPPING_RELATIVE,
        allowed_subtree=_PHOTO_MAPPING_RELATIVE.parent,
    )


@dataclass
class PhotoThumbRef:
    format_id: int
    offset: int
    size: int
    width: int
    height: int
    hpad: int = 0
    vpad: int = 0
    filename: str = ""


@dataclass
class PhotoEntry:
    image_id: int
    original_size: int = 0
    full_res_size: int = 0
    display_name: str = ""
    visual_hash: str = ""
    source_path: str = ""
    full_res_path: str = ""
    created_at: int = 0
    digitized_at: int = 0
    album_names: set[str] = field(default_factory=set)
    thumbs: dict[int, PhotoThumbRef] = field(default_factory=dict)


@dataclass
class PhotoAlbum:
    album_id: int
    name: str
    album_type: int = 2
    members: list[int] = field(default_factory=list)
    playmusic: int = 0
    repeat: int = 0
    random: int = 0
    show_titles: int = 0
    transition_direction: int = 0
    slide_duration: int = 0
    transition_duration: int = 0
    song_id: int = 0
    prev_album_id: int = 0


@dataclass
class PhotoDB:
    photos: dict[int, PhotoEntry] = field(default_factory=dict)
    albums: list[PhotoAlbum] = field(default_factory=list)
    file_sizes: dict[int, int] = field(default_factory=dict)
    next_image_id: int = _MIN_PHOTO_ID
    next_album_id: int = _MIN_PHOTO_ID
    mhfd_unknown2: int = _DEFAULT_MHFD_UNKNOWN2
    non_master_album_type: int = _DEFAULT_NON_MASTER_ALBUM_TYPE

    def master_album(self) -> PhotoAlbum:
        for album in self.albums:
            if album.album_type == 1:
                return album
        master = PhotoAlbum(album_id=self.next_album_id, name=_MASTER_ALBUM_NAME, album_type=1)
        self.next_album_id += 1
        self.albums.insert(0, master)
        return master


@dataclass
class PCPhoto:
    visual_hash: str
    display_name: str
    source_path: str
    size: int
    album_names: set[str] = field(default_factory=set)


@dataclass
class PCPhotoLibrary:
    sync_root: str
    photos: dict[str, PCPhoto] = field(default_factory=dict)
    albums: set[str] = field(default_factory=set)
    skipped: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class PhotoAlbumChange:
    album_name: str
    item_count: int = 0


@dataclass
class PhotoMembershipChange:
    visual_hash: str
    album_name: str
    display_name: str
    source_path: str = ""
    image_id: int = 0
    size: int = 0


@dataclass
class PhotoSyncItem:
    visual_hash: str
    display_name: str
    album_names: set[str] = field(default_factory=set)
    source_path: str = ""
    image_id: int = 0
    size: int = 0
    description: str = ""
    estimated_size: int = 0


@dataclass
class PhotoEditState:
    imported_files: list[tuple[str, str]] = field(default_factory=list)
    created_albums: set[str] = field(default_factory=set)
    renamed_albums: dict[str, str] = field(default_factory=dict)
    deleted_albums: set[str] = field(default_factory=set)
    membership_adds: set[tuple[str, str]] = field(default_factory=set)
    membership_removals: set[tuple[str, str]] = field(default_factory=set)
    deleted_photos: set[str] = field(default_factory=set)

    @property
    def has_changes(self) -> bool:
        return any((
            self.imported_files,
            self.created_albums,
            self.renamed_albums,
            self.deleted_albums,
            self.membership_adds,
            self.membership_removals,
            self.deleted_photos,
        ))


@dataclass
class PhotoSyncPlan:
    albums_to_add: list[PhotoAlbumChange] = field(default_factory=list)
    albums_to_remove: list[PhotoAlbumChange] = field(default_factory=list)
    photos_to_add: list[PhotoSyncItem] = field(default_factory=list)
    photos_to_remove: list[PhotoSyncItem] = field(default_factory=list)
    photos_to_update: list[PhotoSyncItem] = field(default_factory=list)
    album_membership_adds: list[PhotoMembershipChange] = field(default_factory=list)
    album_membership_removes: list[PhotoMembershipChange] = field(default_factory=list)
    thumb_bytes_to_add: int = 0
    thumb_bytes_to_remove: int = 0
    skipped_files: list[tuple[str, str]] = field(default_factory=list)
    current_db: PhotoDB | None = None
    desired_library: PCPhotoLibrary | None = None

    @property
    def has_changes(self) -> bool:
        return any((
            self.albums_to_add,
            self.albums_to_remove,
            self.photos_to_add,
            self.photos_to_remove,
            self.photos_to_update,
            self.album_membership_adds,
            self.album_membership_removes,
        ))


def _load_photo_mapping(ipod_path: str | Path) -> dict[str, PhotoMappingEntry]:
    path = _photo_mapping_path(ipod_path)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        raise PhotoMetadataSafetyError(
            "The existing iPod photo mapping could not be read safely. "
            "iOpenPod stopped before changing photos so the current photo "
            f"library is not overwritten: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise PhotoMetadataSafetyError(
            "The existing iPod photo mapping is malformed. iOpenPod stopped "
            "before changing photos so the current photo library is not overwritten."
        )
    if any(not isinstance(key, str) or not isinstance(value, dict) for key, value in data.items()):
        raise PhotoMetadataSafetyError(
            "The existing iPod photo mapping contains invalid entries. "
            "iOpenPod stopped before changing photos so the current photo "
            "library is not overwritten."
        )
    return data


def photo_sync_settings_from_settings(settings: object) -> dict[str, bool]:
    """Extract the photo sync settings needed by this module."""

    return {
        "rotate_tall_photos_for_device": bool(
            getattr(settings, "rotate_tall_photos_for_device", False)
        ),
        "fit_photo_thumbnails": bool(
            getattr(settings, "fit_photo_thumbnails", False)
        ),
    }


def _current_photo_sync_settings(
    sync_settings: Mapping[str, object] | None = None,
) -> dict[str, bool]:
    if sync_settings is None:
        return {
            "rotate_tall_photos_for_device": False,
            "fit_photo_thumbnails": False,
        }
    return {
        "rotate_tall_photos_for_device": bool(
            sync_settings.get("rotate_tall_photos_for_device", False)
        ),
        "fit_photo_thumbnails": bool(
            sync_settings.get("fit_photo_thumbnails", False)
        ),
    }


def _load_photo_mapping_settings(ipod_path: str | Path) -> dict[str, bool]:
    data = _load_photo_mapping(ipod_path).get(_PHOTO_MAPPING_SETTINGS_KEY)
    if not isinstance(data, dict):
        return {
            "rotate_tall_photos_for_device": False,
            "fit_photo_thumbnails": False,
        }
    return {
        "rotate_tall_photos_for_device": bool(
            data.get("rotate_tall_photos_for_device", False)
        ),
        "fit_photo_thumbnails": bool(
            data.get("fit_photo_thumbnails", False)
        ),
    }


def _save_photo_mapping(
    ipod_path: str | Path,
    photodb: PhotoDB,
    *,
    sync_settings: Mapping[str, object] | None = None,
    before_device_mutation: Callable[[], None] | None = None,
) -> None:
    path = _photo_mapping_path(ipod_path)
    if before_device_mutation is not None:
        before_device_mutation()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, PhotoMappingEntry] = {
        str(photo.image_id): {
            "visual_hash": photo.visual_hash,
            "source_path": photo.source_path,
            "display_name": photo.display_name,
        }
        for photo in photodb.photos.values()
    }
    payload[_PHOTO_MAPPING_SETTINGS_KEY] = {
        "rotate_tall_photos_for_device": bool(
            (sync_settings or {}).get("rotate_tall_photos_for_device", False)
        ),
        "fit_photo_thumbnails": bool(
            (sync_settings or {}).get("fit_photo_thumbnails", False)
        ),
    }
    _replace_bytes_durably(
        path,
        json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"),
        before_device_mutation=before_device_mutation,
    )


def _cleanup_device_temp(
    path: Path | None,
    *,
    before_device_mutation: Callable[[], None] | None,
) -> None:
    if path is None:
        return
    try:
        if before_device_mutation is not None:
            before_device_mutation()
        durable_unlink(path, missing_ok=True)
    except Exception as exc:
        logger.warning("Could not safely remove photo temporary file %s: %s", path, exc)


def _replace_bytes_durably(
    target: Path,
    data: bytes,
    *,
    before_device_mutation: Callable[[], None] | None,
) -> None:
    """Write bytes through an exclusive sibling and atomically install them."""
    temp_path: Path | None = None
    try:
        if before_device_mutation is not None:
            before_device_mutation()
        temp_path, temp_file = open_unique_sibling_temp(target, mode="wb")
        with temp_file as file:
            file.write(data)
            flush_written_file(file)
        if before_device_mutation is not None:
            before_device_mutation()
        durable_replace(temp_path, target)
    except Exception:
        _cleanup_device_temp(
            temp_path,
            before_device_mutation=before_device_mutation,
        )
        raise


def _replace_jpeg_durably(
    target: Path,
    image: Image.Image,
    *,
    before_device_mutation: Callable[[], None] | None,
) -> None:
    """Encode a JPEG into an exclusive sibling and atomically install it."""
    temp_path: Path | None = None
    try:
        if before_device_mutation is not None:
            before_device_mutation()
        temp_path, temp_file = open_unique_sibling_temp(target, mode="wb")
        with temp_file as file:
            image.save(file, format="JPEG", quality=92, optimize=True)
            flush_written_file(file)
        if before_device_mutation is not None:
            before_device_mutation()
        durable_replace(temp_path, target)
    except Exception:
        _cleanup_device_temp(
            temp_path,
            before_device_mutation=before_device_mutation,
        )
        raise


def _image_visual_hash(img: Image.Image) -> str:
    normalized = ImageOps.exif_transpose(img).convert("RGB")
    preview = normalized.copy()
    preview.thumbnail((96, 96), Image.Resampling.LANCZOS)
    return hashlib.md5(preview.tobytes()).hexdigest()


def _load_pil_still_image(path: str | Path) -> Image.Image:
    with Image.open(path) as img:
        img.seek(0)
        loaded = img.copy()
    return ImageOps.exif_transpose(loaded)


def _sanitize_photo_basename(name: str, fallback: str) -> str:
    stem = Path(name).stem if name else fallback
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")
    cleaned = cleaned[:_PHOTO_BASENAME_MAX_LENGTH].rstrip("._")
    return cleaned or fallback[:_PHOTO_BASENAME_MAX_LENGTH]


def _photo_db_string_to_rel_path(value: str) -> str:
    cleaned = value[1:] if value.startswith(":") else value
    return cleaned.replace(":", "/")


def _photo_rel_path_to_db_string(rel_path: str | Path) -> str:
    return ":" + ":".join(Path(rel_path).parts)


def resolve_photo_full_res_path(
    ipod_path: str | Path,
    rel_path: str | Path,
) -> Path:
    """Resolve a Photo DB full-resolution path inside the iPod photo tree."""
    return resolve_device_path(
        ipod_path,
        Path("Photos") / Path(rel_path),
        allowed_subtree=_PHOTO_FULL_RES_RELATIVE,
    )


def _device_photo_path(ipod_path: str | Path, rel_path: str) -> Path:
    return resolve_photo_full_res_path(ipod_path, rel_path)


def _device_photo_thumb_path(ipod_path: str | Path, filename: str) -> Path:
    return resolve_device_path(
        ipod_path,
        _PHOTO_THUMBS_RELATIVE / Path(filename),
        allowed_subtree=_PHOTO_THUMBS_RELATIVE,
    )


def _safe_enumerated_photo_path(
    ipod_path: str | Path,
    path: Path,
    *,
    allowed_subtree: str | Path,
) -> Path:
    root = Path(ipod_path).resolve(strict=False)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise UnsafeDevicePathError(
            f"Enumerated photo path is outside the iPod: {path}",
        ) from exc
    return resolve_device_path(
        root,
        relative,
        allowed_subtree=allowed_subtree,
    )


def _full_res_rel_path_for_entry(entry: PhotoEntry) -> str:
    basename = _sanitize_photo_basename(entry.display_name, f"photo{entry.image_id:05d}")
    return str(Path("Full Resolution") / "iOpenPod" / f"{basename}_{entry.image_id:05d}.jpg")


def _source_timestamp(path: str | Path) -> int:
    try:
        return int(Path(path).stat().st_mtime)
    except OSError:
        return 0


def _describe_image_load_error(path: str | Path, exc: BaseException) -> str:
    if _DECOMPRESSION_BOMB_ERROR is not None and isinstance(exc, _DECOMPRESSION_BOMB_ERROR):
        return f"{exc} Offending image: {path}"
    return str(exc)


def _coerce_photo_entries(
    sync_root: str | Path | Iterable[str | Path | dict[str, object] | MediaFolderEntry],
) -> tuple[tuple[Path, MediaFolderEntry], ...]:
    raw_entries = normalize_media_folder_entries(sync_root)
    entries: list[tuple[Path, MediaFolderEntry]] = []
    seen: set[str] = set()
    for entry in raw_entries:
        if MEDIA_TYPE_PHOTO not in entry.media_types:
            continue
        root = Path(entry.directory).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            continue
        key = os.path.normcase(str(root))
        if key in seen:
            continue
        seen.add(key)
        entries.append((
            root,
            MediaFolderEntry(
                directory=str(root),
                recurse=entry.recurse,
                media_types=entry.media_types,
            ),
        ))
    return tuple(entries)


def _iter_photo_files(root: Path, *, recurse: bool):
    if recurse:
        yield from root.rglob("*")
        return
    yield from root.iterdir()


def _default_photo_workers() -> int:
    return min(os.cpu_count() or 4, 8)


def scan_pc_photos(
    sync_root: str | Path | Iterable[str | Path | dict[str, object] | MediaFolderEntry],
    progress_callback: Callable[[int, int, str], None] | None = None,
    max_workers: int | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> PCPhotoLibrary:
    root_entries = _coerce_photo_entries(sync_root)
    roots = tuple(root for root, _entry in root_entries)
    sync_root_label = os.pathsep.join(str(root) for root in roots)
    library = PCPhotoLibrary(sync_root=sync_root_label)
    if not roots:
        return library

    seen_files: set[str] = set()
    files: list[tuple[Path, Path]] = []
    for root, entry in root_entries:
        for file_path in _iter_photo_files(root, recurse=entry.recurse):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in _SUPPORTED_IMAGE_EXTENSIONS:
                continue
            file_key = os.path.normcase(str(file_path.resolve()))
            if file_key in seen_files:
                continue
            seen_files.add(file_key)
            files.append((file_path, root))

    total = len(files)
    if max_workers is None:
        max_workers = _default_photo_workers()
    max_workers = max(1, min(max_workers, 8))

    def _record_photo(file_path: Path, root: Path, img: Image.Image) -> None:
        rel_parent = file_path.parent.relative_to(root)
        album_name = rel_parent.as_posix() if rel_parent.parts else ""
        if album_name:
            library.albums.add(album_name)

        size = file_path.stat().st_size
        visual_hash = _image_visual_hash(img)
        entry = library.photos.get(visual_hash)
        if entry is None:
            entry = PCPhoto(
                visual_hash=visual_hash,
                display_name=file_path.name,
                source_path=str(file_path),
                size=size,
            )
            library.photos[visual_hash] = entry
        entry.album_names.add(album_name)

    current = 0
    if max_workers == 1 or total <= 1:
        for file_path, root in files:
            if is_cancelled and is_cancelled():
                return library
            try:
                img = _load_pil_still_image(file_path)
            except _PIL_LOAD_ERRORS as exc:
                library.skipped.append((str(file_path), _describe_image_load_error(file_path, exc)))
                img = None
            current += 1
            if progress_callback:
                progress_callback(current, total, file_path.name)
            if img is None:
                continue
            _record_photo(file_path, root, img)
        return library

    def _load_photo(file_path: Path) -> Image.Image:
        return _load_pil_still_image(file_path)

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="photo-scan") as pool:
        futures = {pool.submit(_load_photo, file_path): (file_path, root) for file_path, root in files}
        for future in as_completed(futures):
            if is_cancelled and is_cancelled():
                for pending in futures:
                    pending.cancel()
                return library
            file_path, root = futures[future]
            try:
                img = future.result()
            except _PIL_LOAD_ERRORS as exc:
                library.skipped.append((str(file_path), _describe_image_load_error(file_path, exc)))
                img = None
            current += 1
            if progress_callback:
                progress_callback(current, total, file_path.name)
            if img is None:
                continue
            _record_photo(file_path, root, img)
    return library


def _apply_photo_edits(library: PCPhotoLibrary, staged_edits: PhotoEditState | None) -> PCPhotoLibrary:
    if not staged_edits or not staged_edits.has_changes:
        return library

    library = copy.deepcopy(library)
    for source_path, album_name in staged_edits.imported_files:
        try:
            img = _load_pil_still_image(source_path)
        except _PIL_LOAD_ERRORS as exc:
            library.skipped.append((source_path, _describe_image_load_error(source_path, exc)))
            continue
        visual_hash = _image_visual_hash(img)
        entry = library.photos.get(visual_hash)
        if entry is None:
            size = Path(source_path).stat().st_size if Path(source_path).exists() else 0
            entry = PCPhoto(
                visual_hash=visual_hash,
                display_name=Path(source_path).name,
                source_path=source_path,
                size=size,
            )
            library.photos[visual_hash] = entry
        entry.album_names.add(album_name or "")
        if album_name:
            library.albums.add(album_name)

    for old_name, new_name in staged_edits.renamed_albums.items():
        if old_name in library.albums:
            library.albums.remove(old_name)
            if new_name:
                library.albums.add(new_name)
        for entry in library.photos.values():
            if old_name in entry.album_names:
                entry.album_names.discard(old_name)
                if new_name:
                    entry.album_names.add(new_name)

    for album_name in staged_edits.deleted_albums:
        library.albums.discard(album_name)
        for entry in library.photos.values():
            entry.album_names.discard(album_name)

    for album_name in staged_edits.created_albums:
        if album_name:
            library.albums.add(album_name)

    for visual_hash, album_name in staged_edits.membership_adds:
        entry = library.photos.get(visual_hash)
        if entry is not None:
            entry.album_names.add(album_name)
            if album_name:
                library.albums.add(album_name)

    for visual_hash, album_name in staged_edits.membership_removals:
        entry = library.photos.get(visual_hash)
        if entry is not None:
            entry.album_names.discard(album_name)

    for visual_hash in staged_edits.deleted_photos:
        library.photos.pop(visual_hash, None)

    return library


def _decode_photo_image(entry: PhotoEntry, ipod_path: str | Path) -> Image.Image | None:
    # Prefer iPod-rendered views first so previews reflect on-device output
    # (padding, letterboxing, and alpha flattening), then fall back to full-res.
    role_priority = {
        "photo_full": 0,
        "photo_large": 1,
        "photo_preview": 2,
        "tv_out": 3,
        "photo_thumb": 4,
        "photo_list": 5,
    }
    format_defs = _photo_formats_for_current_device(ipod_path)

    def _format_for_ref(ref: PhotoThumbRef) -> ArtworkFormat | None:
        return (
            format_defs.get(int(ref.format_id))
            or ITHMB_FORMAT_MAP.get(int(ref.format_id))
        )

    def _role_for_ref(ref: PhotoThumbRef) -> str:
        fmt = _format_for_ref(ref)
        return fmt.role if fmt is not None else ""

    candidates = sorted(
        entry.thumbs.values(),
        key=lambda ref: (
            role_priority.get(_role_for_ref(ref), 9),
            -(ref.width * ref.height),
            int(ref.format_id),
        ),
    )
    for ref in candidates:
        filename = ref.filename or f"F{ref.format_id}_1.ithmb"
        thumb_path = _device_photo_thumb_path(ipod_path, filename)
        if not thumb_path.exists():
            continue
        try:
            with open(thumb_path, "rb") as f:
                f.seek(ref.offset)
                payload = f.read(ref.size)
            img = decode_pixels_for_format(
                ref.format_id,
                payload,
                ref.width,
                ref.height,
                ref.hpad,
                ref.vpad,
                fmt_override=_format_for_ref(ref),
            )
            if img is not None:
                return img
        except OSError:
            continue

    if entry.full_res_path:
        full_res_path = _device_photo_path(ipod_path, entry.full_res_path)
        if full_res_path.exists():
            try:
                return _load_pil_still_image(full_res_path)
            except _PIL_LOAD_ERRORS:
                pass
    return None


def _decode_photo_format(
    entry: PhotoEntry,
    ipod_path: str | Path,
    format_id: int,
) -> Image.Image | None:
    ref = entry.thumbs.get(int(format_id))
    if ref is None:
        return None
    filename = ref.filename or f"F{ref.format_id}_1.ithmb"
    thumb_path = _device_photo_thumb_path(ipod_path, filename)
    if not thumb_path.exists():
        return None
    try:
        with open(thumb_path, "rb") as f:
            f.seek(ref.offset)
            payload = f.read(ref.size)
        format_defs = _photo_formats_for_current_device(ipod_path)
        fmt_override = (
            format_defs.get(int(ref.format_id))
            or ITHMB_FORMAT_MAP.get(int(ref.format_id))
        )
        return decode_pixels_for_format(
            ref.format_id,
            payload,
            ref.width,
            ref.height,
            ref.hpad,
            ref.vpad,
            fmt_override=fmt_override,
        )
    except OSError:
        return None


def _ensure_visual_hashes(
    photodb: PhotoDB,
    ipod_path: str | Path,
) -> None:
    for photo in photodb.photos.values():
        if photo.visual_hash:
            continue
        img = load_photo_preview(photo, ipod_path)
        if img is not None:
            photo.visual_hash = _image_visual_hash(img)


def ensure_photo_visual_hashes(
    photodb: PhotoDB,
    ipod_path: str | Path,
) -> None:
    """Populate missing device photo visual hashes in-place.

    Uses only on-device assets (Photo DB/full-res/ithmb).
    """
    _ensure_visual_hashes(photodb, ipod_path)


def build_photo_library_from_device(device_photos: PhotoDB) -> PCPhotoLibrary:
    """Represent the current iPod photo database as a desired-library model."""
    library = PCPhotoLibrary(sync_root="")
    for photo in device_photos.photos.values():
        if not photo.visual_hash:
            continue
        display_name = photo.display_name or Path(photo.full_res_path).name or f"Photo {photo.image_id}"
        entry = PCPhoto(
            visual_hash=photo.visual_hash,
            display_name=display_name,
            source_path=photo.source_path,
            size=photo.original_size or photo.full_res_size,
            album_names=set(photo.album_names),
        )
        library.photos[photo.visual_hash] = entry
        for album_name in entry.album_names:
            if album_name:
                library.albums.add(album_name)
    return library


def _parse_mhod_string(data: bytes, offset: int, header_len: int) -> tuple[str, int]:
    content_offset = offset + header_len
    byte_length = struct.unpack_from("<I", data, content_offset)[0]
    encoding = data[content_offset + 4]
    payload = data[content_offset + 12: content_offset + 12 + byte_length]
    if encoding == 2:
        return payload.decode("utf-16-le", errors="replace"), struct.unpack_from("<I", data, offset + 8)[0]
    return payload.decode("utf-8", errors="replace"), struct.unpack_from("<I", data, offset + 8)[0]


def _parse_mhni(data: bytes, offset: int) -> tuple[dict, int]:
    header_len = struct.unpack_from("<I", data, offset + 4)[0]
    total_len = struct.unpack_from("<I", data, offset + 8)[0]
    child_count = struct.unpack_from("<I", data, offset + 12)[0]
    info = {
        "format_id": struct.unpack_from("<I", data, offset + 16)[0],
        "offset": struct.unpack_from("<I", data, offset + 20)[0],
        "size": struct.unpack_from("<I", data, offset + 24)[0],
        "vpad": struct.unpack_from("<h", data, offset + 28)[0],
        "hpad": struct.unpack_from("<h", data, offset + 30)[0],
        "height": struct.unpack_from("<H", data, offset + 32)[0],
        "width": struct.unpack_from("<H", data, offset + 34)[0],
        "path": "",
        "filename": "",
    }

    child_offset = offset + header_len
    for _ in range(child_count):
        child_type = data[child_offset: child_offset + 4]
        child_header = struct.unpack_from("<I", data, child_offset + 4)[0]
        child_total = struct.unpack_from("<I", data, child_offset + 8)[0]
        if child_type == b"mhod":
            mhod_type = struct.unpack_from("<H", data, child_offset + 12)[0]
            if mhod_type == 3:
                value, _ = _parse_mhod_string(data, child_offset, child_header)
                rel_path = _photo_db_string_to_rel_path(value)
                info["path"] = rel_path
                info["filename"] = Path(rel_path).name
        child_offset += child_total
    return info, total_len


def _parse_mhii(data: bytes, offset: int) -> tuple[PhotoEntry, int]:
    header_len = struct.unpack_from("<I", data, offset + 4)[0]
    total_len = struct.unpack_from("<I", data, offset + 8)[0]
    child_count = struct.unpack_from("<I", data, offset + 12)[0]
    image_id = struct.unpack_from("<I", data, offset + 16)[0]
    original_size = struct.unpack_from("<I", data, offset + 48)[0]
    created_at = struct.unpack_from("<I", data, offset + 40)[0] if header_len >= 52 else 0
    digitized_at = struct.unpack_from("<I", data, offset + 44)[0] if header_len >= 52 else 0
    entry = PhotoEntry(
        image_id=image_id,
        original_size=original_size,
        display_name=f"Photo {image_id}",
        created_at=created_at,
        digitized_at=digitized_at,
    )
    child_offset = offset + header_len
    for _ in range(child_count):
        child_type = data[child_offset: child_offset + 4]
        child_header = struct.unpack_from("<I", data, child_offset + 4)[0]
        child_total = struct.unpack_from("<I", data, child_offset + 8)[0]
        if child_type == b"mhod":
            mhod_type = struct.unpack_from("<H", data, child_offset + 12)[0]
            if mhod_type == 2:
                info, _ = _parse_mhni(data, child_offset + child_header)
                entry.thumbs[info["format_id"]] = PhotoThumbRef(
                    format_id=info["format_id"],
                    offset=info["offset"],
                    size=info["size"],
                    width=info["width"],
                    height=info["height"],
                    hpad=max(0, info["hpad"]),
                    vpad=max(0, info["vpad"]),
                    filename=info["filename"],
                )
            elif mhod_type == 5:
                info, _ = _parse_mhni(data, child_offset + child_header)
                entry.full_res_path = info["path"]
                entry.full_res_size = info["size"]
                if not entry.original_size:
                    entry.original_size = info["size"]
        child_offset += child_total
    return entry, total_len


def _parse_mhli(data: bytes, offset: int) -> tuple[dict[int, PhotoEntry], int]:
    header_len = struct.unpack_from("<I", data, offset + 4)[0]
    count = struct.unpack_from("<I", data, offset + 8)[0]
    child_offset = offset + header_len
    photos: dict[int, PhotoEntry] = {}
    for _ in range(count):
        if data[child_offset: child_offset + 4] != b"mhii":
            break
        entry, total_len = _parse_mhii(data, child_offset)
        photos[entry.image_id] = entry
        child_offset += total_len
    return photos, child_offset - offset


def _parse_mhia(data: bytes, offset: int) -> tuple[int, int]:
    total_len = struct.unpack_from("<I", data, offset + 8)[0]
    image_id = struct.unpack_from("<I", data, offset + 16)[0]
    return image_id, total_len


def _parse_mhba(data: bytes, offset: int) -> tuple[PhotoAlbum, int]:
    header_len = struct.unpack_from("<I", data, offset + 4)[0]
    total_len = struct.unpack_from("<I", data, offset + 8)[0]
    album = PhotoAlbum(
        album_id=struct.unpack_from("<I", data, offset + 20)[0],
        name=f"Album {struct.unpack_from('<I', data, offset + 20)[0]}",
        album_type=data[offset + 30],
        playmusic=data[offset + 31],
        repeat=data[offset + 32],
        random=data[offset + 33],
        show_titles=data[offset + 34],
        transition_direction=data[offset + 35],
        slide_duration=struct.unpack_from("<I", data, offset + 36)[0],
        transition_duration=struct.unpack_from("<I", data, offset + 40)[0],
        song_id=struct.unpack_from("<Q", data, offset + 52)[0],
        prev_album_id=struct.unpack_from("<I", data, offset + 60)[0],
    )
    child_offset = offset + header_len
    while child_offset + 12 <= offset + total_len:
        child_type = data[child_offset: child_offset + 4]
        child_header = struct.unpack_from("<I", data, child_offset + 4)[0]
        child_total = struct.unpack_from("<I", data, child_offset + 8)[0]
        if child_total <= 0:
            break
        if child_type == b"mhod":
            mhod_type = struct.unpack_from("<H", data, child_offset + 12)[0]
            if mhod_type == 1:
                value, _ = _parse_mhod_string(data, child_offset, child_header)
                album.name = value
        elif child_type == b"mhia":
            image_id, _ = _parse_mhia(data, child_offset)
            album.members.append(image_id)
        child_offset += child_total
    return album, total_len


def _parse_mhla(data: bytes, offset: int) -> tuple[list[PhotoAlbum], int]:
    header_len = struct.unpack_from("<I", data, offset + 4)[0]
    count = struct.unpack_from("<I", data, offset + 8)[0]
    child_offset = offset + header_len
    albums: list[PhotoAlbum] = []
    for _ in range(count):
        if data[child_offset: child_offset + 4] != b"mhba":
            break
        album, total_len = _parse_mhba(data, child_offset)
        albums.append(album)
        child_offset += total_len
    return albums, child_offset - offset


def _parse_mhif(data: bytes, offset: int) -> tuple[dict, int]:
    header_len = struct.unpack_from("<I", data, offset + 4)[0]
    total_len = struct.unpack_from("<I", data, offset + 8)[0]
    info = {
        "format_id": struct.unpack_from("<I", data, offset + 16)[0],
        "image_size": struct.unpack_from("<I", data, offset + 20)[0],
        "path": "",
        "filename": "",
    }
    child_offset = offset + header_len
    while child_offset + 12 <= offset + total_len:
        child_type = data[child_offset: child_offset + 4]
        child_header = struct.unpack_from("<I", data, child_offset + 4)[0]
        child_total = struct.unpack_from("<I", data, child_offset + 8)[0]
        if child_total <= 0:
            break
        if child_type == b"mhod":
            mhod_type = struct.unpack_from("<H", data, child_offset + 12)[0]
            if mhod_type == 3:
                value, _ = _parse_mhod_string(data, child_offset, child_header)
                rel_path = _photo_db_string_to_rel_path(value)
                info["path"] = rel_path
                info["filename"] = Path(rel_path).name
        child_offset += child_total
    return info, total_len


def _parse_mhlf(data: bytes, offset: int) -> tuple[dict[int, dict], int]:
    header_len = struct.unpack_from("<I", data, offset + 4)[0]
    count = struct.unpack_from("<I", data, offset + 8)[0]
    child_offset = offset + header_len
    formats: dict[int, dict] = {}
    for _ in range(count):
        if data[child_offset: child_offset + 4] != b"mhif":
            break
        info, total_len = _parse_mhif(data, child_offset)
        formats[info["format_id"]] = info
        child_offset += total_len
    return formats, child_offset - offset


def _read_photo_db_checked(ipod_path: str | Path) -> PhotoDB:
    ipod_path = Path(ipod_path)
    db_path = _photo_db_path(ipod_path)
    photodb = PhotoDB()
    try:
        data = db_path.read_bytes()
    except FileNotFoundError:
        # An orphaned mapping is still existing photo metadata. Validate it
        # before a future write is allowed to replace it.
        _load_photo_mapping(ipod_path)
        photodb.mhfd_unknown2 = _mhfd_unknown2_for_device(ipod_path)
        photodb.non_master_album_type = _non_master_album_type_for_device(ipod_path)
        photodb.master_album()
        return photodb

    if len(data) < _MHFD_HEADER_SIZE or data[:4] != b"mhfd":
        raise PhotoMetadataSafetyError(
            "The existing iPod Photo Database is malformed or incomplete. "
            "iOpenPod stopped before changing photos so the current photo "
            "library is not overwritten."
        )

    header_len = struct.unpack_from("<I", data, 4)[0]
    total_len = struct.unpack_from("<I", data, 8)[0]
    if (
        header_len < _MHFD_HEADER_SIZE
        or header_len > total_len
        or total_len > len(data)
    ):
        raise PhotoMetadataSafetyError(
            "The existing iPod Photo Database has invalid size fields. "
            "iOpenPod stopped before changing photos so the current photo "
            "library is not overwritten."
        )

    photodb.mhfd_unknown2 = struct.unpack_from("<I", data, 16)[0]

    offset = header_len
    format_meta: dict[int, dict] = {}
    while offset + 16 <= total_len:
        if data[offset: offset + 4] != b"mhsd":
            raise PhotoMetadataSafetyError(
                "The existing iPod Photo Database contains an invalid dataset."
            )
        dataset_header_len = struct.unpack_from("<I", data, offset + 4)[0]
        dataset_total_len = struct.unpack_from("<I", data, offset + 8)[0]
        if (
            dataset_header_len < 16
            or dataset_header_len > dataset_total_len
            or offset + dataset_total_len > total_len
        ):
            raise PhotoMetadataSafetyError(
                "The existing iPod Photo Database contains invalid dataset sizes."
            )
        ds_type = struct.unpack_from("<I", data, offset + 12)[0]
        child_offset = offset + dataset_header_len
        expected_child = {1: b"mhli", 2: b"mhla", 3: b"mhlf"}.get(ds_type)
        if expected_child is not None:
            child_type = data[child_offset: child_offset + 4]
            if child_type != expected_child:
                raise PhotoMetadataSafetyError(
                    "The existing iPod Photo Database contains an invalid "
                    f"type-{ds_type} dataset."
                )
            if ds_type == 1:
                photodb.photos, _ = _parse_mhli(data, child_offset)
            elif ds_type == 2:
                photodb.albums, _ = _parse_mhla(data, child_offset)
            else:
                format_meta, _ = _parse_mhlf(data, child_offset)
        offset += dataset_total_len

    if offset != total_len:
        raise PhotoMetadataSafetyError(
            "The existing iPod Photo Database is truncated between datasets."
        )

    for info in format_meta.values():
        photodb.file_sizes[info["format_id"]] = info["image_size"]
        filename = info["filename"] or f"F{info['format_id']}_1.ithmb"
        for photo in photodb.photos.values():
            ref = photo.thumbs.get(info["format_id"])
            if ref is not None and not ref.filename:
                ref.filename = filename

    by_id = photodb.photos
    for album in photodb.albums:
        for image_id in album.members:
            photo = by_id.get(image_id)
            if photo is not None:
                photo.album_names.add("" if album.album_type == 1 else album.name)

    photodb.non_master_album_type = next(
        (album.album_type for album in photodb.albums if album.album_type != 1),
        _non_master_album_type_for_device(ipod_path),
    )

    mapping = _load_photo_mapping(ipod_path)
    for photo in photodb.photos.values():
        meta = mapping.get(str(photo.image_id))
        if not meta:
            continue
        photo.visual_hash = str(meta.get("visual_hash") or "")
        photo.source_path = str(meta.get("source_path") or "")
        photo.display_name = str(meta.get("display_name") or photo.display_name)

    photodb.master_album()
    if photodb.photos:
        photodb.next_image_id = max(photodb.photos) + 1
    if photodb.albums:
        photodb.next_album_id = max(a.album_id for a in photodb.albums) + 1
    return photodb


def read_photo_db(ipod_path: str | Path) -> PhotoDB:
    """Read existing photo metadata, failing closed when it cannot be trusted."""
    try:
        return _read_photo_db_checked(ipod_path)
    except PhotoMetadataSafetyError:
        raise
    except Exception as exc:
        raise PhotoMetadataSafetyError(
            "The existing iPod Photo Database could not be read safely. "
            "iOpenPod stopped before changing photos so the current photo "
            f"library is not overwritten: {exc}"
        ) from exc


def _write_mhod_string(mhod_type: int, string: str) -> bytes:
    encoded = string.encode("utf-16-le") if mhod_type == 3 else string.encode("utf-8")
    encoding_byte = 2 if mhod_type == 3 else 1
    padding = (4 - (len(encoded) % 4)) % 4
    body = struct.pack("<I", len(encoded))
    body += struct.pack("<B", encoding_byte)
    body += b"\x00" * 3
    body += b"\x00" * 4
    body += encoded
    body += b"\x00" * padding
    header = bytearray(_MHOD_HEADER_SIZE)
    header[0:4] = b"mhod"
    struct.pack_into("<I", header, 4, _MHOD_HEADER_SIZE)
    struct.pack_into("<I", header, 8, _MHOD_HEADER_SIZE + len(body))
    struct.pack_into("<H", header, 12, mhod_type)
    header[15] = padding
    return bytes(header) + body


def _write_mhni(format_id: int, ithmb_offset: int, img_info: dict) -> bytes:
    storage_path = img_info.get("storage_path") or img_info.get("filename") or ""
    mhod3 = _write_mhod_string(3, _photo_rel_path_to_db_string(str(storage_path)))
    header = bytearray(_MHNI_HEADER_SIZE)
    header[0:4] = b"mhni"
    struct.pack_into("<I", header, 4, _MHNI_HEADER_SIZE)
    struct.pack_into("<I", header, 8, _MHNI_HEADER_SIZE + len(mhod3))
    struct.pack_into("<I", header, 12, 1)
    struct.pack_into("<I", header, 16, format_id)
    struct.pack_into("<I", header, 20, ithmb_offset)
    struct.pack_into("<I", header, 24, img_info["size"])
    struct.pack_into("<h", header, 28, int(img_info.get("vpad", 0)))
    struct.pack_into("<h", header, 30, int(img_info.get("hpad", 0)))
    struct.pack_into("<H", header, 32, int(img_info["height"]))
    struct.pack_into("<H", header, 34, int(img_info["width"]))
    struct.pack_into("<I", header, 40, img_info["size"])
    return bytes(header) + mhod3


def _write_mhod_container(mhod_type: int, child_data: bytes) -> bytes:
    header = bytearray(_MHOD_HEADER_SIZE)
    header[0:4] = b"mhod"
    struct.pack_into("<I", header, 4, _MHOD_HEADER_SIZE)
    struct.pack_into("<I", header, 8, _MHOD_HEADER_SIZE + len(child_data))
    struct.pack_into("<H", header, 12, mhod_type)
    return bytes(header) + child_data


def _write_mhii(
    entry: PhotoEntry,
    format_offsets: dict[int, int],
    full_res_sizes: dict[int, int],
) -> bytes:
    children = []
    full_res_rel_path = entry.full_res_path or _full_res_rel_path_for_entry(entry)
    full_res_size = full_res_sizes.get(entry.image_id, entry.full_res_size or entry.original_size)
    full_res_info = {
        "width": 0,
        "height": 0,
        "size": full_res_size,
        "hpad": 0,
        "vpad": 0,
        "storage_path": full_res_rel_path,
    }
    children.append(_write_mhod_container(5, _write_mhni(1, 0, full_res_info)))
    for fmt_id in sorted(entry.thumbs):
        thumb = entry.thumbs[fmt_id]
        img_info = {
            "width": thumb.width,
            "height": thumb.height,
            "size": thumb.size,
            "hpad": thumb.hpad,
            "vpad": thumb.vpad,
            "storage_path": str(Path("Thumbs") / (thumb.filename or f"F{fmt_id}_1.ithmb")),
        }
        mhni = _write_mhni(fmt_id, format_offsets.get(fmt_id, thumb.offset), img_info)
        children.append(_write_mhod_container(2, mhni))

    children_data = b"".join(children)
    header = bytearray(_MHII_HEADER_SIZE)
    header[0:4] = b"mhii"
    struct.pack_into("<I", header, 4, _MHII_HEADER_SIZE)
    struct.pack_into("<I", header, 8, _MHII_HEADER_SIZE + len(children_data))
    struct.pack_into("<I", header, 12, len(children))
    struct.pack_into("<I", header, 16, entry.image_id)
    struct.pack_into("<I", header, 40, entry.created_at)
    struct.pack_into("<I", header, 44, entry.digitized_at)
    struct.pack_into("<I", header, 48, entry.original_size)
    return bytes(header) + children_data


def _write_mhli(entries: list[PhotoEntry], full_res_sizes: dict[int, int]) -> bytes:
    children = b"".join(
        _write_mhii(
            entry,
            {fmt_id: ref.offset for fmt_id, ref in entry.thumbs.items()},
            full_res_sizes,
        )
        for entry in entries
    )
    header = bytearray(_MHLI_HEADER_SIZE)
    header[0:4] = b"mhli"
    struct.pack_into("<I", header, 4, _MHLI_HEADER_SIZE)
    struct.pack_into("<I", header, 8, len(entries))
    return bytes(header) + children


def _write_mhia(image_id: int) -> bytes:
    header = bytearray(_MHIA_HEADER_SIZE)
    header[0:4] = b"mhia"
    struct.pack_into("<I", header, 4, _MHIA_HEADER_SIZE)
    struct.pack_into("<I", header, 8, _MHIA_HEADER_SIZE)
    struct.pack_into("<I", header, 16, image_id)
    return bytes(header)


def _write_mhba(album: PhotoAlbum) -> bytes:
    children = [_write_mhod_string(1, album.name)]
    children.extend(_write_mhia(image_id) for image_id in album.members)
    children_data = b"".join(children)
    header = bytearray(_MHBA_HEADER_SIZE)
    header[0:4] = b"mhba"
    struct.pack_into("<I", header, 4, _MHBA_HEADER_SIZE)
    struct.pack_into("<I", header, 8, _MHBA_HEADER_SIZE + len(children_data))
    struct.pack_into("<I", header, 12, 1)
    struct.pack_into("<I", header, 16, len(album.members))
    struct.pack_into("<I", header, 20, album.album_id)
    struct.pack_into("<H", header, 28, 0)
    header[30] = album.album_type & 0xFF
    header[31] = album.playmusic & 0xFF
    header[32] = album.repeat & 0xFF
    header[33] = album.random & 0xFF
    header[34] = album.show_titles & 0xFF
    header[35] = album.transition_direction & 0xFF
    struct.pack_into("<I", header, 36, album.slide_duration)
    struct.pack_into("<I", header, 40, album.transition_duration)
    struct.pack_into("<Q", header, 52, album.song_id)
    struct.pack_into("<I", header, 60, album.prev_album_id)
    return bytes(header) + children_data


def _write_mhla(albums: list[PhotoAlbum]) -> bytes:
    children = b"".join(_write_mhba(album) for album in albums)
    header = bytearray(_MHLA_HEADER_SIZE)
    header[0:4] = b"mhla"
    struct.pack_into("<I", header, 4, _MHLA_HEADER_SIZE)
    struct.pack_into("<I", header, 8, len(albums))
    return bytes(header) + children


def _write_mhif(format_id: int, image_size: int) -> bytes:
    header = bytearray(_MHIF_HEADER_SIZE)
    header[0:4] = b"mhif"
    struct.pack_into("<I", header, 4, _MHIF_HEADER_SIZE)
    struct.pack_into("<I", header, 8, _MHIF_HEADER_SIZE)
    struct.pack_into("<I", header, 12, 0)
    struct.pack_into("<I", header, 16, format_id)
    struct.pack_into("<I", header, 20, image_size)
    return bytes(header)


def _write_mhlf(image_sizes: dict[int, int]) -> bytes:
    format_ids = sorted(image_sizes)
    children = b"".join(_write_mhif(fmt_id, image_sizes[fmt_id]) for fmt_id in format_ids)
    header = bytearray(_MHLF_HEADER_SIZE)
    header[0:4] = b"mhlf"
    struct.pack_into("<I", header, 4, _MHLF_HEADER_SIZE)
    struct.pack_into("<I", header, 8, len(format_ids))
    return bytes(header) + children


def _write_mhsd(ds_type: int, child_data: bytes) -> bytes:
    header = bytearray(_MHSD_HEADER_SIZE)
    header[0:4] = b"mhsd"
    struct.pack_into("<I", header, 4, _MHSD_HEADER_SIZE)
    struct.pack_into("<I", header, 8, _MHSD_HEADER_SIZE + len(child_data))
    struct.pack_into("<I", header, 12, ds_type)
    return bytes(header) + child_data


def _write_mhfd(datasets: list[bytes], next_mhii_id: int, unknown2: int) -> bytes:
    datasets_data = b"".join(datasets)
    header = bytearray(_MHFD_HEADER_SIZE)
    header[0:4] = b"mhfd"
    struct.pack_into("<I", header, 4, _MHFD_HEADER_SIZE)
    struct.pack_into("<I", header, 8, _MHFD_HEADER_SIZE + len(datasets_data))
    struct.pack_into("<I", header, 12, 0)
    struct.pack_into("<I", header, 16, int(unknown2))
    struct.pack_into("<I", header, 20, len(datasets))
    struct.pack_into("<I", header, 24, 0)
    struct.pack_into("<I", header, 28, next_mhii_id)
    struct.pack_into("<I", header, 48, 2)
    struct.pack_into("<I", header, 52, 0)
    return bytes(header) + datasets_data


def _current_device_family_gen(ipod_path: str | Path | None = None) -> tuple[str, str]:
    try:
        from iopenpod.device import (
            DeviceInfo,
            enrich,
            get_current_device,
            get_current_device_for_path,
            read_sysinfo,
        )
        dev = (
            get_current_device_for_path(ipod_path)
            if ipod_path is not None
            else get_current_device()
        )
        if dev is None and ipod_path is not None:
            dev = DeviceInfo(path=str(ipod_path))
            dev.sysinfo = read_sysinfo(str(ipod_path))
            enrich(dev)
        if dev:
            return dev.model_family or "", dev.generation or ""
    except Exception:
        pass
    return "", ""


def _mhfd_unknown2_for_device(ipod_path: str | Path | None = None) -> int:
    # Empirical iTunes-written databases across Nano 2/6/7 all use 6.
    # Keep this fixed for maximum compatibility.
    return _DEFAULT_MHFD_UNKNOWN2


def _non_master_album_type_for_device(ipod_path: str | Path | None = None) -> int:
    family, generation = _current_device_family_gen(ipod_path)
    if family == "iPod Nano" and generation in {"6th Gen", "7th Gen"}:
        return _NANO_67_NON_MASTER_ALBUM_TYPE
    return _DEFAULT_NON_MASTER_ALBUM_TYPE


def _photo_formats_for_current_device(ipod_path: str | Path | None = None) -> Mapping[int, ArtworkFormat]:
    try:
        family, generation = _current_device_family_gen(ipod_path)
        if family:
            formats = photo_formats_for_device(family, generation)
            if formats:
                return formats
    except Exception:
        pass
    if ipod_path is not None:
        return {}
    return photo_formats_for_device("iPod Classic", "6.5th Gen")


def _estimated_photo_storage_bytes(formats: Mapping[int, ArtworkFormat]) -> int:
    total = 0
    for fmt_id, fmt in formats.items():
        width = max(1, int(fmt.width or 0))
        height = max(1, int(fmt.height or 0))
        size = expected_size_bytes(
            int(fmt_id),
            width,
            height,
            fmt_override=fmt,
        )
        if size <= 0 and int(fmt.row_bytes or 0) > 0:
            size = int(fmt.row_bytes) * height
        total += max(0, int(size))
    return total


def _fit_dimensions(src_w: int, src_h: int, target_w: int, target_h: int) -> tuple[int, int]:
    width_scale = target_w / src_w
    height_scale = target_h / src_h
    if width_scale < height_scale:
        fitted_w = target_w
        fitted_h = min(int(math.ceil(src_h * width_scale)), target_h)
    elif width_scale > height_scale:
        fitted_w = min(int(math.ceil(src_w * height_scale)), target_w)
        fitted_h = target_h
    else:
        fitted_w = target_w
        fitted_h = target_h
    return (
        max(1, min(target_w, fitted_w)),
        max(1, min(target_h, fitted_h)),
    )


def _fitted_area(src_w: int, src_h: int, target_w: int, target_h: int) -> int:
    fitted_w, fitted_h = _fit_dimensions(src_w, src_h, target_w, target_h)
    return fitted_w * fitted_h


def _should_rotate_tall_photo_for_format(
    img: Image.Image,
    fmt: ArtworkFormat,
    rotate_tall_photos: bool,
) -> bool:
    if not rotate_tall_photos or fmt.role not in _ROTATABLE_PHOTO_ROLES:
        return False
    src_w, src_h = img.size
    target_w = max(1, int(fmt.width))
    target_h = max(1, int(fmt.height))
    if src_w <= 0 or src_h <= 0 or src_h <= src_w:
        return False
    if (src_h / src_w) < _ROTATE_TALL_PHOTO_ASPECT_THRESHOLD:
        return False

    normal_area = _fitted_area(src_w, src_h, target_w, target_h)
    rotated_area = _fitted_area(src_h, src_w, target_w, target_h)
    return rotated_area >= int(math.ceil(normal_area * _ROTATE_TALL_PHOTO_GAIN_THRESHOLD))


def _prepare_full_res_photo(
    img: Image.Image,
    formats: Mapping[int, ArtworkFormat],
    rotate_tall_photos: bool,
) -> Image.Image:
    source = img.convert("RGB")
    candidates = [
        fmt for fmt in formats.values()
        if fmt.role in _FULL_RES_ROTATION_ROLES
    ]
    if not candidates:
        return source
    representative = max(candidates, key=lambda fmt: int(fmt.width) * int(fmt.height))
    if _should_rotate_tall_photo_for_format(source, representative, rotate_tall_photos):
        return source.transpose(Image.Transpose.ROTATE_270)
    return source


def _fit_photo_to_format(
    img: Image.Image,
    fmt: ArtworkFormat,
    *,
    fit_thumbnails: bool,
) -> tuple[Image.Image, int, int, int, int]:
    target_w = max(1, int(fmt.width))
    target_h = max(1, int(fmt.height))
    source = img.convert("RGB")
    src_w, src_h = source.size
    if src_w <= 0 or src_h <= 0:
        fallback = source.resize((target_w, target_h), Image.Resampling.LANCZOS)
        return fallback, target_w, target_h, 0, 0

    if fmt.role in _THUMBNAIL_PHOTO_ROLES and not fit_thumbnails:
        # iTunes-style thumbnail rendering: zoom and crop to fill.
        fill_scale = max(target_w / src_w, target_h / src_h)
        fill_w = max(1, int(math.ceil(src_w * fill_scale)))
        fill_h = max(1, int(math.ceil(src_h * fill_scale)))
        filled = source.resize((fill_w, fill_h), Image.Resampling.LANCZOS)
        left = max(0, (fill_w - target_w) // 2)
        top = max(0, (fill_h - target_h) // 2)
        cropped = filled.crop((left, top, left + target_w, top + target_h))
        return cropped, target_w, target_h, 0, 0

    fitted_w, fitted_h = _fit_dimensions(src_w, src_h, target_w, target_h)

    # iPod photo MHNI padding is effectively symmetric per side. Ensure the
    # raster overhang can be split evenly into left/right and top/bottom pads.
    if fitted_w < target_w and ((target_w - fitted_w) % 2) != 0:
        fitted_w = max(1, fitted_w - 1)
    if fitted_h < target_h and ((target_h - fitted_h) % 2) != 0:
        fitted_h = max(1, fitted_h - 1)

    # Log undersized photos for diagnostic purposes
    if fit_thumbnails and (fitted_w < target_w or fitted_h < target_h):
        logger.info(
            f"Photo thumbnail undersized: {fitted_w}x{fitted_h} fit into "
            f"{target_w}x{target_h} format (role={fmt.role}, id={fmt.format_id})"
        )

    fitted = source.resize((fitted_w, fitted_h), Image.Resampling.LANCZOS)
    if fitted_w == target_w and fitted_h == target_h:
        return fitted, target_w, target_h, 0, 0

    # Store the padded raster at the format's full dimensions, but expose the
    # active image region through MHNI width/height + hpad/vpad so decoders
    # can crop using iPod-style padding semantics.
    hpad = max(0, (target_w - fitted_w) // 2)
    vpad = max(0, (target_h - fitted_h) // 2)
    canvas = Image.new("RGB", (target_w, target_h), (0, 0, 0))
    canvas.paste(fitted, (hpad, vpad))

    # For photo formats, readers expect:
    #   stored ~= (width + hpad, height + vpad)
    # where hpad/vpad are per-side margins.
    visible_w = max(1, target_w - (2 * hpad))
    visible_h = max(1, target_h - (2 * vpad))
    mhni_width = visible_w + hpad
    mhni_height = visible_h + vpad
    return canvas, mhni_width, mhni_height, hpad, vpad


def _encode_photo_for_formats(
    img: Image.Image,
    formats: Mapping[int, ArtworkFormat],
    *,
    rotate_tall_photos: bool = False,
    fit_thumbnails: bool = False,
) -> dict[int, dict]:
    encoded: dict[int, dict] = {}
    for fmt_id, fmt in sorted(formats.items()):
        source = img
        if _should_rotate_tall_photo_for_format(img, fmt, rotate_tall_photos):
            source = img.transpose(Image.Transpose.ROTATE_270)
        prepared, mhni_w, mhni_h, hpad, vpad = _fit_photo_to_format(
            source,
            fmt,
            fit_thumbnails=fit_thumbnails,
        )
        meta = encode_image_for_format(
            prepared,
            fmt_id,
            int(fmt.width),
            int(fmt.height),
            fmt_override=fmt,
        )
        encoded[fmt_id] = {
            "data": meta.data,
            "width": int(mhni_w),
            "height": int(mhni_h),
            "size": int(meta.size),
            "hpad": int(hpad),
            "vpad": int(vpad),
            "filename": f"F{fmt_id}_1.ithmb",
        }
    return encoded


def load_photo_preview(
    photo: PhotoEntry,
    ipod_path: str | Path,
    *,
    format_id: int | None = None,
) -> Image.Image | None:
    if format_id is not None:
        return _decode_photo_format(photo, ipod_path, format_id)
    # Default preview follows iPod output first (thumb formats), not raw source-like full-res.
    return _decode_photo_image(photo, ipod_path)


def _write_photo_db_snapshot(
    ipod_path: str | Path,
    photodb: PhotoDB,
    source_images: dict[int, Image.Image],
    progress_callback: Callable[[str, int, int, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    sync_settings: dict[str, bool] | None = None,
    before_device_mutation: Callable[[], None] | None = None,
    filesystem_profile: FilesystemProfile | None = None,
) -> None:
    ipod_path = Path(ipod_path)
    read_photo_db(ipod_path)
    formats = _photo_formats_for_current_device(ipod_path)
    if not formats:
        raise RuntimeError("No photo formats available for the current device")
    _preflight_photo_snapshot_sizes(photodb, formats, filesystem_profile)
    db_path = _photo_db_path(ipod_path)
    thumbs_dir = _photo_thumbs_dir(ipod_path)
    full_res_dir = _photo_full_res_dir(ipod_path)
    if before_device_mutation is not None:
        before_device_mutation()
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    full_res_dir.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    sync_settings = _current_photo_sync_settings(sync_settings)
    rotate_tall_photos = bool(sync_settings.get("rotate_tall_photos_for_device", False))
    fit_thumbnails = bool(sync_settings.get("fit_photo_thumbnails", False))

    payloads_by_format: dict[int, bytearray] = {fmt_id: bytearray() for fmt_id in formats}
    file_sizes: dict[int, int] = {fmt_id: 0 for fmt_id in formats}
    image_sizes: dict[int, int] = {
        fmt_id: int(fmt.row_bytes) * int(fmt.height)
        for fmt_id, fmt in formats.items()
    }
    filenames: dict[int, str] = {fmt_id: f"F{fmt_id}_1.ithmb" for fmt_id in formats}
    full_res_sizes: dict[int, int] = {}
    live_full_res_paths: set[Path] = set()

    ordered_photos = sorted(photodb.photos.values(), key=lambda p: p.image_id)
    total = len(ordered_photos)
    for index, photo in enumerate(ordered_photos, start=1):
        if is_cancelled and is_cancelled():
            return
        if progress_callback:
            progress_callback("photo_write", index, total, photo.display_name or f"Photo {photo.image_id}")
        image = source_images.get(photo.image_id)
        if image is None:
            raise RuntimeError(f"Missing source image for photo {photo.image_id}")
        photo.full_res_path = _full_res_rel_path_for_entry(photo)
        full_res_target = _device_photo_path(ipod_path, photo.full_res_path)
        if before_device_mutation is not None:
            before_device_mutation()
        full_res_target.parent.mkdir(parents=True, exist_ok=True)
        full_res_image = _prepare_full_res_photo(image, formats, rotate_tall_photos)
        _replace_jpeg_durably(
            full_res_target,
            full_res_image,
            before_device_mutation=before_device_mutation,
        )
        full_res_sizes[photo.image_id] = full_res_target.stat().st_size
        photo.full_res_size = full_res_sizes[photo.image_id]
        live_full_res_paths.add(full_res_target.resolve())
        if not photo.original_size:
            photo.original_size = full_res_sizes[photo.image_id]
        encoded = _encode_photo_for_formats(
            image,
            formats,
            rotate_tall_photos=rotate_tall_photos,
            fit_thumbnails=fit_thumbnails,
        )
        photo.thumbs.clear()
        for fmt_id, info in encoded.items():
            offset = len(payloads_by_format[fmt_id])
            payloads_by_format[fmt_id].extend(info["data"])
            file_sizes[fmt_id] = len(payloads_by_format[fmt_id])
            image_sizes[fmt_id] = int(info["size"])
            photo.thumbs[fmt_id] = PhotoThumbRef(
                format_id=fmt_id,
                offset=offset,
                size=info["size"],
                width=info["width"],
                height=info["height"],
                hpad=info["hpad"],
                vpad=info["vpad"],
                filename=info["filename"],
            )

    mhli = _write_mhli(ordered_photos, full_res_sizes)
    mhla = _write_mhla(photodb.albums)
    mhlf = _write_mhlf(image_sizes)
    highest_image_id = max((photo.image_id for photo in ordered_photos), default=_MIN_PHOTO_ID - 1)
    next_mhii_id = highest_image_id + len(photodb.albums) + 1
    unknown2 = _mhfd_unknown2_for_device(ipod_path)
    photodb.mhfd_unknown2 = unknown2
    data = _write_mhfd(
        [_write_mhsd(1, mhli), _write_mhsd(2, mhla), _write_mhsd(3, mhlf)],
        next_mhii_id,
        unknown2,
    )

    _replace_bytes_durably(
        db_path,
        data,
        before_device_mutation=before_device_mutation,
    )

    live_files = set()
    for fmt_id, payload in payloads_by_format.items():
        filename = filenames[fmt_id]
        live_files.add(filename)
        _replace_bytes_durably(
            thumbs_dir / filename,
            bytes(payload),
            before_device_mutation=before_device_mutation,
        )

    for stale in thumbs_dir.glob("F*_*.ithmb"):
        if stale.name not in live_files:
            safe_stale = _safe_enumerated_photo_path(
                ipod_path,
                stale,
                allowed_subtree=_PHOTO_THUMBS_RELATIVE,
            )
            if before_device_mutation is not None:
                before_device_mutation()
            durable_unlink(safe_stale, missing_ok=True)

    managed_full_res_root = resolve_device_path(
        ipod_path,
        _PHOTO_FULL_RES_RELATIVE / "iOpenPod",
        allowed_subtree=_PHOTO_FULL_RES_RELATIVE,
    )
    if managed_full_res_root.exists():
        for stale in managed_full_res_root.rglob("*.jpg"):
            safe_stale = _safe_enumerated_photo_path(
                ipod_path,
                stale,
                allowed_subtree=_PHOTO_FULL_RES_RELATIVE,
            )
            if safe_stale not in live_full_res_paths:
                if before_device_mutation is not None:
                    before_device_mutation()
                durable_unlink(safe_stale, missing_ok=True)

    photodb.file_sizes = file_sizes
    _save_photo_mapping(
        ipod_path,
        photodb,
        sync_settings=sync_settings,
        before_device_mutation=before_device_mutation,
    )


def build_photo_sync_plan(
    pc_photos: PCPhotoLibrary,
    device_photos: PhotoDB,
    staged_edits: PhotoEditState | None = None,
    *,
    ipod_path: str | Path | None = None,
    sync_settings: dict[str, bool] | None = None,
) -> PhotoSyncPlan:
    library = _apply_photo_edits(pc_photos, staged_edits)
    photodb = copy.deepcopy(device_photos)
    if ipod_path is not None:
        # Keep sync planning deterministic from on-device data only.
        _ensure_visual_hashes(photodb, ipod_path)
    sync_settings = _current_photo_sync_settings(sync_settings)
    stored_sync_settings = (
        _load_photo_mapping_settings(ipod_path) if ipod_path is not None
        else {
            "rotate_tall_photos_for_device": False,
            "fit_photo_thumbnails": False,
        }
    )

    plan = PhotoSyncPlan(current_db=photodb, desired_library=library, skipped_files=list(library.skipped))
    estimated_add_bytes_per_photo = _estimated_photo_storage_bytes(_photo_formats_for_current_device(ipod_path))

    existing_by_hash: dict[str, PhotoEntry] = {}
    for photo in photodb.photos.values():
        if photo.visual_hash:
            existing_by_hash[photo.visual_hash] = photo

    desired_hashes = set(library.photos)
    existing_hashes = set(existing_by_hash)

    desired_albums = {name for name in library.albums if name}
    existing_albums = {album.name for album in photodb.albums if album.album_type != 1}

    plan.albums_to_add = [
        PhotoAlbumChange(album_name=name, item_count=sum(1 for p in library.photos.values() if name in p.album_names))
        for name in sorted(desired_albums - existing_albums)
    ]
    plan.albums_to_remove = [
        PhotoAlbumChange(album_name=name, item_count=sum(1 for p in photodb.photos.values() if name in p.album_names))
        for name in sorted(existing_albums - desired_albums)
    ]

    for visual_hash in sorted(desired_hashes - existing_hashes):
        photo = library.photos[visual_hash]
        estimated_size = estimated_add_bytes_per_photo or photo.size
        plan.photos_to_add.append(PhotoSyncItem(
            visual_hash=visual_hash,
            display_name=photo.display_name,
            album_names=set(photo.album_names),
            source_path=photo.source_path,
            size=photo.size,
            description=f"Add photo {photo.display_name}",
            estimated_size=estimated_size,
        ))
        plan.thumb_bytes_to_add += estimated_size

    for visual_hash in sorted(existing_hashes - desired_hashes):
        photo = existing_by_hash[visual_hash]
        plan.photos_to_remove.append(PhotoSyncItem(
            visual_hash=visual_hash,
            display_name=photo.display_name,
            album_names=set(photo.album_names),
            source_path=photo.source_path,
            image_id=photo.image_id,
            size=photo.original_size,
            description=f"Remove photo {photo.display_name}",
        ))
        plan.thumb_bytes_to_remove += photo.original_size

    for visual_hash in sorted(desired_hashes & existing_hashes):
        desired = library.photos[visual_hash]
        existing = existing_by_hash[visual_hash]
        desired_members = {name for name in desired.album_names if name}
        existing_members = {name for name in existing.album_names if name}

        for album_name in sorted(desired_members - existing_members):
            plan.album_membership_adds.append(PhotoMembershipChange(
                visual_hash=visual_hash,
                album_name=album_name,
                display_name=desired.display_name,
                source_path=desired.source_path,
                image_id=existing.image_id,
                size=desired.size,
            ))
        for album_name in sorted(existing_members - desired_members):
            plan.album_membership_removes.append(PhotoMembershipChange(
                visual_hash=visual_hash,
                album_name=album_name,
                display_name=existing.display_name,
                source_path=existing.source_path,
                image_id=existing.image_id,
                size=existing.original_size,
            ))

    if (
        bool(sync_settings.get("rotate_tall_photos_for_device", False))
        != bool(stored_sync_settings.get("rotate_tall_photos_for_device", False))
        or bool(sync_settings.get("fit_photo_thumbnails", False))
        != bool(stored_sync_settings.get("fit_photo_thumbnails", False))
    ):
        rotate_changed = (
            bool(sync_settings.get("rotate_tall_photos_for_device", False))
            != bool(stored_sync_settings.get("rotate_tall_photos_for_device", False))
        )
        thumb_mode_changed = (
            bool(sync_settings.get("fit_photo_thumbnails", False))
            != bool(stored_sync_settings.get("fit_photo_thumbnails", False))
        )
        if rotate_changed and thumb_mode_changed:
            update_desc = "Regenerate device photo views after photo rendering settings changed"
        elif rotate_changed:
            update_desc = (
                "Regenerate device photo views with tall-photo rotation enabled"
                if sync_settings.get("rotate_tall_photos_for_device", False)
                else "Regenerate device photo views with original orientation"
            )
        else:
            update_desc = (
                "Regenerate photo thumbnails with aspect-fit mode"
                if sync_settings.get("fit_photo_thumbnails", False)
                else "Regenerate photo thumbnails with iTunes-style crop-to-fill"
            )

        for visual_hash in sorted(desired_hashes & existing_hashes):
            desired = library.photos[visual_hash]
            existing = existing_by_hash[visual_hash]
            plan.photos_to_update.append(PhotoSyncItem(
                visual_hash=visual_hash,
                display_name=desired.display_name or existing.display_name,
                album_names=set(desired.album_names or existing.album_names),
                source_path=desired.source_path or existing.source_path,
                image_id=existing.image_id,
                size=desired.size or existing.original_size,
                description=update_desc,
            ))

    return plan


def merge_photo_sync_plan(current_db: PhotoDB, photo_plan: PhotoSyncPlan | None) -> PhotoDB:
    """Apply a photo sync plan to a PhotoDB structure without rewriting image payloads."""
    if not photo_plan:
        return current_db
    final_by_hash = {photo.visual_hash: photo for photo in current_db.photos.values() if photo.visual_hash}
    desired_lookup = photo_plan.desired_library.photos if photo_plan.desired_library else {}

    for item in photo_plan.photos_to_add:
        existing = final_by_hash.get(item.visual_hash)
        source = desired_lookup.get(item.visual_hash)
        album_names = set(source.album_names) if source is not None else set(item.album_names)
        if existing is None:
            existing = PhotoEntry(
                image_id=current_db.next_image_id,
                original_size=item.size,
                display_name=item.display_name,
                visual_hash=item.visual_hash,
                source_path=item.source_path,
                album_names=album_names,
            )
            current_db.next_image_id += 1
        else:
            existing.original_size = item.size or existing.original_size
            existing.display_name = item.display_name or existing.display_name
            existing.source_path = item.source_path or existing.source_path
            existing.album_names.update(album_names)
        if existing.source_path and Path(existing.source_path).exists():
            timestamp = _source_timestamp(existing.source_path)
            existing.created_at = timestamp
            existing.digitized_at = timestamp
        final_by_hash[item.visual_hash] = existing

    for item in photo_plan.photos_to_update:
        existing = final_by_hash.get(item.visual_hash)
        if existing is not None:
            existing.display_name = item.display_name or existing.display_name
            existing.source_path = item.source_path or existing.source_path

    for item in photo_plan.album_membership_adds:
        existing = final_by_hash.get(item.visual_hash)
        if existing is not None and item.album_name:
            existing.album_names.add(item.album_name)

    for item in photo_plan.album_membership_removes:
        existing = final_by_hash.get(item.visual_hash)
        if existing is not None and item.album_name:
            existing.album_names.discard(item.album_name)

    for item in photo_plan.photos_to_remove:
        final_by_hash.pop(item.visual_hash, None)

    current_db.photos = {photo.image_id: photo for photo in final_by_hash.values()}

    existing_album_ids = {album.name: album.album_id for album in current_db.albums if album.album_type != 1}
    final_album_names = set(existing_album_ids)
    final_album_names.update(change.album_name for change in photo_plan.albums_to_add if change.album_name)
    final_album_names.difference_update(change.album_name for change in photo_plan.albums_to_remove if change.album_name)
    for photo in current_db.photos.values():
        photo.album_names.intersection_update(final_album_names)

    non_master_album_type = int(current_db.non_master_album_type or _DEFAULT_NON_MASTER_ALBUM_TYPE)
    master = current_db.master_album()
    if not master.name:
        master.name = _MASTER_ALBUM_NAME
    master.album_type = 1
    master.members = sorted(photo.image_id for photo in current_db.photos.values())
    highest_image_id = max((photo.image_id for photo in current_db.photos.values()), default=_MIN_PHOTO_ID - 1)
    ordered_album_names = sorted(final_album_names)
    master.album_id = highest_image_id + 1
    master.prev_album_id = _MIN_PHOTO_ID
    albums = [master]
    prev_album = master
    for index, name in enumerate(ordered_album_names, start=1):
        members = sorted(photo.image_id for photo in current_db.photos.values() if name in photo.album_names)
        album = PhotoAlbum(
            album_id=highest_image_id + 1 + index,
            name=name,
            album_type=non_master_album_type,
            members=members,
            prev_album_id=(_MIN_PHOTO_ID + 1) if index == 1 else (prev_album.prev_album_id + len(prev_album.members) + 1),
        )
        albums.append(album)
        prev_album = album
    current_db.albums = albums
    current_db.non_master_album_type = non_master_album_type
    current_db.next_album_id = max((album.album_id for album in current_db.albums), default=_MIN_PHOTO_ID - 1) + 1
    return current_db


def write_photo_db_metadata_only(
    ipod_path: str | Path,
    photodb: PhotoDB,
    *,
    sync_settings: Mapping[str, object] | None = None,
    before_device_mutation: Callable[[], None] | None = None,
) -> None:
    """Rewrite only the photo database metadata, preserving existing image payload files."""
    ipod_path = Path(ipod_path)
    read_photo_db(ipod_path)
    db_path = _photo_db_path(ipod_path)
    if before_device_mutation is not None:
        before_device_mutation()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    ordered_photos = sorted(photodb.photos.values(), key=lambda p: p.image_id)
    full_res_sizes = {
        photo.image_id: int(photo.full_res_size or photo.original_size)
        for photo in ordered_photos
    }
    file_sizes: dict[int, int] = {}
    image_sizes: dict[int, int] = {}
    for photo in ordered_photos:
        for fmt_id, thumb in photo.thumbs.items():
            file_sizes[fmt_id] = max(file_sizes.get(fmt_id, 0), int(thumb.offset) + int(thumb.size))
            image_sizes.setdefault(fmt_id, int(thumb.size))

    mhli = _write_mhli(ordered_photos, full_res_sizes)
    mhla = _write_mhla(photodb.albums)
    mhlf = _write_mhlf(image_sizes)
    highest_image_id = max((photo.image_id for photo in ordered_photos), default=_MIN_PHOTO_ID - 1)
    next_mhii_id = highest_image_id + len(photodb.albums) + 1
    unknown2 = _mhfd_unknown2_for_device(ipod_path)
    photodb.mhfd_unknown2 = unknown2
    data = _write_mhfd(
        [_write_mhsd(1, mhli), _write_mhsd(2, mhla), _write_mhsd(3, mhlf)],
        next_mhii_id,
        unknown2,
    )

    _replace_bytes_durably(
        db_path,
        data,
        before_device_mutation=before_device_mutation,
    )

    photodb.file_sizes = file_sizes
    _save_photo_mapping(
        ipod_path,
        photodb,
        sync_settings=_current_photo_sync_settings(sync_settings),
        before_device_mutation=before_device_mutation,
    )


@dataclass(frozen=True)
class _PhotoSyncChangeSet:
    removed_ids: set[int]
    updated_ids: set[int]
    new_ids: set[int]
    touch_ids: list[int]


def _photo_format_payload_size(fmt_id: int, fmt: ArtworkFormat) -> int:
    size = expected_size_bytes(
        int(fmt_id),
        max(1, int(fmt.width or 0)),
        max(1, int(fmt.height or 0)),
        fmt_override=fmt,
    )
    if size <= 0 and int(fmt.row_bytes or 0) > 0:
        size = int(fmt.row_bytes) * max(1, int(fmt.height or 0))
    return max(0, int(size))


def _preflight_photo_ithmb_sizes(
    ipod_path: Path,
    photodb: PhotoDB,
    change_set: _PhotoSyncChangeSet,
    formats: Mapping[int, ArtworkFormat],
    filesystem_profile: FilesystemProfile | None,
) -> None:
    """Reject unrepresentable final ITHMB sizes before photo mutations."""
    max_file_size = (
        filesystem_profile.max_file_size_bytes
        if filesystem_profile is not None
        else None
    )
    if not max_file_size:
        return

    will_compact = bool(change_set.removed_ids or change_set.updated_ids)
    final_sizes: dict[int, int] = {}
    if will_compact:
        touched = set(change_set.touch_ids)
        for photo in photodb.photos.values():
            if photo.image_id in touched:
                for fmt_id, fmt in formats.items():
                    final_sizes[fmt_id] = (
                        final_sizes.get(fmt_id, 0)
                        + _photo_format_payload_size(fmt_id, fmt)
                    )
                continue
            for fmt_id, thumb in photo.thumbs.items():
                final_sizes[fmt_id] = final_sizes.get(fmt_id, 0) + max(
                    0,
                    int(thumb.size),
                )
    elif change_set.touch_ids:
        for fmt_id, fmt in formats.items():
            thumb_path = _device_photo_thumb_path(
                ipod_path,
                f"F{fmt_id}_1.ithmb",
            )
            try:
                disk_size = int(thumb_path.stat().st_size)
            except FileNotFoundError:
                disk_size = 0
            baseline = max(
                0,
                int(photodb.file_sizes.get(fmt_id, 0)),
                disk_size,
            )
            final_sizes[fmt_id] = (
                baseline
                + len(change_set.touch_ids)
                * _photo_format_payload_size(fmt_id, fmt)
            )

    for fmt_id, final_size in final_sizes.items():
        require_file_size_supported(
            final_size,
            max_file_size_bytes=max_file_size,
            display_name=f"F{fmt_id}_1.ithmb photo thumbnail file",
        )


def _preflight_photo_snapshot_sizes(
    photodb: PhotoDB,
    formats: Mapping[int, ArtworkFormat],
    filesystem_profile: FilesystemProfile | None,
) -> None:
    max_file_size = (
        filesystem_profile.max_file_size_bytes
        if filesystem_profile is not None
        else None
    )
    if not max_file_size:
        return
    photo_count = len(photodb.photos)
    for fmt_id, fmt in formats.items():
        require_file_size_supported(
            photo_count * _photo_format_payload_size(fmt_id, fmt),
            max_file_size_bytes=max_file_size,
            display_name=f"F{fmt_id}_1.ithmb photo thumbnail file",
        )


def _collect_removed_photo_ids(photo_plan: PhotoSyncPlan) -> set[int]:
    return {
        int(item.image_id)
        for item in photo_plan.photos_to_remove
        if int(item.image_id or 0) > 0
    }


def _collect_updated_photo_ids(
    photo_plan: PhotoSyncPlan,
    current_by_id: Mapping[int, PhotoEntry],
    current_by_hash: Mapping[str, PhotoEntry],
) -> set[int]:
    updated_ids: set[int] = set()
    for item in photo_plan.photos_to_update:
        image_id = int(item.image_id or 0)
        if image_id > 0 and image_id in current_by_id:
            updated_ids.add(image_id)
            continue
        if item.visual_hash:
            photo = current_by_hash.get(item.visual_hash)
            if photo is not None:
                updated_ids.add(photo.image_id)
    return updated_ids


def _collect_new_photo_ids(
    merged_db: PhotoDB,
    existing_ids: set[int],
) -> set[int]:
    return {
        photo.image_id
        for photo in merged_db.photos.values()
        if photo.image_id not in existing_ids
    }


def _build_incremental_change_set(
    photo_plan: PhotoSyncPlan,
    pre_merge_by_id: Mapping[int, PhotoEntry],
    merged_db: PhotoDB,
) -> _PhotoSyncChangeSet:
    existing_ids = set(pre_merge_by_id)
    current_by_id = {photo.image_id: photo for photo in merged_db.photos.values()}
    current_by_hash = {
        photo.visual_hash: photo
        for photo in merged_db.photos.values()
        if photo.visual_hash
    }

    removed_ids = _collect_removed_photo_ids(photo_plan)
    updated_ids = _collect_updated_photo_ids(photo_plan, current_by_id, current_by_hash)
    new_ids = _collect_new_photo_ids(merged_db, existing_ids)
    touch_ids = sorted(new_ids | updated_ids)

    return _PhotoSyncChangeSet(
        removed_ids=removed_ids,
        updated_ids=updated_ids,
        new_ids=new_ids,
        touch_ids=touch_ids,
    )


def _remove_deleted_full_res_files(
    ipod_path: Path,
    pre_merge_by_id: Mapping[int, PhotoEntry],
    removed_ids: set[int],
    before_device_mutation: Callable[[], None] | None = None,
) -> None:
    for image_id in removed_ids:
        prev = pre_merge_by_id.get(image_id)
        if prev is None or not prev.full_res_path:
            continue
        full_res_path = _device_photo_path(ipod_path, prev.full_res_path)
        if before_device_mutation is not None:
            before_device_mutation()
        durable_unlink(full_res_path, missing_ok=True)


def _initialize_thumb_file_sizes(
    ipod_path: Path,
    formats: Mapping[int, ArtworkFormat],
    baseline_sizes: Mapping[int, int],
    before_device_mutation: Callable[[], None] | None = None,
) -> dict[int, int]:
    thumbs_dir = _photo_thumbs_dir(ipod_path)
    if before_device_mutation is not None:
        before_device_mutation()
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    file_sizes = {int(fmt_id): int(size) for fmt_id, size in baseline_sizes.items()}
    for fmt_id in formats:
        filename = f"F{fmt_id}_1.ithmb"
        path = thumbs_dir / filename
        try:
            disk_size = int(path.stat().st_size)
        except OSError:
            disk_size = 0
        file_sizes[fmt_id] = max(int(file_sizes.get(fmt_id, 0)), disk_size)
    return file_sizes


def _load_sync_image_for_photo(
    photo: PhotoEntry,
    prev: PhotoEntry | None,
    ipod_path: Path,
    *,
    is_new: bool,
) -> Image.Image:
    if is_new:
        if not photo.source_path or not Path(photo.source_path).exists():
            raise RuntimeError(
                f"Could not load source image for new photo '{photo.display_name or photo.image_id}'",
            )
        try:
            img = _load_pil_still_image(photo.source_path)
        except _PIL_LOAD_ERRORS as err:
            raise RuntimeError(
                f"Could not load source image for new photo "
                f"'{photo.display_name or photo.image_id}': "
                f"{_describe_image_load_error(photo.source_path, err)}",
            ) from err
        timestamp = _source_timestamp(photo.source_path)
        photo.created_at = timestamp
        photo.digitized_at = timestamp
        photo.visual_hash = _image_visual_hash(img)
        return img

    if prev is not None:
        img = load_photo_preview(prev, ipod_path)
        if img is not None:
            photo.created_at = prev.created_at
            photo.digitized_at = prev.digitized_at
            return img

    raise RuntimeError(
        f"Could not load on-device image for updated photo '{photo.display_name or photo.image_id}'",
    )


def _write_full_res_for_touched_photo(
    ipod_path: Path,
    photo: PhotoEntry,
    prev: PhotoEntry | None,
    img: Image.Image,
    formats: Mapping[int, ArtworkFormat],
    *,
    rotate_tall_photos: bool,
    before_device_mutation: Callable[[], None] | None = None,
) -> None:
    if prev is not None and prev.full_res_path:
        photo.full_res_path = prev.full_res_path
    elif not photo.full_res_path:
        photo.full_res_path = _full_res_rel_path_for_entry(photo)

    full_res_target = _device_photo_path(ipod_path, photo.full_res_path)
    if before_device_mutation is not None:
        before_device_mutation()
    full_res_target.parent.mkdir(parents=True, exist_ok=True)

    full_res_image = _prepare_full_res_photo(img, formats, rotate_tall_photos)
    _replace_jpeg_durably(
        full_res_target,
        full_res_image,
        before_device_mutation=before_device_mutation,
    )

    photo.full_res_size = full_res_target.stat().st_size
    if not photo.original_size:
        photo.original_size = photo.full_res_size


def _append_touched_photo_thumbs(
    ipod_path: Path,
    photo: PhotoEntry,
    img: Image.Image,
    formats: Mapping[int, ArtworkFormat],
    file_sizes: dict[int, int],
    *,
    rotate_tall_photos: bool,
    fit_thumbnails: bool,
    before_device_mutation: Callable[[], None] | None = None,
) -> None:
    encoded = _encode_photo_for_formats(
        img,
        formats,
        rotate_tall_photos=rotate_tall_photos,
        fit_thumbnails=fit_thumbnails,
    )

    photo.thumbs.clear()
    for fmt_id, info in encoded.items():
        filename = info["filename"]
        offset = int(file_sizes.get(fmt_id, 0))
        if before_device_mutation is not None:
            before_device_mutation()
        thumb_path = _device_photo_thumb_path(ipod_path, filename)
        thumb_existed = thumb_path.exists()
        with open(thumb_path, "ab") as f:
            f.write(info["data"])
            flush_written_file(f)
        if not thumb_existed:
            flush_parent_directory(thumb_path)
        file_sizes[fmt_id] = offset + len(info["data"])

        photo.thumbs[fmt_id] = PhotoThumbRef(
            format_id=fmt_id,
            offset=offset,
            size=int(info["size"]),
            width=int(info["width"]),
            height=int(info["height"]),
            hpad=int(info["hpad"]),
            vpad=int(info["vpad"]),
            filename=filename,
        )


def _apply_touched_photo_changes(
    ipod_path: Path,
    merged_db: PhotoDB,
    pre_merge_by_id: Mapping[int, PhotoEntry],
    change_set: _PhotoSyncChangeSet,
    formats: Mapping[int, ArtworkFormat],
    file_sizes: dict[int, int],
    *,
    rotate_tall_photos: bool,
    fit_thumbnails: bool,
    progress_callback: Callable[[str, int, int, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    before_device_mutation: Callable[[], None] | None = None,
) -> None:
    current_by_id = {photo.image_id: photo for photo in merged_db.photos.values()}

    total = len(change_set.touch_ids)
    for index, image_id in enumerate(change_set.touch_ids, start=1):
        if is_cancelled and is_cancelled():
            return

        photo = current_by_id.get(image_id)
        if photo is None:
            continue

        if progress_callback:
            progress_callback("photo_prepare", index, total, photo.display_name or f"Photo {photo.image_id}")

        prev = pre_merge_by_id.get(image_id)
        img = _load_sync_image_for_photo(
            photo,
            prev,
            ipod_path,
            is_new=(image_id in change_set.new_ids),
        )

        _write_full_res_for_touched_photo(
            ipod_path,
            photo,
            prev,
            img,
            formats,
            rotate_tall_photos=rotate_tall_photos,
            before_device_mutation=before_device_mutation,
        )
        _append_touched_photo_thumbs(
            ipod_path,
            photo,
            img,
            formats,
            file_sizes,
            rotate_tall_photos=rotate_tall_photos,
            fit_thumbnails=fit_thumbnails,
            before_device_mutation=before_device_mutation,
        )

        if progress_callback:
            progress_callback("photo_write", index, total, photo.display_name or f"Photo {photo.image_id}")


def _compact_photo_thumb_payloads(
    ipod_path: Path,
    photodb: PhotoDB,
    progress_callback: Callable[[str, int, int, str], None] | None = None,
    before_device_mutation: Callable[[], None] | None = None,
) -> None:
    """Compact ithmb payloads by copying only currently referenced thumb blocks."""
    thumbs_dir = _photo_thumbs_dir(ipod_path)
    if before_device_mutation is not None:
        before_device_mutation()
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    ordered_photos = sorted(photodb.photos.values(), key=lambda p: p.image_id)
    refs_by_format: dict[int, list[PhotoThumbRef]] = {}
    for photo in ordered_photos:
        for fmt_id, thumb in sorted(photo.thumbs.items()):
            refs_by_format.setdefault(fmt_id, []).append(thumb)

    live_files: set[str] = set()
    new_file_sizes: dict[int, int] = {}
    total_formats = len(refs_by_format)

    for index, (fmt_id, refs) in enumerate(sorted(refs_by_format.items()), start=1):
        if not refs:
            continue
        target_filename = f"F{fmt_id}_1.ithmb"
        target_path = thumbs_dir / target_filename
        live_files.add(target_filename)

        if progress_callback:
            progress_callback("photo_compact", index, total_formats, target_filename)

        offset_map: dict[tuple[str, int, int], int] = {}
        src_handles: dict[str, BinaryIO] = {}
        tmp_path: Path | None = None
        try:
            if before_device_mutation is not None:
                before_device_mutation()
            tmp_path, temp_file = open_unique_sibling_temp(target_path, mode="wb")
            try:
                with temp_file as dst:
                    for ref in refs:
                        source_filename = ref.filename or target_filename
                        key = (source_filename, int(ref.offset), int(ref.size))
                        existing_offset = offset_map.get(key)
                        if existing_offset is not None:
                            ref.offset = existing_offset
                            ref.filename = target_filename
                            continue

                        src = src_handles.get(source_filename)
                        if src is None:
                            src_path = _device_photo_thumb_path(ipod_path, source_filename)
                            src = open(src_path, "rb")
                            src_handles[source_filename] = src

                        src.seek(int(ref.offset))
                        payload = src.read(int(ref.size))
                        if len(payload) != int(ref.size):
                            raise RuntimeError(
                                f"Could not compact photo thumbs for {target_filename}: "
                                f"short read at offset {ref.offset} (size {ref.size})",
                            )

                        new_offset = int(dst.tell())
                        dst.write(payload)
                        offset_map[key] = new_offset
                        ref.offset = new_offset
                        ref.filename = target_filename
                    flush_written_file(dst)
            finally:
                for src in src_handles.values():
                    try:
                        src.close()
                    except OSError:
                        pass
            if before_device_mutation is not None:
                before_device_mutation()
            durable_replace(tmp_path, target_path)
        except Exception:
            _cleanup_device_temp(
                tmp_path,
                before_device_mutation=before_device_mutation,
            )
            raise
        new_file_sizes[fmt_id] = int(target_path.stat().st_size)

    for stale in thumbs_dir.glob("F*_*.ithmb"):
        if stale.name not in live_files:
            safe_stale = _safe_enumerated_photo_path(
                ipod_path,
                stale,
                allowed_subtree=_PHOTO_THUMBS_RELATIVE,
            )
            if before_device_mutation is not None:
                before_device_mutation()
            durable_unlink(safe_stale, missing_ok=True)

    photodb.file_sizes = new_file_sizes


def _apply_photo_sync_plan_incremental(
    ipod_path: Path,
    current_db: PhotoDB,
    photo_plan: PhotoSyncPlan,
    progress_callback: Callable[[str, int, int, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    sync_settings: dict[str, bool] | None = None,
    before_device_mutation: Callable[[], None] | None = None,
    filesystem_profile: FilesystemProfile | None = None,
) -> PhotoDB:
    """Apply photo sync plan incrementally in three phases.

    Phase 1: merge the logical plan and classify changes.
    Phase 2: apply payload writes only for touched photos.
    Phase 3: compact stale payload blocks (removes/updates) and rewrite metadata.
    """
    pre_merge_by_id = {photo.image_id: photo for photo in current_db.photos.values()}
    current_db = merge_photo_sync_plan(current_db, photo_plan)
    change_set = _build_incremental_change_set(photo_plan, pre_merge_by_id, current_db)

    formats: Mapping[int, ArtworkFormat] = {}
    if change_set.touch_ids:
        formats = _photo_formats_for_current_device(ipod_path)
        if not formats:
            raise RuntimeError("No photo formats available for the current device")
    _preflight_photo_ithmb_sizes(
        ipod_path,
        current_db,
        change_set,
        formats,
        filesystem_profile,
    )

    _remove_deleted_full_res_files(
        ipod_path,
        pre_merge_by_id,
        change_set.removed_ids,
        before_device_mutation=before_device_mutation,
    )

    sync_settings = _current_photo_sync_settings(sync_settings)

    # Albums/membership/removes-only plans can skip re-encoding entirely.
    if not change_set.touch_ids:
        if change_set.removed_ids:
            _compact_photo_thumb_payloads(
                ipod_path,
                current_db,
                progress_callback=progress_callback,
                before_device_mutation=before_device_mutation,
            )
        write_photo_db_metadata_only(
            ipod_path,
            current_db,
            sync_settings=sync_settings,
            before_device_mutation=before_device_mutation,
        )
        return current_db

    rotate_tall_photos = bool(sync_settings.get("rotate_tall_photos_for_device", False))
    fit_thumbnails = bool(sync_settings.get("fit_photo_thumbnails", False))
    file_sizes = _initialize_thumb_file_sizes(
        ipod_path,
        formats,
        current_db.file_sizes,
        before_device_mutation=before_device_mutation,
    )
    _apply_touched_photo_changes(
        ipod_path,
        current_db,
        pre_merge_by_id,
        change_set,
        formats,
        file_sizes,
        rotate_tall_photos=rotate_tall_photos,
        fit_thumbnails=fit_thumbnails,
        progress_callback=progress_callback,
        is_cancelled=is_cancelled,
        before_device_mutation=before_device_mutation,
    )

    current_db.file_sizes = file_sizes
    if change_set.removed_ids or change_set.updated_ids:
        _compact_photo_thumb_payloads(
            ipod_path,
            current_db,
            progress_callback=progress_callback,
            before_device_mutation=before_device_mutation,
        )

    write_photo_db_metadata_only(
        ipod_path,
        current_db,
        sync_settings=sync_settings,
        before_device_mutation=before_device_mutation,
    )
    return current_db


def apply_photo_sync_plan(
    ipod_path: str | Path,
    photo_plan: PhotoSyncPlan | None,
    progress_callback: Callable[[str, int, int, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    sync_settings: dict[str, bool] | None = None,
    before_device_mutation: Callable[[], None] | None = None,
    filesystem_profile: FilesystemProfile | None = None,
) -> PhotoDB:
    ipod_path = Path(ipod_path)
    on_disk_db = read_photo_db(ipod_path)
    current_db = copy.deepcopy(
        photo_plan.current_db
        if photo_plan and photo_plan.current_db
        else on_disk_db
    )
    if not photo_plan:
        return current_db

    return _apply_photo_sync_plan_incremental(
        ipod_path,
        current_db,
        photo_plan,
        progress_callback=progress_callback,
        is_cancelled=is_cancelled,
        sync_settings=sync_settings,
        before_device_mutation=before_device_mutation,
        filesystem_profile=filesystem_profile,
    )
