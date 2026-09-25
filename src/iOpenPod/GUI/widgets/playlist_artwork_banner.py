# Hallmark · component: Playlist artwork banner · genre: modern-minimal · theme: iOpenPod
# states: no selection · empty · placeholders · loading · loaded · theme changed
# pre-emit critique: P5 H5 E5 S5 R5 V4 · contrast: pass · tokens: pass
"""Quiet, deterministic album-art ribbons behind Playlist context controls."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from random import Random
from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF, QSize, Qt, Slot
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from iOpenPod.app.models.artwork_seed import stable_artwork_seed
from iOpenPod.GUI.presentation.artwork import (
    paint_artwork_pixmap,
    paint_artwork_placeholder,
)
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT

if TYPE_CHECKING:
    from collections.abc import Iterable

    from PySide6.QtGui import QPaintEvent

    from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
    from iOpenPod.GUI.presentation.theme.manager import ThemeManager
    from iPodDB.library import Track

_MAX_ALBUMS = 12
_LIGHT_ARTWORK_OPACITY = 0.30
_DARK_ARTWORK_OPACITY = 0.42
_RIBBON_ANGLE_DEGREES = 10.0


@dataclass(frozen=True, slots=True)
class _BannerTile:
    artwork_id: int
    placeholder_seed: int


class PlaylistArtworkBanner(QWidget):
    """Paint a bounded, slanted ribbon from a Playlist's representative covers."""

    def __init__(
        self,
        theme_manager: ThemeManager,
        artwork_provider: ArtworkPixmapProvider,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("playlistArtworkBanner")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMinimumHeight(LAYOUT.playlist_banner_minimum_height)
        self._theme_manager = theme_manager
        self._artwork_provider = artwork_provider
        self._tiles: tuple[_BannerTile, ...] = ()
        self._artwork_ids: frozenset[int] = frozenset()
        artwork_provider.artworkChanged.connect(self._artwork_changed)
        artwork_provider.cleared.connect(self.update)
        theme_manager.effectiveThemeChanged.connect(self._theme_changed)

    @property
    def artwork_ids(self) -> tuple[int, ...]:
        """Return the representative IDs in their deterministic display order."""

        return tuple(tile.artwork_id for tile in self._tiles)

    def set_tracks(
        self,
        tracks: Iterable[Track],
        *,
        playlist_id: int | None,
    ) -> None:
        """Replace the bounded album projection used by the decorative ribbon."""

        tiles = _representative_tiles(tracks, playlist_id=playlist_id)
        if tiles == self._tiles:
            return
        self._tiles = tiles
        self._artwork_ids = frozenset(
            tile.artwork_id for tile in tiles if tile.artwork_id > 0
        )
        self.update()

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        hint.setHeight(max(hint.height(), LAYOUT.playlist_banner_minimum_height))
        return hint

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        tokens = self._theme_manager.tokens
        background = QColor(tokens.window)
        painter.fillRect(self.rect(), background)
        if not self._tiles:
            return

        painter.save()
        painter.setClipRect(self.rect())
        painter.setOpacity(
            _LIGHT_ARTWORK_OPACITY
            if background.lightnessF() >= 0.5
            else _DARK_ARTWORK_OPACITY
        )

        tile_size = float(LAYOUT.playlist_banner_artwork_size)
        gap = float(LAYOUT.space_xs)
        step = tile_size + gap
        ribbon_left = self.width() * (0.52 if self.width() < 720 else 0.36)
        pivot_x = ribbon_left + ((self.width() - ribbon_left) / 2.0)
        painter.translate(pivot_x, self.height() / 2.0)
        direction = (
            -1.0 if self.layoutDirection() is Qt.LayoutDirection.LeftToRight else 1.0
        )
        painter.rotate(direction * _RIBBON_ANGLE_DEGREES)
        painter.translate(-pivot_x, -self.height() / 2.0)

        start_x = ribbon_left - tile_size
        start_y = -(tile_size * 0.55)
        columns = max(1, ceil((self.width() - start_x + tile_size) / step))
        rows = max(2, ceil((self.height() - start_y + tile_size) / step))
        pixmaps: dict[int, QPixmap | None] = {}
        device_pixel_ratio = self.devicePixelRatioF()
        for row in range(rows):
            row_offset = -(step / 2.0) if row % 2 else 0.0
            for column in range(columns):
                tile = self._tiles[(row * columns + column) % len(self._tiles)]
                tile_rect = QRectF(
                    start_x + row_offset + (column * step),
                    start_y + (row * step),
                    tile_size,
                    tile_size,
                )
                pixmap = None
                if tile.artwork_id > 0:
                    if tile.artwork_id not in pixmaps:
                        pixmaps[tile.artwork_id] = self._artwork_provider.pixmap(
                            tile.artwork_id,
                            LAYOUT.playlist_banner_artwork_size,
                            device_pixel_ratio,
                        )
                    pixmap = pixmaps[tile.artwork_id]
                if pixmap is None:
                    paint_artwork_placeholder(
                        painter,
                        tile_rect,
                        tile.placeholder_seed,
                        tokens,
                        float(LAYOUT.space_3xs),
                    )
                else:
                    paint_artwork_pixmap(
                        painter,
                        tile_rect,
                        pixmap,
                        tokens,
                        float(LAYOUT.space_3xs),
                    )
        painter.restore()

        separator = QPen(QColor(tokens.border))
        separator.setWidthF(1.0)
        painter.setPen(separator)
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)

    @Slot(object)
    def _artwork_changed(self, artwork_id: object) -> None:
        if isinstance(artwork_id, int) and artwork_id in self._artwork_ids:
            self.update()

    @Slot(str)
    def _theme_changed(self, _theme: str) -> None:
        self.update()


def _representative_tiles(
    tracks: Iterable[Track],
    *,
    playlist_id: int | None,
) -> tuple[_BannerTile, ...]:
    album_artwork: dict[str, int] = {}
    for track in tracks:
        retained = album_artwork.get(track.album_key)
        if retained is None or (retained <= 0 < track.artwork_id):
            album_artwork[track.album_key] = track.artwork_id

    tiles = [
        _BannerTile(
            artwork_id=artwork_id,
            placeholder_seed=stable_artwork_seed(album_key),
        )
        for album_key, artwork_id in sorted(album_artwork.items())
    ]
    Random(0 if playlist_id is None else playlist_id).shuffle(tiles)
    return tuple(tiles[:_MAX_ALBUMS])


__all__ = ["PlaylistArtworkBanner"]
