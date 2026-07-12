from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from PIL import Image, UnidentifiedImageError
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..styles import Colors, Metrics, btn_css, make_scroll_area

log = logging.getLogger(__name__)

_ARTWORK_TEMP_PREFIX = "iopenpod-artwork-"
_UNIFY_ARTWORK_ICON_SIZE = 156


@dataclass
class ArtworkUnifyChoice:
    digest: str
    image: Image.Image
    source_img_id: int | None
    source_label: str
    first_track_title: str
    first_track_index: int
    track_count: int = 0


@dataclass(frozen=True)
class ArtworkUnifyContext:
    title: str
    tracks: list[dict]
    choices: list[ArtworkUnifyChoice]
    missing_count: int


def track_artwork_id(track: dict) -> int | None:
    artwork_id = (
        track.get("artwork_id_ref")
        or track.get("mhii_link")
        or track.get("mhiiLink")
        or 0
    )
    if not artwork_id:
        return None
    try:
        return int(artwork_id)
    except (TypeError, ValueError):
        return None


def track_title(track: dict) -> str:
    title = track.get("Title") or track.get("title") or ""
    return str(title).strip() or "Untitled Track"


def short_artwork_label(text: str, max_chars: int = 24) -> str:
    cleaned = " ".join(str(text).split())
    if len(cleaned) <= max_chars:
        return cleaned
    return f"{cleaned[: max_chars - 3]}..."


def artwork_compare_hash(image: Image.Image) -> str:
    normalized = image.convert("RGBA")
    digest = hashlib.sha256()
    digest.update(b"RGBA")
    digest.update(f"{normalized.width}x{normalized.height}".encode("ascii"))
    digest.update(normalized.tobytes("raw", "RGBA"))
    return digest.hexdigest()


def save_unified_artwork_temp(image: Image.Image) -> str:
    fd, path = tempfile.mkstemp(prefix=_ARTWORK_TEMP_PREFIX, suffix=".png")
    os.close(fd)
    try:
        image.save(path, "PNG")
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
        raise
    return path


def _pending_artwork_image(track: dict) -> tuple[Image.Image, str] | None:
    pending_path = track.get("_iop_pending_artwork_path")
    if not pending_path:
        return None
    try:
        pending_path = os.fspath(pending_path)
    except TypeError:
        return None
    if not os.path.exists(pending_path):
        return None
    try:
        with Image.open(pending_path) as img:
            return img.copy(), "Pending artwork"
    except (OSError, UnidentifiedImageError):
        return None


def _track_artwork_image_for_unify(
    track: dict,
    *,
    artworkdb_data: dict | None,
    artwork_folder_path: str,
    img_id_index: dict[int, dict] | None,
) -> tuple[Image.Image, int | None, str] | None:
    pending = _pending_artwork_image(track)
    if pending is not None:
        image, label = pending
        return image, None, label

    from ..imgMaker import get_artwork, get_track_artwork_previews

    artwork_id = track_artwork_id(track)
    if artwork_id is not None:
        image = get_artwork(
            artwork_id,
            mode="image_only",
            artworkdb_data=artworkdb_data,
            artwork_folder_path=artwork_folder_path,
            img_id_index=img_id_index,
        )
        if image is not None:
            return image, artwork_id, f"Artwork {artwork_id}"

    previews = get_track_artwork_previews(
        track,
        artworkdb_data=artworkdb_data,
        artwork_folder_path=artwork_folder_path,
        img_id_index=img_id_index,
    )
    if not previews:
        return None

    preview = previews[0]
    variant = representative_artwork_variant(preview)
    if variant is None:
        return None
    return variant.image, preview.img_id, f"Artwork {preview.img_id}"


def representative_artwork_variant(artwork: Any) -> Any | None:
    variants = list(getattr(artwork, "variants", ()) or ())
    if not variants:
        return None
    return max(
        variants,
        key=lambda item: (item.width * item.height, item.format_id),
    )


def _album_title(album_item: dict) -> str:
    album_title = (
        album_item.get("album")
        or album_item.get("title")
        or "Album"
    )
    return str(album_title)


def build_album_artwork_unify_context(
    album_item: dict,
    tracks: Sequence[dict],
    *,
    artworkdb_path: str | None,
    artwork_folder_path: str | None,
) -> ArtworkUnifyContext | None:
    if len(tracks) < 2 or not artworkdb_path or not artwork_folder_path:
        return None

    try:
        from ..imgMaker import configure_artwork_api

        artworkdb_data, img_id_index = configure_artwork_api(
            artworkdb_path,
            artwork_folder_path,
        )
    except Exception:
        log.debug("Could not configure artwork API for artwork unifier", exc_info=True)
        return None

    choices_by_hash: dict[str, ArtworkUnifyChoice] = {}
    missing_count = 0
    for index, track in enumerate(tracks):
        try:
            loaded = _track_artwork_image_for_unify(
                track,
                artworkdb_data=artworkdb_data,
                artwork_folder_path=artwork_folder_path,
                img_id_index=img_id_index,
            )
        except Exception:
            log.debug("Could not decode artwork for track during artwork unifier", exc_info=True)
            loaded = None

        if loaded is None:
            missing_count += 1
            continue

        image, source_img_id, source_label = loaded
        _add_choice(
            choices_by_hash,
            image=image,
            source_img_id=source_img_id,
            source_label=source_label,
            first_track_title=track_title(track),
            first_track_index=index,
        )

    return _context_from_choices(
        title=_album_title(album_item),
        tracks=tracks,
        choices_by_hash=choices_by_hash,
        missing_count=missing_count,
    )


def build_track_artwork_unify_context(
    title: str,
    tracks: Sequence[dict],
    artworks: Sequence[Any],
) -> ArtworkUnifyContext | None:
    if len(tracks) < 2:
        return None

    preview_by_img_id: dict[int, Any] = {}
    preview_by_song_id: dict[int, Any] = {}
    for artwork in artworks:
        try:
            img_id = int(getattr(artwork, "img_id", 0) or 0)
        except (TypeError, ValueError):
            img_id = 0
        if img_id:
            preview_by_img_id.setdefault(img_id, artwork)

        try:
            song_id = int(getattr(artwork, "song_id", 0) or 0)
        except (TypeError, ValueError):
            song_id = 0
        if song_id:
            preview_by_song_id.setdefault(song_id, artwork)

    choices_by_hash: dict[str, ArtworkUnifyChoice] = {}
    missing_count = 0
    for index, track in enumerate(tracks):
        artwork = _preview_for_track(track, preview_by_img_id, preview_by_song_id)
        if artwork is None:
            missing_count += 1
            continue

        variant = representative_artwork_variant(artwork)
        if variant is None:
            missing_count += 1
            continue

        source_img_id = int(getattr(artwork, "img_id", 0) or 0) or None
        source_label = f"Artwork {source_img_id}" if source_img_id is not None else "Artwork"
        _add_choice(
            choices_by_hash,
            image=variant.image,
            source_img_id=source_img_id,
            source_label=source_label,
            first_track_title=track_title(track),
            first_track_index=index,
        )

    return _context_from_choices(
        title=title,
        tracks=tracks,
        choices_by_hash=choices_by_hash,
        missing_count=missing_count,
    )


def _preview_for_track(
    track: dict,
    preview_by_img_id: dict[int, Any],
    preview_by_song_id: dict[int, Any],
) -> Any | None:
    artwork_id = track_artwork_id(track)
    if artwork_id is not None and artwork_id in preview_by_img_id:
        return preview_by_img_id[artwork_id]

    for key in ("db_track_id", "track_id"):
        try:
            track_id = int(track.get(key) or 0)
        except (TypeError, ValueError):
            track_id = 0
        if track_id and track_id in preview_by_song_id:
            return preview_by_song_id[track_id]
    return None


def _add_choice(
    choices_by_hash: dict[str, ArtworkUnifyChoice],
    *,
    image: Image.Image,
    source_img_id: int | None,
    source_label: str,
    first_track_title: str,
    first_track_index: int,
) -> None:
    digest = artwork_compare_hash(image)
    choice = choices_by_hash.get(digest)
    if choice is None:
        choice = ArtworkUnifyChoice(
            digest=digest,
            image=image.copy(),
            source_img_id=source_img_id,
            source_label=source_label,
            first_track_title=first_track_title,
            first_track_index=first_track_index,
            track_count=0,
        )
        choices_by_hash[digest] = choice
    choice.track_count += 1


def _context_from_choices(
    *,
    title: str,
    tracks: Sequence[dict],
    choices_by_hash: dict[str, ArtworkUnifyChoice],
    missing_count: int,
) -> ArtworkUnifyContext | None:
    choices = sorted(
        choices_by_hash.values(),
        key=lambda choice: choice.first_track_index,
    )
    if not choices:
        return None
    if len(choices) == 1 and missing_count == 0:
        return None
    return ArtworkUnifyContext(
        title=title,
        tracks=list(tracks),
        choices=choices,
        missing_count=missing_count,
    )


def _pil_image_icon(image: Image.Image, size: int = _UNIFY_ARTWORK_ICON_SIZE) -> QIcon:
    rgba = image.convert("RGBA")
    qimage = QImage(
        rgba.tobytes("raw", "RGBA"),
        rgba.width,
        rgba.height,
        QImage.Format.Format_RGBA8888,
    ).copy()
    pixmap = QPixmap.fromImage(qimage).scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    return QIcon(pixmap)


class UnifyArtworkDialog(QDialog):
    def __init__(self, context: ArtworkUnifyContext, parent=None):
        super().__init__(parent)
        self._context = context
        self._selected_choice: ArtworkUnifyChoice | None = None

        self.setWindowTitle("Unify Artwork")
        self.setMinimumSize(520, 360)
        self.resize(720, 520)
        self.setStyleSheet(
            f"""
            QDialog {{
                background: {Colors.DIALOG_BG};
            }}
            QLabel#dialogTitle {{
                color: {Colors.TEXT_PRIMARY};
            }}
            QLabel#dialogSubtitle {{
                color: {Colors.TEXT_SECONDARY};
            }}
            QToolButton#artworkChoice {{
                background: {Colors.SURFACE};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                color: {Colors.TEXT_PRIMARY};
                padding: 10px;
            }}
            QToolButton#artworkChoice:hover {{
                background: {Colors.SURFACE_HOVER};
                border-color: {Colors.BORDER};
            }}
            QToolButton#artworkChoice:pressed {{
                background: {Colors.SURFACE_ACTIVE};
                border-color: {Colors.ACCENT_BORDER};
            }}
            """
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(14)

        title = QLabel("Choose Artwork")
        title.setObjectName("dialogTitle")
        title.setStyleSheet(f"font-size: {Metrics.FONT_XL}pt; font-weight: 700;")
        outer.addWidget(title)

        track_count = len(context.tracks)
        subtitle = QLabel(
            f"{context.title} - {track_count} track{'s' if track_count != 1 else ''}"
        )
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        for index, choice in enumerate(context.choices):
            grid.addWidget(self._choice_button(choice), index // 3, index % 3)
        grid.setColumnStretch(3, 1)

        scroll = make_scroll_area()
        scroll.setWidget(grid_host)
        outer.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setStyleSheet(btn_css())
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        outer.addLayout(buttons)

    def selected_choice(self) -> ArtworkUnifyChoice | None:
        return self._selected_choice

    def _choice_button(self, choice: ArtworkUnifyChoice) -> QToolButton:
        button = QToolButton()
        button.setObjectName("artworkChoice")
        button.setFixedSize(190, 222)
        button.setIcon(_pil_image_icon(choice.image))
        button.setIconSize(QSize(_UNIFY_ARTWORK_ICON_SIZE, _UNIFY_ARTWORK_ICON_SIZE))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        detail = f"{choice.track_count} track{'s' if choice.track_count != 1 else ''}"
        button.setText(f"{detail}\n{short_artwork_label(choice.first_track_title)}")
        button.setToolTip(f"{choice.source_label}\n{choice.first_track_title}")
        button.clicked.connect(lambda _checked=False, c=choice: self._choose(c))
        return button

    def _choose(self, choice: ArtworkUnifyChoice) -> None:
        self._selected_choice = choice
        self.accept()
