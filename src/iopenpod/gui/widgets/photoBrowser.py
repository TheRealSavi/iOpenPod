from __future__ import annotations

import copy
import os
import re
import shutil
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QCursor, QFont, QImage, QPixmap
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QInputDialog,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from iopenpod.device.artwork import ITHMB_FORMAT_MAP
from iopenpod.device.durability import (
    durable_replace,
    durable_unlink,
    flush_written_file,
    open_unique_sibling_temp,
)
from iopenpod.device.write_guard import DeviceWriteGuard, DeviceWriteSafetyError
from iopenpod.device.write_readiness import (
    inspect_device_write_readiness,
    revalidate_device_write_readiness,
    volume_lock_key,
)
from iopenpod.search import matches_search
from iopenpod.sync import photos as photo_sync
from iopenpod.sync.photos import (
    PhotoDB,
    PhotoEditState,
    PhotoEntry,
    apply_photo_sync_plan,
    build_photo_library_from_device,
    build_photo_sync_plan,
    ensure_photo_visual_hashes,
    load_photo_preview,
    merge_photo_sync_plan,
    resolve_photo_full_res_path,
    write_photo_db_metadata_only,
)

from ..glyphs import glyph_icon
from ..styles import (
    FONT_FAMILY,
    Colors,
    Metrics,
    context_menu_css,
    make_scroll_area,
)
from .browserChrome import (
    BrowserHeroHeader,
    BrowserPane,
    chrome_action_btn_css,
    style_browser_splitter,
)
from .formatters import format_size
from .gridHeaderBar import GridHeaderBar
from .photoViewer import PhotoViewerPane
from .pooledGrid import GridItemModel, PooledGridView
from .sidebarNavButton import SidebarNavButton

if TYPE_CHECKING:
    from iopenpod.application.services import (
        DeviceSessionService,
        LibraryCacheLike,
        LibraryService,
        SettingsService,
    )
    from iopenpod.device.filesystem_profile import FilesystemProfile


PhotoListItem = tuple[int, PhotoEntry]
PhotoTilePayload = tuple[int, int, bytes, tuple[int, int, int] | None]
PhotoExportRequest = tuple[PhotoEntry, str]

_THUMB_DECODE_BATCH_SIZE = 6
_THUMB_PREFETCH_AHEAD = 6
_MAX_THUMB_WORKERS = 2
_EXPORT_FILTERS = "JPEG Image (*.jpg);;PNG Image (*.png);;All Files (*)"
_JPEG_EXTENSIONS = {".jpg", ".jpeg"}
_PNG_EXTENSIONS = {".png"}


def _safe_photo_stem(name: str, fallback: str) -> str:
    stem = Path(name).stem if name else fallback
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", stem).strip(" ._")
    return cleaned or fallback


def _default_export_filename(title: str, image_id: int) -> str:
    stem = _safe_photo_stem(title, f"photo_{image_id:05d}")
    return f"{stem}.jpg"


def _device_full_res_path(ipod_path: str | Path, photo: PhotoEntry) -> Path | None:
    if not photo.full_res_path:
        return None
    path = resolve_photo_full_res_path(ipod_path, photo.full_res_path)
    return path if path.is_file() else None


def _load_still_image(path: str | Path):
    from PIL import Image, ImageOps

    with Image.open(path) as image:
        image.seek(0)
        loaded = image.copy()
    return ImageOps.exif_transpose(loaded)


def _jpeg_ready_image(image):
    from PIL import Image

    if image.mode == "RGB":
        return image
    if image.mode in ("RGBA", "LA") or (
        image.mode == "P" and "transparency" in image.info
    ):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return image.convert("RGB")


def _save_image_as_normal_photo(image, target_path: str | Path) -> Path:
    target = Path(target_path)
    if not target.suffix:
        target = target.with_suffix(".jpg")
    target.parent.mkdir(parents=True, exist_ok=True)
    suffix = target.suffix.lower()
    if suffix in _PNG_EXTENSIONS:
        image.convert("RGBA").save(target, format="PNG")
    else:
        _jpeg_ready_image(image).save(target, format="JPEG", quality=95, optimize=True)
    return target


def _preferred_export_format_id(photo: PhotoEntry) -> int | None:
    if not photo.thumbs:
        return None
    role_priority = {
        "photo_full": 0,
        "photo_large": 1,
        "photo_preview": 2,
        "tv_out": 3,
        "photo_list": 4,
        "photo_thumb": 5,
    }
    return min(
        photo.thumbs,
        key=lambda fmt_id: (
            role_priority.get(
                (lambda fmt: fmt.role if fmt is not None else "")(
                    ITHMB_FORMAT_MAP.get(fmt_id)
                ),
                9,
            ),
            -(
                photo.thumbs[fmt_id].width
                * photo.thumbs[fmt_id].height
            ),
            int(fmt_id),
        ),
    )


def _export_photo_to_path(
    photo: PhotoEntry,
    ipod_path: str | Path,
    target_path: str | Path,
    *,
    format_id: int | None = None,
) -> Path:
    target = Path(target_path)
    if not target.suffix:
        target = target.with_suffix(".jpg")

    full_res_path = _device_full_res_path(ipod_path, photo)
    suffix = target.suffix.lower()
    if full_res_path is not None and suffix in _JPEG_EXTENSIONS:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(full_res_path, target)
        return target

    image = _load_still_image(full_res_path) if full_res_path is not None else None
    if image is None and format_id is not None:
        image = load_photo_preview(photo, ipod_path, format_id=format_id)
    if image is None:
        image = load_photo_preview(photo, ipod_path)
    if image is None:
        raise RuntimeError("Could not decode the selected photo from the iPod.")

    return _save_image_as_normal_photo(image, target)


class _PhotoWriteWorker(QThread):
    finished_ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        ipod_path: str,
        device_photos: PhotoDB,
        action: str,
        *,
        image_id: int | None = None,
        album_name: str = "",
        old_name: str = "",
        new_name: str = "",
        sync_settings: dict[str, bool] | None = None,
        reported_volume_format: str = "",
        expected_volume_identity_key: str = "",
    ):
        super().__init__()
        self._ipod_path = ipod_path
        self._device_photos = copy.deepcopy(device_photos)
        self._action = action
        self._image_id = image_id
        self._album_name = album_name
        self._old_name = old_name
        self._new_name = new_name
        self._sync_settings = sync_settings
        self._reported_volume_format = reported_volume_format
        self._expected_volume_identity_key = expected_volume_identity_key
        self._filesystem_profile: FilesystemProfile | None = None

    def _revalidate_write_readiness(self) -> None:
        profile = self._filesystem_profile
        if profile is None:
            raise DeviceWriteSafetyError("The iPod write session is not active.")
        self._filesystem_profile = revalidate_device_write_readiness(profile)

    def _unlink_device_path(self, path: Path, *, missing_ok: bool = False) -> None:
        self._revalidate_write_readiness()
        durable_unlink(path, missing_ok=missing_ok)

    def _replace_device_path(self, source: Path, target: Path) -> None:
        self._revalidate_write_readiness()
        durable_replace(source, target)

    def _commit_photo_metadata(self, photodb: PhotoDB) -> None:
        self._revalidate_write_readiness()
        write_photo_db_metadata_only(
            self._ipod_path,
            photodb,
            sync_settings=self._sync_settings,
            before_device_mutation=self._revalidate_write_readiness,
        )

    def _restore_metadata_file(self, path: Path, contents: bytes | None) -> None:
        if contents is None:
            self._unlink_device_path(path, missing_ok=True)
            return

        tmp_path: Path | None = None
        try:
            self._revalidate_write_readiness()
            tmp_path, temp_file = open_unique_sibling_temp(path, mode="wb")
            with temp_file as file:
                file.write(contents)
                flush_written_file(file)
            self._replace_device_path(tmp_path, path)
        except Exception:
            if tmp_path is not None:
                try:
                    self._unlink_device_path(tmp_path, missing_ok=True)
                except Exception:
                    pass
            raise

    def _delete_photo_fast_path(self) -> PhotoDB:
        if self._image_id is None:
            raise RuntimeError("No device photo selected.")

        photodb = copy.deepcopy(self._device_photos)
        photo = photodb.photos.pop(self._image_id, None)
        if photo is None:
            raise RuntimeError("Selected photo could not be resolved on the iPod.")

        for album in photodb.albums:
            album.members = [mid for mid in album.members if mid != self._image_id]

        if photo.full_res_path:
            full_res_path = resolve_photo_full_res_path(
                self._ipod_path,
                photo.full_res_path,
            )
            self._unlink_device_path(full_res_path, missing_ok=True)

        self._commit_photo_metadata(photodb)
        return photodb

    def _rename_photo_fast_path(self) -> PhotoDB:
        if self._image_id is None:
            raise RuntimeError("No device photo selected.")

        new_stem = _safe_photo_stem(self._new_name, "")
        if not new_stem:
            raise RuntimeError("Photo name cannot be empty.")

        photodb = copy.deepcopy(self._device_photos)
        photo = photodb.photos.get(self._image_id)
        if photo is None:
            raise RuntimeError("Selected photo could not be resolved on the iPod.")

        old_path: Path | None = None
        new_path: Path | None = None
        if photo.full_res_path:
            old_path = resolve_photo_full_res_path(
                self._ipod_path,
                photo.full_res_path,
            )
            new_path = old_path.with_name(f"{new_stem}{old_path.suffix}")
            same_location = os.path.normcase(str(new_path)) == os.path.normcase(str(old_path))
            if not same_location and new_path.exists():
                raise RuntimeError(f"A photo named '{new_path.name}' already exists.")
            if old_path.exists() and old_path.name != new_path.name:
                rename_source = old_path
                rename_temp: Path | None = None
                if same_location:
                    self._revalidate_write_readiness()
                    rename_temp, temp_file = open_unique_sibling_temp(
                        old_path,
                        mode="wb",
                    )
                    with temp_file as file:
                        flush_written_file(file)
                    try:
                        self._replace_device_path(old_path, rename_temp)
                    except Exception:
                        self._unlink_device_path(rename_temp, missing_ok=True)
                        raise
                    rename_source = rename_temp
                try:
                    self._replace_device_path(rename_source, new_path)
                except Exception:
                    if rename_temp is not None and rename_temp.exists():
                        self._replace_device_path(rename_temp, old_path)
                    raise
                photo.full_res_path = Path(
                    photo.full_res_path
                ).with_name(new_path.name).as_posix()

        photo.display_name = f"{new_stem}{new_path.suffix if new_path else ''}"
        metadata_paths = (
            photo_sync._photo_db_path(self._ipod_path),
            photo_sync._photo_mapping_path(self._ipod_path),
        )
        metadata_backups = {
            path: path.read_bytes() if path.exists() else None
            for path in metadata_paths
        }
        try:
            self._commit_photo_metadata(photodb)
        except Exception:
            for path, contents in metadata_backups.items():
                self._restore_metadata_file(path, contents)
            if old_path is not None and new_path is not None and new_path.exists():
                self._replace_device_path(new_path, old_path)
            raise
        return photodb

    def _resolve_photo_for_membership_action(self) -> PhotoEntry:
        if self._image_id is None:
            raise RuntimeError("No device photo selected.")
        photo = self._device_photos.photos.get(self._image_id)
        if photo is None or not photo.visual_hash:
            raise RuntimeError("Selected photo could not be resolved on the iPod.")
        return photo

    def _build_edits_for_action(self) -> PhotoEditState:
        edits = PhotoEditState()
        if self._action == "create_album":
            edits.created_albums.add(self._album_name)
            return edits
        if self._action == "rename_album":
            edits.renamed_albums[self._old_name] = self._new_name
            return edits
        if self._action == "delete_album":
            edits.deleted_albums.add(self._album_name)
            return edits

        photo = self._resolve_photo_for_membership_action()
        if self._action == "add_to_album":
            edits.membership_adds.add((photo.visual_hash, self._album_name))
            return edits
        if self._action == "remove_from_album":
            edits.membership_removals.add((photo.visual_hash, self._album_name))
            return edits

        raise RuntimeError(f"Unknown photo action: {self._action}")

    def _apply_edit_state(self, edits: PhotoEditState) -> PhotoDB:
        desired_library = build_photo_library_from_device(self._device_photos)
        plan = build_photo_sync_plan(
            desired_library,
            self._device_photos,
            edits,
            ipod_path=self._ipod_path,
            sync_settings=self._sync_settings,
        )

        needs_payload_writes = bool(
            plan.photos_to_add or plan.photos_to_remove or plan.photos_to_update
        )
        if needs_payload_writes:
            self._revalidate_write_readiness()
            return apply_photo_sync_plan(
                self._ipod_path,
                plan,
                sync_settings=self._sync_settings,
                before_device_mutation=self._revalidate_write_readiness,
                filesystem_profile=self._filesystem_profile,
            )

        photodb = merge_photo_sync_plan(copy.deepcopy(self._device_photos), plan)
        self._commit_photo_metadata(photodb)
        return photodb

    def _run_guarded(self) -> PhotoDB:
        profile = inspect_device_write_readiness(
            self._ipod_path,
            reported_volume_format=self._reported_volume_format,
        )
        lock_key = volume_lock_key(profile)
        if (
            self._expected_volume_identity_key
            and lock_key != self._expected_volume_identity_key
        ):
            raise DeviceWriteSafetyError(
                "The mounted iPod volume changed since it was selected. "
                "iOpenPod stopped before editing photos. Reconnect and reload the iPod."
            )

        with DeviceWriteGuard(self._ipod_path, volume_key=lock_key):
            self._filesystem_profile = profile
            try:
                if self._action == "delete_photo":
                    return self._delete_photo_fast_path()
                if self._action == "rename_photo":
                    return self._rename_photo_fast_path()

                ensure_photo_visual_hashes(self._device_photos, self._ipod_path)
                edits = self._build_edits_for_action()
                return self._apply_edit_state(edits)
            finally:
                self._filesystem_profile = None

    def run(self) -> None:
        try:
            photodb = self._run_guarded()
            self.finished_ok.emit(photodb)
        except Exception as exc:
            self.failed.emit(str(exc))


class _PhotoExportWorker(QThread):
    finished_ok = pyqtSignal(int, str)
    failed = pyqtSignal(str)

    def __init__(
        self,
        ipod_path: str,
        exports: list[PhotoExportRequest],
        destination_label: str,
    ):
        super().__init__()
        self._ipod_path = ipod_path
        self._exports = [
            (copy.deepcopy(photo), target_path)
            for photo, target_path in exports
        ]
        self._destination_label = destination_label

    def run(self) -> None:
        try:
            if not self._exports:
                raise RuntimeError("No photos were selected for export.")
            for photo, target_path in self._exports:
                _export_photo_to_path(
                    photo,
                    self._ipod_path,
                    target_path,
                    format_id=_preferred_export_format_id(photo),
                )
            self.finished_ok.emit(len(self._exports), self._destination_label)
        except Exception as exc:
            self.failed.emit(str(exc))


class PhotoBrowserWidget(QFrame):
    def __init__(
        self,
        settings_service: SettingsService,
        device_sessions: DeviceSessionService,
        libraries: LibraryService,
        parent=None,
    ):
        super().__init__(parent)
        self._settings_service = settings_service
        self._device_sessions = device_sessions
        self._library_service = libraries
        self._library_cache: LibraryCacheLike = libraries.cache()
        self._current_album = ""
        self._device_db: PhotoDB | None = None
        self._filtered_items: list[PhotoListItem] = []
        self._current_preview_photo: PhotoEntry | None = None
        self._current_format_ids: list[int] = []
        self._bound_cache = None
        self._search_query = ""
        self._sort_key = "title"
        self._sort_reverse = False
        self._album_buttons: dict[str, SidebarNavButton] = {}
        self._selected_album_btn: SidebarNavButton | None = None
        self._write_worker: _PhotoWriteWorker | None = None
        self._export_worker: _PhotoExportWorker | None = None
        self._tile_pixmap_cache: dict[int, QPixmap] = {}
        self._tile_color_cache: dict[int, tuple[int, int, int] | None] = {}
        self._preview_pixmap_cache: dict[tuple[int, int], QPixmap] = {}
        self._preview_pending: set[tuple[int, int]] = set()
        self._cache_marker: tuple[str, int, int] | None = None
        self._thumb_queue: deque[tuple[int, PhotoEntry, int | None, int]] = deque()
        self._queued_thumb_ids: set[int] = set()
        self._thumb_in_flight_ids: set[int] = set()
        self._thumb_workers_in_flight = 0
        self._grid_load_token = 0
        self._grid_device_path = ""
        self._pending_grid_device_path = ""
        self._current_preview_format_id: int | None = None
        self._preview_request_token = 0
        self._reload_timer = QTimer(self)
        self._reload_timer.setSingleShot(True)
        self._reload_timer.timeout.connect(self._reload_now)
        self._grid_reload_timer = QTimer(self)
        self._grid_reload_timer.setSingleShot(True)
        self._grid_reload_timer.timeout.connect(self._run_grid_reload)
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.timeout.connect(self._process_thumb_batch)
        self._build_ui()
        self.bind_cache(self._library_cache)

    def _current_device_path(self) -> str:
        return self._device_sessions.current_session().device_path or ""

    def _photo_sync_settings(self) -> dict[str, bool]:
        settings = self._settings_service.get_effective_settings()
        return {
            "rotate_tall_photos_for_device": settings.rotate_tall_photos_for_device,
            "fit_photo_thumbnails": settings.fit_photo_thumbnails,
        }

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = BrowserHeroHeader("Photos", self)

        self.new_album_btn = QPushButton("New Album")
        self.new_album_btn.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self.new_album_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.new_album_btn.setStyleSheet(chrome_action_btn_css())
        new_album_icon = glyph_icon("plus", 14, Colors.TEXT_PRIMARY)
        if new_album_icon is not None:
            self.new_album_btn.setIcon(new_album_icon)
        header.actions_layout.addWidget(self.new_album_btn)
        header.actions_layout.addStretch()

        root.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        style_browser_splitter(splitter)
        root.addWidget(splitter, 1)

        self._album_panel = BrowserPane(
            "Albums",
            min_width=220,
            body_margins=(8, 2, 8, 8),
            parent=splitter,
        )

        self._album_scroll = make_scroll_area()
        self._album_inner = QWidget()
        self._album_inner.setStyleSheet("background: transparent; border: none;")
        self._album_inner_layout = QVBoxLayout(self._album_inner)
        self._album_inner_layout.setContentsMargins(0, 0, 0, 0)
        self._album_inner_layout.setSpacing(2)
        self._album_inner_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._album_scroll.setWidget(self._album_inner)
        self._album_panel.addWidget(self._album_scroll, 1)
        splitter.addWidget(self._album_panel)

        self._grid_panel = BrowserPane("", parent=splitter)

        self.grid_header = GridHeaderBar()
        self.grid_header.setCategory("Photos")
        self.grid_header.sort_changed.connect(self._on_sort_changed)
        self.grid_header.search_changed.connect(self._on_search_changed)
        self._grid_panel.addWidget(self.grid_header)

        self.photo_scroll = make_scroll_area()
        self.photo_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.photo_grid = PooledGridView(settings_service=self._settings_service)
        self.photo_scroll.setWidget(self.photo_grid)
        self.photo_grid.attachScrollArea(self.photo_scroll)
        self._grid_panel.addWidget(self.photo_scroll, 1)
        splitter.addWidget(self._grid_panel)

        self.viewer = PhotoViewerPane(
            heading="",
            empty_title="No photo selected",
            empty_summary="Select a photo to inspect its preview and album details.",
            parent=splitter,
        )
        viewer_actions = self.viewer.configureActionRow([
            ("export_photo", "Export", "download", False),
            ("add_to_album", "Add to Album", "plus", False),
            ("remove_from_album", "Remove from Album", "minus", False),
            ("delete_photo", "Delete Photo", "trash", True),
        ])
        self.export_photo_btn = viewer_actions["export_photo"]
        self.add_to_album_btn = viewer_actions["add_to_album"]
        self.remove_from_album_btn = viewer_actions["remove_from_album"]
        self.delete_photo_btn = viewer_actions["delete_photo"]
        splitter.addWidget(self.viewer)
        splitter.setSizes([240, 760, 340])

        self.photo_grid.currentIndexChanged.connect(self._on_photo_changed)
        self.photo_grid.contextRequested.connect(self._on_photo_context_requested)
        self.photo_grid.visibleIndicesChanged.connect(
            self._on_visible_photo_indices_changed
        )
        self.viewer.variantSelected.connect(self._on_variant_selected)
        self.new_album_btn.clicked.connect(self._create_album)
        self.export_photo_btn.clicked.connect(self._export_current_photo)
        self.add_to_album_btn.clicked.connect(self._add_to_album)
        self.remove_from_album_btn.clicked.connect(self._remove_from_album)
        self.delete_photo_btn.clicked.connect(self._delete_photo)
        self._update_action_states()

    def bind_cache(self, cache):
        if self._bound_cache is cache:
            return
        cache.data_ready.connect(self.reload)
        cache.photos_changed.connect(self.reload)
        self._bound_cache = cache

    def refresh_artwork_appearance(self) -> None:
        self.photo_grid.refresh_artwork_appearance()

    def clear(self):
        self._reload_timer.stop()
        self._grid_reload_timer.stop()
        self._thumb_timer.stop()
        self._clear_album_sidebar()
        self.photo_grid.clearGrid()
        self._current_preview_photo = None
        self._current_preview_format_id = None
        self._current_format_ids = []
        self.viewer.clearPreview()
        self._filtered_items.clear()
        self._thumb_queue.clear()
        self._queued_thumb_ids.clear()
        self._thumb_in_flight_ids.clear()
        self._preview_pending.clear()
        self._thumb_workers_in_flight = 0
        self._grid_load_token += 1
        self._preview_request_token += 1
        self._tile_pixmap_cache.clear()
        self._tile_color_cache.clear()
        self._preview_pixmap_cache.clear()
        self._cache_marker = None
        self._update_action_states()

    def reload(self):
        self._reload_timer.start(0)

    def _reload_now(self):
        cache = self._library_cache
        photodb = cache.get_photo_db() or PhotoDB()
        self._device_db = photodb
        device_path = self._current_device_path()

        marker = (device_path, id(photodb), len(photodb.photos))
        if marker != self._cache_marker:
            self._tile_pixmap_cache.clear()
            self._tile_color_cache.clear()
            self._preview_pixmap_cache.clear()
            self._preview_pending.clear()
            self._cache_marker = marker

        album_names = self._album_names()
        target = self._current_album if self._current_album and self._current_album in album_names else "All Photos"
        self._rebuild_album_sidebar(album_names)
        self._current_album = target
        self._highlight_album_button(target)

        self.grid_header.setCategory("Photos")
        self._schedule_grid_reload(device_path)

    def _album_names(self) -> list[str]:
        if self._device_db is None:
            return []
        return sorted(album.name for album in self._device_db.albums if album.album_type != 1)

    def _all_items(self) -> list[PhotoListItem]:
        if self._device_db is None:
            return []
        return [(int(photo.image_id), photo) for photo in self._device_db.photos.values()]

    def _on_search_changed(self, query: str):
        self._search_query = query.strip()
        self._schedule_grid_reload(self._current_device_path())

    def _on_sort_changed(self, key: str, reverse: bool):
        self._sort_key = key
        self._sort_reverse = reverse
        self._schedule_grid_reload(self._current_device_path())

    def _matches_search(self, photo: PhotoEntry) -> bool:
        if not self._search_query:
            return True
        parts = [
            self._device_photo_title(photo),
            str(photo.image_id),
            photo.full_res_path,
            " ".join(str(format_id) for format_id in self._photo_format_ids(photo)),
            " ".join(sorted(name for name in getattr(photo, "album_names", set()) if name)),
        ]
        haystack = " ".join(part for part in parts if part)
        return matches_search(self._search_query, haystack)

    def _sort_items(
        self,
        items: list[PhotoListItem],
    ) -> list[PhotoListItem]:
        if self._sort_key == "size":
            key_fn = self._size_sort_key
        elif self._sort_key == "album_count":
            key_fn = self._album_count_sort_key
        else:
            key_fn = self._title_sort_key
        return sorted(items, key=key_fn, reverse=self._sort_reverse)

    def _size_sort_key(self, item: PhotoListItem) -> tuple[int, str]:
        photo = item[1]
        return self._device_storage_size(photo), self._device_photo_title(photo).lower()

    def _album_count_sort_key(self, item: PhotoListItem) -> tuple[int, str]:
        photo = item[1]
        return len(getattr(photo, "album_names", set())), self._device_photo_title(photo).lower()

    def _title_sort_key(self, item: PhotoListItem) -> tuple[str, int]:
        photo = item[1]
        return self._device_photo_title(photo).lower(), self._device_storage_size(photo)

    def _photo_subtitle(self, photo: PhotoEntry) -> str:
        album_names = sorted(name for name in getattr(photo, "album_names", set()) if name)
        if not album_names:
            return "All Photos"
        if len(album_names) <= 2:
            return ", ".join(album_names)
        return f"{album_names[0]}, {album_names[1]} +{len(album_names) - 2} more"

    def _device_photo_title(self, photo: PhotoEntry) -> str:
        if photo.display_name:
            display_stem = Path(photo.display_name).stem
            if display_stem:
                return display_stem
        if photo.full_res_path:
            stem = Path(photo.full_res_path).stem
            image_suffix = f"_{photo.image_id:05d}"
            if stem.endswith(image_suffix):
                stem = stem[:-len(image_suffix)] or stem
            if stem:
                return stem
            filename = Path(photo.full_res_path).name
            if filename:
                return filename
        return f"Photo {photo.image_id}"

    def _photo_format_ids(self, photo: PhotoEntry) -> list[int]:
        return sorted(
            photo.thumbs,
            key=lambda fmt_id: (
                -(photo.thumbs[fmt_id].width * photo.thumbs[fmt_id].height),
                fmt_id,
            ),
        )

    def _default_preview_format_id(self, format_ids: list[int]) -> int | None:
        for format_id in format_ids:
            fmt = ITHMB_FORMAT_MAP.get(format_id)
            if fmt is not None and fmt.role == "photo_full":
                return format_id
        return format_ids[0] if format_ids else None

    def _default_tile_format_id(self, photo: PhotoEntry) -> int | None:
        format_ids = self._photo_format_ids(photo)
        if not format_ids:
            return None

        role_priority = {
            "photo_thumb": 0,
            "photo_list": 1,
            "photo_preview": 2,
            "photo_large": 3,
            "photo_full": 4,
            "tv_out": 5,
        }

        return min(
            format_ids,
            key=lambda fmt_id: (
                role_priority.get((lambda fmt: fmt.role if fmt is not None else "")(ITHMB_FORMAT_MAP.get(fmt_id)), 9),
                int(fmt_id),
            ),
        )

    def _device_storage_size(self, photo: PhotoEntry) -> int:
        total = max(0, int(getattr(photo, "full_res_size", 0) or 0))
        total += sum(max(0, int(ref.size)) for ref in photo.thumbs.values())
        return total

    @staticmethod
    def _preview_cache_key(photo: PhotoEntry, format_id: int | None) -> tuple[int, int]:
        return photo.image_id, int(format_id) if format_id is not None else -1

    def _preview_pixmap(self, photo: PhotoEntry, *, format_id: int | None = None) -> QPixmap:
        cache_key = self._preview_cache_key(photo, format_id)
        return self._preview_pixmap_cache.get(cache_key, QPixmap())

    @staticmethod
    def _pixmap_from_rgba_bytes(width: int, height: int, rgba: bytes) -> QPixmap:
        qimg = QImage(rgba, width, height, width * 4, QImage.Format.Format_RGBA8888)
        return QPixmap.fromImage(qimg.copy())

    @staticmethod
    def _dominant_color_from_image(image) -> tuple[int, int, int] | None:
        try:
            from ..imgMaker import get_artwork_colors

            dominant_color, _album_colors = get_artwork_colors(image.convert("RGBA"))
            return dominant_color
        except Exception:
            try:
                pixel = cast(
                    tuple[int, int, int],
                    image.convert("RGB").resize((1, 1)).getpixel((0, 0)),
                )
                return int(pixel[0]), int(pixel[1]), int(pixel[2])
            except Exception:
                return None

    @staticmethod
    def _encode_loaded_image(
        image,
        *,
        thumbnail_size: tuple[int, int] | None = None,
    ) -> tuple[int, int, bytes] | None:
        if image is None:
            return None
        if thumbnail_size is not None:
            image.thumbnail(thumbnail_size)
        image = image.convert("RGBA")
        return image.width, image.height, image.tobytes("raw", "RGBA")

    @staticmethod
    def _encode_loaded_tile_image(
        image,
        *,
        thumbnail_size: tuple[int, int],
    ) -> PhotoTilePayload | None:
        if image is None:
            return None
        image.thumbnail(thumbnail_size)
        image = image.convert("RGBA")
        dominant_color = PhotoBrowserWidget._dominant_color_from_image(image)
        return image.width, image.height, image.tobytes("raw", "RGBA"), dominant_color

    @staticmethod
    def _load_thumb_batch(
        requests: list[tuple[int, PhotoEntry, int | None]],
        device_path: str,
    ) -> dict[int, PhotoTilePayload | None]:
        results: dict[int, PhotoTilePayload | None] = {}
        for photo_id, photo, format_id in requests:
            try:
                image = load_photo_preview(
                    photo,
                    device_path,
                    format_id=format_id,
                )
                if image is None:
                    image = load_photo_preview(photo, device_path)
                results[photo_id] = PhotoBrowserWidget._encode_loaded_tile_image(
                    image,
                    thumbnail_size=(132, 132),
                )
            except Exception:
                results[photo_id] = None
        return results

    @staticmethod
    def _load_preview_batch(
        requests: list[tuple[tuple[int, int], PhotoEntry, int | None]],
        device_path: str,
    ) -> dict[tuple[int, int], tuple[int, int, bytes] | None]:
        results: dict[tuple[int, int], tuple[int, int, bytes] | None] = {}
        for cache_key, photo, format_id in requests:
            try:
                image = load_photo_preview(
                    photo,
                    device_path,
                    format_id=format_id,
                )
                results[cache_key] = PhotoBrowserWidget._encode_loaded_image(image)
            except Exception:
                results[cache_key] = None
        return results

    def _format_usage_label(self, role: str, description: str) -> str:
        usage_map = {
            "photo_full": "Full-screen viewing on the iPod",
            "photo_preview": "Mid-size preview image",
            "photo_list": "List/grid thumbnail",
            "photo_thumb": "Small thumbnail cache",
            "photo_large": "Large photo cache",
            "tv_out": "TV output / slideshow video-out",
        }
        usage = usage_map.get(role)
        if usage:
            return usage
        if description:
            return description
        return role.replace("_", " ").title() if role else "Unknown device usage"

    def _format_photo_timestamp(self, unix_seconds: int) -> str:
        if not unix_seconds:
            return ""
        try:
            return datetime.fromtimestamp(unix_seconds).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError, OverflowError):
            return str(unix_seconds)

    def _format_meta_sections(
        self,
        photo: PhotoEntry,
        selected_format_id: int | None,
        format_ids: list[int],
    ) -> list[tuple[str, list[tuple[str, str]]]]:
        sections: list[tuple[str, list[tuple[str, str]]]] = []

        album_names = sorted(name for name in getattr(photo, "album_names", set()) if name)
        album_label = ", ".join(album_names) if album_names else "All Photos"
        image_rows = [
            ("Image ID", str(photo.image_id)),
            ("Display Name", photo.display_name or self._device_photo_title(photo)),
            ("Albums", album_label),
            ("Format Variants", str(len(format_ids))),
            ("Created", self._format_photo_timestamp(int(getattr(photo, "created_at", 0) or 0))),
            ("Digitized", self._format_photo_timestamp(int(getattr(photo, "digitized_at", 0) or 0))),
            ("Visual Hash", photo.visual_hash),
            ("Source Path", photo.source_path),
        ]
        sections.append(("Image Record", image_rows))

        thumbs_bytes = sum(max(0, int(ref.size)) for ref in photo.thumbs.values())
        storage_rows = [
            ("Original Size", format_size(photo.original_size) if photo.original_size else ""),
            ("Full-Res Size", format_size(photo.full_res_size) if photo.full_res_size else ""),
            ("Full-Res Path", photo.full_res_path),
            ("Thumbnail Bytes", format_size(thumbs_bytes) if thumbs_bytes else ""),
            (
                "Total On Device",
                format_size(self._device_storage_size(photo)) if self._device_storage_size(photo) else "",
            ),
        ]
        sections.append(("Storage", storage_rows))

        if selected_format_id is not None:
            ref = photo.thumbs.get(selected_format_id)
            fmt = ITHMB_FORMAT_MAP.get(selected_format_id)

            width = ref.width if ref is not None else int(fmt.width) if fmt is not None else 0
            height = ref.height if ref is not None else int(fmt.height) if fmt is not None else 0
            usage = self._format_usage_label(
                fmt.role if fmt is not None else "",
                fmt.description if fmt is not None else "",
            )

            selected_rows = [
                ("Format ID", str(selected_format_id)),
                ("Resolution", f"{width} x {height}" if width and height else ""),
                ("Usage", usage),
                ("Role", fmt.role if fmt is not None else ""),
                ("Pixel Format", fmt.pixel_format if fmt is not None else ""),
                ("Row Bytes", str(fmt.row_bytes) if fmt is not None else ""),
                ("Ithmb File", ref.filename if ref is not None else ""),
                ("Offset", f"{ref.offset:,}" if ref is not None else ""),
                ("Stored Size", format_size(ref.size) if ref is not None and ref.size else ""),
                (
                    "Padding",
                    f"h={ref.hpad}, v={ref.vpad}" if ref is not None and (ref.hpad or ref.vpad) else "",
                ),
                (
                    "Format Table",
                    f"{fmt.width} x {fmt.height}" if fmt is not None else "",
                ),
                (
                    "Device Label",
                    fmt.description if fmt is not None else "",
                ),
            ]
            sections.append(("Selected Variant", selected_rows))

        variant_rows: list[tuple[str, str]] = []
        for format_id in format_ids:
            ref = photo.thumbs.get(format_id)
            fmt = ITHMB_FORMAT_MAP.get(format_id)
            width = ref.width if ref is not None else int(fmt.width) if fmt is not None else 0
            height = ref.height if ref is not None else int(fmt.height) if fmt is not None else 0
            parts: list[str] = []
            if width and height:
                parts.append(f"{width}x{height}")
            if ref is not None and ref.size:
                parts.append(format_size(ref.size))
            if ref is not None and ref.filename:
                parts.append(ref.filename)
            if ref is not None:
                parts.append(f"offset {ref.offset:,}")
            if fmt is not None and fmt.role:
                parts.append(fmt.role)
            variant_rows.append((f"Format {format_id}", " · ".join(parts)))
        sections.append(("All Device Variants", variant_rows))

        return sections

    def _show_photo_preview(self, photo: PhotoEntry, *, selected_format_id: int | None = None) -> None:
        self._current_preview_photo = photo
        format_ids = self._photo_format_ids(photo)
        self._current_format_ids = format_ids
        if selected_format_id is None or selected_format_id not in format_ids:
            selected_format_id = self._default_preview_format_id(format_ids)
        self._current_preview_format_id = selected_format_id

        summary_parts = [self._photo_subtitle(photo)]
        if format_ids:
            summary_parts.append(f"{len(format_ids)} format variant{'s' if len(format_ids) != 1 else ''}")
        total_device_size = self._device_storage_size(photo)
        if total_device_size:
            summary_parts.append(f"{format_size(total_device_size)} on device")

        preview_pixmap = self._preview_pixmap(photo, format_id=selected_format_id)
        self.viewer.setPhoto(
            title=self._device_photo_title(photo),
            pixmap=preview_pixmap,
            summary=" · ".join(part for part in summary_parts if part),
            meta_sections=self._format_meta_sections(photo, selected_format_id, format_ids),
        )
        self.viewer.setVariantIds(
            format_ids,
            selected_id=selected_format_id,
            label="Formats",
        )
        if preview_pixmap.isNull():
            self.viewer.setPreviewPlaceholder("Loading preview...")
            self._request_preview_async(photo, selected_format_id)

    def _schedule_grid_reload(self, device_path: str) -> None:
        self._pending_grid_device_path = device_path
        self._grid_reload_timer.start(40)

    def _run_grid_reload(self) -> None:
        self._reload_grid(self._pending_grid_device_path)

    def _reload_grid(self, device_path: str):
        self._thumb_timer.stop()
        self._thumb_queue.clear()
        self._queued_thumb_ids.clear()
        self._thumb_in_flight_ids.clear()
        self._preview_pending.clear()
        self._thumb_workers_in_flight = 0
        self._grid_load_token += 1
        self._preview_request_token += 1
        load_token = self._grid_load_token
        self._grid_device_path = device_path

        self._filtered_items.clear()
        album_name = "" if self._current_album in ("", "All Photos") else self._current_album

        for key, photo in self._all_items():
            if album_name:
                photo_albums = getattr(photo, "album_names", set())
                if album_name not in photo_albums:
                    continue
            if not self._matches_search(photo):
                continue
            self._filtered_items.append((key, photo))

        self._filtered_items = self._sort_items(self._filtered_items)

        records: list[GridItemModel] = []
        for _index, (photo_id, photo) in enumerate(self._filtered_items):
            cached = self._tile_pixmap_cache.get(photo.image_id)
            records.append(
                GridItemModel(
                    key=photo_id,
                    title=self._device_photo_title(photo),
                    image=cached if cached is not None else QPixmap(),
                    dominant_color=self._tile_color_cache.get(photo.image_id),
                    placeholder_glyph="photo",
                )
            )
        self.photo_grid.setRecords(
            records,
            reset_scroll=True,
            preserve_selection=True,
            fallback_index=0 if records else -1,
        )
        self._queue_visible_thumbnails(load_token)

        self._update_collection_summary()
        if not records:
            self.viewer.clearPreview(
                title="No photos found",
                summary="Try another album or broaden the search.",
            )
            self._update_action_states()

    def _on_visible_photo_indices_changed(self, _indices: object) -> None:
        self._queue_visible_thumbnails(self._grid_load_token)

    def _request_preview_async(self, photo: PhotoEntry, format_id: int | None) -> None:
        device_path = self._current_device_path()
        if not device_path:
            return

        cache_key = self._preview_cache_key(photo, format_id)
        if cache_key in self._preview_pixmap_cache or cache_key in self._preview_pending:
            return

        from iopenpod.application.runtime import ThreadPoolSingleton, Worker

        self._preview_request_token += 1
        request_token = self._preview_request_token
        self._preview_pending.add(cache_key)
        load_token = self._grid_load_token
        worker = Worker(
            self._load_preview_batch,
            [(cache_key, photo, format_id)],
            device_path,
        )
        worker.signals.result.connect(
            lambda result, lid=load_token, rid=request_token: self._on_preview_loaded(
                result, lid, rid
            )
        )
        ThreadPoolSingleton.get_instance().start(worker)

    def _on_preview_loaded(
        self,
        results: dict[tuple[int, int], tuple[int, int, bytes] | None] | None,
        load_token: int,
        request_token: int,
    ) -> None:
        if results is None:
            return

        if (
            load_token != self._grid_load_token
            or request_token != self._preview_request_token
        ):
            for cache_key in results:
                self._preview_pending.discard(cache_key)
            return

        for cache_key, data in results.items():
            self._preview_pending.discard(cache_key)
            pixmap = QPixmap()
            if data is not None:
                width, height, rgba = data
                pixmap = self._pixmap_from_rgba_bytes(width, height, rgba)
            self._preview_pixmap_cache[cache_key] = pixmap

            if self._current_preview_photo is None:
                continue
            current_key = self._preview_cache_key(
                self._current_preview_photo,
                self._current_preview_format_id,
            )
            if current_key == cache_key:
                self.viewer.setPreviewPixmap(pixmap)

    def _queue_visible_thumbnails(self, load_token: int) -> None:
        if not self._grid_device_path:
            return

        visible_indices = list(self.photo_grid.visibleIndices())
        if not visible_indices:
            return

        first_index = min(visible_indices)
        last_index = max(visible_indices)
        prefetch_start = max(0, first_index - (_THUMB_PREFETCH_AHEAD // 2))
        prefetch_stop = min(
            len(self._filtered_items),
            last_index + 1 + _THUMB_PREFETCH_AHEAD,
        )
        prioritized_indices = list(range(prefetch_start, prefetch_stop))

        next_queue: deque[tuple[int, PhotoEntry, int | None, int]] = deque()
        next_queued_ids: set[int] = set()
        for index in prioritized_indices:
            if not (0 <= index < len(self._filtered_items)):
                continue
            photo_id, photo = self._filtered_items[index]
            if (
                photo_id in self._tile_pixmap_cache
                or photo_id in self._thumb_in_flight_ids
            ):
                continue
            next_queued_ids.add(photo_id)
            next_queue.append(
                (photo_id, photo, self._default_tile_format_id(photo), load_token)
            )
        self._thumb_queue = next_queue
        self._queued_thumb_ids = next_queued_ids
        if self._thumb_queue and not self._thumb_timer.isActive():
            self._thumb_timer.start(0)

    def _process_thumb_batch(self) -> None:
        if not self._thumb_queue or self._thumb_workers_in_flight >= _MAX_THUMB_WORKERS:
            return

        from iopenpod.application.runtime import ThreadPoolSingleton, Worker

        batch: list[tuple[int, PhotoEntry, int | None]] = []
        load_token = self._grid_load_token
        for _ in range(_THUMB_DECODE_BATCH_SIZE):
            if not self._thumb_queue:
                break
            photo_id, photo, format_id, token = self._thumb_queue.popleft()
            if token != self._grid_load_token:
                self._queued_thumb_ids.discard(photo_id)
                continue
            self._queued_thumb_ids.discard(photo_id)
            self._thumb_in_flight_ids.add(photo_id)
            batch.append((photo_id, photo, format_id))

        if not batch:
            if self._thumb_queue and not self._thumb_timer.isActive():
                self._thumb_timer.start(1)
            return

        self._thumb_workers_in_flight += 1
        worker = Worker(self._load_thumb_batch, batch, self._grid_device_path)
        worker.signals.result.connect(
            lambda result, lid=load_token: self._on_thumb_batch_loaded(result, lid)
        )
        ThreadPoolSingleton.get_instance().start(worker)

        if self._thumb_queue and not self._thumb_timer.isActive():
            self._thumb_timer.start(1)

    def _on_thumb_batch_loaded(
        self,
        results: dict[int, PhotoTilePayload | None] | None,
        load_token: int,
    ) -> None:
        self._thumb_workers_in_flight = max(0, self._thumb_workers_in_flight - 1)
        if results is None or load_token != self._grid_load_token:
            if results is not None:
                for photo_id in results:
                    self._thumb_in_flight_ids.discard(photo_id)
            return

        for photo_id, data in results.items():
            self._thumb_in_flight_ids.discard(photo_id)
            pixmap = QPixmap()
            dominant_color: tuple[int, int, int] | None = None
            if data is not None:
                width, height, rgba, dominant_color = data
                pixmap = self._pixmap_from_rgba_bytes(width, height, rgba)
            self._tile_pixmap_cache[photo_id] = pixmap
            self._tile_color_cache[photo_id] = dominant_color
            self.photo_grid.setRecordPixmap(
                photo_id,
                pixmap,
                dominant_color=dominant_color,
            )

        if self._thumb_queue and not self._thumb_timer.isActive():
            self._thumb_timer.start(0)

    def _update_collection_summary(self):
        pass

    def _current_photo(self) -> tuple[int | None, PhotoEntry | None]:
        row = self.photo_grid.currentIndex()
        if row < 0 or row >= len(self._filtered_items):
            return None, None
        return self._filtered_items[row]

    def _clear_album_sidebar(self):
        self._album_buttons.clear()
        self._selected_album_btn = None
        while self._album_inner_layout.count():
            item = self._album_inner_layout.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.deleteLater()

    def _rebuild_album_sidebar(self, album_names: list[str]):
        self._clear_album_sidebar()
        self._add_album_button("All Photos")
        for name in album_names:
            self._add_album_button(name)
        self._album_inner_layout.addStretch()

    def _add_album_button(self, name: str):
        btn = SidebarNavButton(name, self._album_inner)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.clicked.connect(lambda _checked=False, album_name=name: self._on_album_changed(album_name))
        btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        btn.customContextMenuRequested.connect(
            lambda pos, b=btn, album_name=name: self._on_album_context_requested(
                album_name,
                b.mapToGlobal(pos),
            )
        )
        self._album_buttons[name] = btn
        self._album_inner_layout.addWidget(btn)

    def _set_menu_icon(self, action, glyph_name: str, color: str | None = None) -> None:
        icon = glyph_icon(glyph_name, 14, color or Colors.TEXT_PRIMARY)
        if icon is not None and action is not None:
            action.setIcon(icon)

    def _add_menu_action(
        self,
        menu: QMenu,
        label: str,
        *,
        glyph_name: str,
        color: str | None = None,
        enabled: bool = True,
    ) -> QAction:
        action = menu.addAction(label)
        if action is None:
            raise RuntimeError(f"Could not create menu action: {label}")
        self._set_menu_icon(action, glyph_name, color)
        action.setEnabled(enabled)
        return action

    def _on_photo_context_requested(
        self,
        key: object,
        index: int,
        global_pos,
    ) -> None:
        if not (0 <= index < len(self._filtered_items)):
            return
        photo_id, photo = self._filtered_items[index]
        if photo_id != key:
            return

        grid = getattr(self, "photo_grid", None)
        if grid is not None and hasattr(grid, "setCurrentIndex"):
            grid.setCurrentIndex(index)

        menu = QMenu(self)
        menu.setStyleSheet(context_menu_css())
        actions_locked = self._photo_actions_locked()

        export_action = self._add_menu_action(
            menu,
            "Export Photo...",
            glyph_name="download",
            enabled=not actions_locked,
        )

        menu.addSeparator()
        add_action = self._add_menu_action(
            menu,
            "Add to Album",
            glyph_name="plus",
            enabled=not actions_locked and bool(self._available_album_targets(photo)),
        )

        remove_action: QAction | None = None
        current_album = self._selected_album_target()
        if current_album:
            remove_action = self._add_menu_action(
                menu,
                "Remove from Current Album",
                glyph_name="minus",
                enabled=(
                    not actions_locked
                    and current_album in getattr(photo, "album_names", set())
                ),
            )

        menu.addSeparator()
        delete_action = self._add_menu_action(
            menu,
            "Delete Photo",
            glyph_name="trash",
            color=Colors.DANGER,
            enabled=not actions_locked,
        )

        rename_action = self._add_menu_action(
            menu,
            "Rename Photo",
            glyph_name="edit",
            enabled=not actions_locked,
        )

        chosen = menu.exec(global_pos)
        if chosen == export_action and export_action.isEnabled():
            self._export_current_photo()
        elif chosen == add_action and add_action.isEnabled():
            self._add_to_album()
        elif (
            remove_action is not None
            and chosen == remove_action
            and remove_action.isEnabled()
        ):
            self._remove_from_album()
        elif chosen == delete_action and delete_action.isEnabled():
            self._delete_photo()
        elif chosen == rename_action and rename_action.isEnabled():
            self._rename_photo()

    def _on_album_context_requested(self, album_name: str, global_pos) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(context_menu_css())
        actions_locked = self._photo_actions_locked()
        target_album = "" if album_name in ("", "All Photos") else album_name
        exportable_count = len(self._photos_for_album_target(target_album))

        export_action = self._add_menu_action(
            menu,
            "Export Album..." if target_album else "Export All Photos...",
            glyph_name="download",
            enabled=not actions_locked and exportable_count > 0,
        )

        menu.addSeparator()

        new_action = self._add_menu_action(
            menu,
            "New Album",
            glyph_name="plus",
            enabled=not actions_locked,
        )

        rename_action: QAction | None = None
        delete_action: QAction | None = None
        if target_album:
            menu.addSeparator()
            rename_action = self._add_menu_action(
                menu,
                "Rename Album",
                glyph_name="edit",
                enabled=not actions_locked,
            )

            delete_action = self._add_menu_action(
                menu,
                "Delete Album",
                glyph_name="trash",
                color=Colors.DANGER,
                enabled=not actions_locked,
            )

        chosen = menu.exec(global_pos)
        if chosen == export_action and export_action.isEnabled():
            self._export_album_target(target_album)
        elif chosen == new_action and new_action.isEnabled():
            self._create_album()
        elif (
            rename_action is not None
            and chosen == rename_action
            and rename_action.isEnabled()
        ):
            self._rename_album_target(target_album)
        elif (
            delete_action is not None
            and chosen == delete_action
            and delete_action.isEnabled()
        ):
            self._delete_album_target(target_album)

    def _highlight_album_button(self, album_name: str):
        if self._selected_album_btn is not None:
            self._selected_album_btn.setSelected(False)
        btn = self._album_buttons.get(album_name) or self._album_buttons.get("All Photos")
        self._selected_album_btn = btn
        if btn is not None:
            btn.setSelected(True)

    def _update_action_states(self):
        actions_locked = self._photo_actions_locked()
        has_album = bool(self._selected_album_target())
        _key, photo = self._current_photo()
        has_photo = photo is not None
        can_add_to_album = has_photo and bool(self._available_album_targets(photo))
        self.new_album_btn.setEnabled(not actions_locked)
        self.export_photo_btn.setEnabled(
            not actions_locked and has_photo and bool(self._current_device_path())
        )
        self.add_to_album_btn.setEnabled(not actions_locked and can_add_to_album)
        self.remove_from_album_btn.setEnabled(
            not actions_locked and has_album and has_photo
        )
        self.delete_photo_btn.setEnabled(not actions_locked and has_photo)

    def _on_album_changed(self, album_name: str):
        self._current_album = album_name
        self._highlight_album_button(album_name)
        self._schedule_grid_reload(self._current_device_path())
        self._update_action_states()

    def _on_photo_changed(self, row: int):
        if row < 0 or row >= len(self._filtered_items):
            self._current_preview_photo = None
            self._current_preview_format_id = None
            self._current_format_ids = []
            self.viewer.clearPreview()
            self._update_action_states()
            return

        _, photo = self._filtered_items[row]
        self._show_photo_preview(photo)
        self._update_action_states()

    def _on_variant_selected(self, format_id: int) -> None:
        if self._current_preview_photo is not None:
            self._show_photo_preview(self._current_preview_photo, selected_format_id=format_id)

    def _selected_album_target(self) -> str:
        return "" if self._current_album in ("", "All Photos") else self._current_album

    def _available_album_targets(self, photo: PhotoEntry) -> list[str]:
        return [
            name for name in self._album_names()
            if name and name not in getattr(photo, "album_names", set())
        ]

    def _show_save_indicator(self, state: str) -> None:
        sidebar = getattr(self.window(), "sidebar", None)
        if sidebar is not None and hasattr(sidebar, "show_save_indicator"):
            sidebar.show_save_indicator(state)

    def _is_sync_running(self) -> bool:
        owner = self.window()
        if owner is self:
            return False
        sync_checker = getattr(owner, "_is_sync_running", None)
        if callable(sync_checker):
            return bool(sync_checker())
        return False

    def _is_photo_export_running(self) -> bool:
        export_worker = getattr(self, "_export_worker", None)
        return export_worker is not None and export_worker.isRunning()

    def _photo_actions_locked(self) -> bool:
        write_worker = getattr(self, "_write_worker", None)
        return (
            write_worker is not None
            and write_worker.isRunning()
        ) or self._is_photo_export_running() or self._is_sync_running()

    def _start_photo_write(
        self,
        action: str,
        *,
        image_id: int | None = None,
        album_name: str = "",
        old_name: str = "",
        new_name: str = "",
    ) -> None:
        if self._write_worker is not None and self._write_worker.isRunning():
            QMessageBox.information(self, "Photo Save In Progress", "Please wait for the current photo save to finish.")
            return
        if self._is_photo_export_running():
            QMessageBox.information(self, "Photo Export In Progress", "Please wait for the current photo export to finish.")
            return
        if self._is_sync_running():
            QMessageBox.information(self, "Sync Running", "Wait for the current sync to finish before editing photos.")
            return
        if self._device_db is None:
            QMessageBox.warning(self, "No Photo Database", "The iPod photo database is not loaded yet.")
            return

        session = self._device_sessions.current_session()
        ipod_path = session.device_path or ""
        if not ipod_path:
            QMessageBox.warning(self, "No iPod Connected", "Select an iPod before editing device photos.")
            return

        self._show_save_indicator("saving")
        self._write_worker = _PhotoWriteWorker(
            ipod_path,
            self._device_db,
            action,
            image_id=image_id,
            album_name=album_name,
            old_name=old_name,
            new_name=new_name,
            sync_settings=self._photo_sync_settings(),
            reported_volume_format=(
                session.storage.reported_volume_format
                if session.storage is not None
                else ""
            ),
            expected_volume_identity_key=(
                session.storage.volume_identity_key
                if session.storage is not None
                else ""
            ),
        )
        self._write_worker.finished_ok.connect(self._on_photo_write_ok)
        self._write_worker.failed.connect(self._on_photo_write_failed)
        self._write_worker.finished.connect(self._on_photo_write_finished)
        self._write_worker.finished.connect(self._write_worker.deleteLater)
        self._write_worker.start()
        self._update_action_states()

    def _on_photo_write_ok(self, photodb: object) -> None:
        if isinstance(photodb, PhotoDB):
            self._device_db = photodb
            self._tile_pixmap_cache.clear()
            self._tile_color_cache.clear()
            self._preview_pixmap_cache.clear()
            self._preview_pending.clear()
            self._cache_marker = None
            self._library_cache.replace_photo_db(photodb)
        self._show_save_indicator("saved")

    def _on_photo_write_failed(self, error_msg: str) -> None:
        self._show_save_indicator("error")
        QMessageBox.warning(self, "Photo Save Failed", f"Could not save photo changes to the iPod:\n{error_msg}")

    def _on_photo_write_finished(self) -> None:
        self._write_worker = None
        self._update_action_states()

    def _normalize_export_dialog_path(
        self,
        path: str,
        selected_filter: str,
    ) -> Path:
        target = Path(path)
        supported_extensions = _JPEG_EXTENSIONS | _PNG_EXTENSIONS
        if target.suffix.lower() in supported_extensions:
            return target
        suffix = ".png" if "PNG" in selected_filter else ".jpg"
        return target.with_suffix(suffix)

    def _photos_for_album_target(self, album_name: str) -> list[PhotoEntry]:
        if self._device_db is None:
            return []
        photos = list(self._device_db.photos.values())
        if album_name:
            photos = [
                photo for photo in photos
                if album_name in getattr(photo, "album_names", set())
            ]
        return sorted(
            photos,
            key=lambda photo: (
                self._device_photo_title(photo).lower(),
                int(photo.image_id),
            ),
        )

    def _unique_export_path(
        self,
        folder: Path,
        filename: str,
        used_names: set[str],
    ) -> Path:
        original = Path(filename)
        stem = _safe_photo_stem(original.stem, "photo")
        suffix = original.suffix if original.suffix.lower() in _JPEG_EXTENSIONS else ".jpg"
        candidate = folder / f"{stem}{suffix}"
        counter = 2
        while candidate.name.lower() in used_names or candidate.exists():
            candidate = folder / f"{stem} ({counter}){suffix}"
            counter += 1
        used_names.add(candidate.name.lower())
        return candidate

    def _export_targets_for_photos(
        self,
        photos: list[PhotoEntry],
        folder: str | Path,
    ) -> list[PhotoExportRequest]:
        target_dir = Path(folder)
        used_names: set[str] = set()
        exports: list[PhotoExportRequest] = []
        for photo in photos:
            filename = _default_export_filename(
                self._device_photo_title(photo),
                int(photo.image_id),
            )
            target = self._unique_export_path(target_dir, filename, used_names)
            exports.append((photo, str(target)))
        return exports

    def _start_photo_export(
        self,
        exports: list[PhotoExportRequest],
        destination_label: str,
    ) -> None:
        if self._is_photo_export_running():
            QMessageBox.information(self, "Photo Export In Progress", "Please wait for the current photo export to finish.")
            return
        if self._write_worker is not None and self._write_worker.isRunning():
            QMessageBox.information(self, "Photo Save In Progress", "Please wait for the current photo save to finish.")
            return
        if self._is_sync_running():
            QMessageBox.information(self, "Sync Running", "Wait for the current sync to finish before exporting photos.")
            return
        if not exports:
            QMessageBox.information(self, "No Photos", "There are no photos to export.")
            return

        ipod_path = self._current_device_path()
        if not ipod_path:
            QMessageBox.warning(self, "No iPod Connected", "Select an iPod before exporting device photos.")
            return

        worker = _PhotoExportWorker(
            ipod_path,
            exports,
            destination_label,
        )
        worker.finished_ok.connect(self._on_photo_export_ok)
        worker.failed.connect(self._on_photo_export_failed)
        worker.finished.connect(self._on_photo_export_finished)
        worker.finished.connect(worker.deleteLater)
        self._export_worker = worker
        worker.start()
        self._update_action_states()

    def _on_photo_export_ok(self, count: int, destination_label: str) -> None:
        noun = "photo" if count == 1 else "photos"
        QMessageBox.information(
            self,
            "Photo Export Complete",
            f"Exported {count:,} {noun} to:\n{destination_label}",
        )

    def _on_photo_export_failed(self, error_msg: str) -> None:
        QMessageBox.warning(
            self,
            "Photo Export Failed",
            f"Could not export photos from the iPod:\n{error_msg}",
        )

    def _on_photo_export_finished(self) -> None:
        self._export_worker = None
        self._update_action_states()

    def _export_current_photo(self):
        _key, photo = self._current_photo()
        if photo is None:
            return
        if not self._current_device_path():
            QMessageBox.warning(self, "No iPod Connected", "Select an iPod before exporting device photos.")
            return

        title = self._device_photo_title(photo)
        default_path = Path.home() / _default_export_filename(title, int(photo.image_id))
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Photo",
            str(default_path),
            _EXPORT_FILTERS,
        )
        if not path:
            return

        target_path = self._normalize_export_dialog_path(path, selected_filter)
        self._start_photo_export(
            [(photo, str(target_path))],
            str(target_path),
        )

    def _export_album_target(self, album_name: str) -> None:
        photos = self._photos_for_album_target(album_name)
        if not photos:
            QMessageBox.information(self, "No Photos", "There are no photos to export.")
            return
        if not self._current_device_path():
            QMessageBox.warning(self, "No iPod Connected", "Select an iPod before exporting device photos.")
            return

        title = "Export Album" if album_name else "Export All Photos"
        folder = QFileDialog.getExistingDirectory(
            self,
            title,
            str(Path.home()),
            QFileDialog.Option.ShowDirsOnly,
        )
        if not folder:
            return

        self._start_photo_export(
            self._export_targets_for_photos(photos, folder),
            folder,
        )

    def _create_album(self):
        name, ok = QInputDialog.getText(self, "New Album", "Album name:")
        if ok and name.strip():
            self._start_photo_write("create_album", album_name=name.strip())

    def _add_to_album(self):
        _key, photo = self._current_photo()
        if photo is None:
            return
        album_names = self._available_album_targets(photo)
        if not album_names:
            QMessageBox.information(self, "No Available Albums", "Create another album first, or choose a photo that is not already in every album.")
            return
        target_album, ok = QInputDialog.getItem(
            self,
            "Add Photo to Album",
            "Album:",
            album_names,
            0,
            False,
        )
        if ok and target_album:
            self._start_photo_write("add_to_album", image_id=photo.image_id, album_name=target_album)

    def _rename_album(self):
        current = self._selected_album_target()
        self._rename_album_target(current)

    def _rename_album_target(self, current: str) -> None:
        if not current:
            return
        new_name, ok = QInputDialog.getText(self, "Rename Album", "New album name:", text=current)
        if ok and new_name.strip() and new_name.strip() != current:
            self._start_photo_write("rename_album", old_name=current, new_name=new_name.strip())

    def _delete_album(self):
        current = self._selected_album_target()
        self._delete_album_target(current)

    def _delete_album_target(self, current: str) -> None:
        if not current:
            return
        if QMessageBox.question(self, "Delete Album", f"Delete '{current}' from the iPod now?") == QMessageBox.StandardButton.Yes:
            self._start_photo_write("delete_album", album_name=current)

    def _remove_from_album(self):
        current = self._selected_album_target()
        _key, photo = self._current_photo()
        if not current or photo is None:
            return
        self._start_photo_write("remove_from_album", image_id=photo.image_id, album_name=current)

    def _delete_photo(self):
        _key, photo = self._current_photo()
        if photo is None:
            return
        if QMessageBox.question(
            self,
            "Delete Photo",
            f"Delete '{self._device_photo_title(photo)}' from the iPod now?",
        ) == QMessageBox.StandardButton.Yes:
            self._start_photo_write("delete_photo", image_id=photo.image_id)

    def _rename_photo(self) -> None:
        _key, photo = self._current_photo()
        if photo is None:
            return
        current = self._device_photo_title(photo)
        new_name, ok = QInputDialog.getText(
            self,
            "Rename Photo",
            "New photo name:",
            text=current,
        )
        if ok and new_name.strip() and new_name.strip() != current:
            self._start_photo_write(
                "rename_photo",
                image_id=photo.image_id,
                new_name=new_name.strip(),
            )
