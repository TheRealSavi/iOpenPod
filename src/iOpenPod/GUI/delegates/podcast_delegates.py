"""Virtualized, artwork-led delegates for the Podcast browser."""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import (
    QModelIndex,
    QPersistentModelIndex,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem, QWidget

from iOpenPod.app.models.artwork_seed import stable_artwork_seed
from iOpenPod.app.models.podcast_list_models import PodcastListRole
from iOpenPod.app.podcasts.models import (
    PodcastEpisode,
    PodcastSearchResult,
    PodcastSubscription,
)
from iOpenPod.GUI.presentation.artwork import (
    paint_artwork_pixmap,
    paint_artwork_placeholder,
)
from iOpenPod.GUI.presentation.podcast_collection_artwork import (
    paint_podcast_collection_artwork,
)
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT, ThemeTokens, TypographyTokens

if TYPE_CHECKING:
    from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
    from iOpenPod.GUI.presentation.podcast_artwork_provider import (
        PodcastArtworkPixmapProvider,
    )
    from iOpenPod.GUI.presentation.theme.manager import ThemeManager

_SHOW_WIDTH = 248
_SHOW_HEIGHT = 72
_SHOW_ARTWORK = 48
_EPISODE_HEIGHT = 128
_SEARCH_HEIGHT = 88


class PodcastShowDelegate(QStyledItemDelegate):
    """Paint compact cover-led rows for the vertical show rail."""

    def __init__(
        self,
        theme_manager: ThemeManager,
        artwork_provider: PodcastArtworkPixmapProvider,
        parent: QWidget | None = None,
        *,
        device_artwork_provider: ArtworkPixmapProvider | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self._artwork_provider = artwork_provider
        self._device_artwork_provider = device_artwork_provider

    def sizeHint(
        self,
        _option: QStyleOptionViewItem,
        _index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        return QSize(_SHOW_WIDTH, _SHOW_HEIGHT)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        subscription = index.data(PodcastListRole.RECORD)
        is_aggregate = bool(index.data(PodcastListRole.IS_AGGREGATE))
        if not isinstance(subscription, PodcastSubscription) and not is_aggregate:
            return
        title = (
            str(index.data(Qt.ItemDataRole.DisplayRole) or "All Podcasts")
            if is_aggregate
            else subscription.title
        )
        identity = (
            str(index.data(PodcastListRole.IDENTITY) or "all-podcasts")
            if is_aggregate
            else subscription.subscription_id
        )
        tokens = self._theme_manager.tokens
        typography = self._theme_manager.typography
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
        cell = QRectF(option.rect).adjusted(4, 4, -4, -4)
        artwork = QRectF(cell.left() + 8, cell.top() + 8, _SHOW_ARTWORK, _SHOW_ARTWORK)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if selected or hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(
                QColor(tokens.surface_selected if selected else tokens.surface_hover)
            )
            painter.drawRoundedRect(
                cell,
                float(LAYOUT.radius_panel),
                float(LAYOUT.radius_panel),
            )
        if is_aggregate:
            subscription_values = index.data(PodcastListRole.SUBSCRIPTIONS)
            typed_values = (
                cast("tuple[object, ...]", subscription_values)
                if isinstance(subscription_values, tuple)
                else ()
            )
            subscriptions = tuple(
                item for item in typed_values if isinstance(item, PodcastSubscription)
            )
            paint_podcast_collection_artwork(
                painter,
                artwork,
                subscriptions,
                self._artwork_provider,
                tokens,
                option.widget.devicePixelRatioF(),
                self._device_artwork_provider,
            )
        else:
            pixmap = self._artwork_provider.pixmap(
                subscription.artwork_url,
                _SHOW_ARTWORK,
                option.widget.devicePixelRatioF(),
            )
            if pixmap is None:
                paint_artwork_placeholder(
                    painter,
                    artwork,
                    stable_artwork_seed(identity),
                    tokens,
                    float(LAYOUT.radius_control),
                )
            else:
                paint_artwork_pixmap(
                    painter,
                    artwork,
                    pixmap,
                    tokens,
                    float(LAYOUT.radius_control),
                )
        title_font = _font(
            option.font, typography.album_card_title_pt, QFont.Weight.DemiBold
        )
        detail_font = _font(option.font, typography.small_pt, QFont.Weight.Medium)
        title_metrics = QFontMetrics(title_font)
        detail_metrics = QFontMetrics(detail_font)
        text_left = artwork.right() + LAYOUT.space_sm
        text_width = max(64.0, cell.right() - text_left - LAYOUT.space_xs)
        text_rect = QRectF(
            text_left,
            cell.top() + 16,
            text_width,
            title_metrics.height(),
        )
        painter.setFont(title_font)
        painter.setPen(QColor(tokens.text))
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            title_metrics.elidedText(
                title,
                Qt.TextElideMode.ElideRight,
                round(text_rect.width()),
            ),
        )
        if is_aggregate:
            episode_count = int(index.data(PodcastListRole.EPISODE_COUNT) or 0)
            detail = f"{episode_count} episodes"
        else:
            detail = (
                f"{subscription.on_device_count} on iPod"
                if subscription.on_device_count
                else subscription.author or "Subscribed"
            )
        painter.setFont(detail_font)
        painter.setPen(QColor(tokens.text_secondary))
        painter.drawText(
            QRectF(
                text_rect.left(),
                text_rect.bottom() + LAYOUT.space_3xs,
                text_rect.width(),
                detail_metrics.height(),
            ),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            detail_metrics.elidedText(
                detail,
                Qt.TextElideMode.ElideRight,
                round(text_rect.width()),
            ),
        )
        if focused:
            _paint_focus(painter, cell, tokens)
        painter.restore()


class PodcastEpisodeDelegate(QStyledItemDelegate):
    """Paint editorial episode rows with metadata, synopsis, and device state."""

    def __init__(
        self,
        theme_manager: ThemeManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager

    def sizeHint(
        self,
        _option: QStyleOptionViewItem,
        _index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        return QSize(600, _EPISODE_HEIGHT)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        episode = index.data(PodcastListRole.RECORD)
        if not isinstance(episode, PodcastEpisode):
            return
        tokens = self._theme_manager.tokens
        typography = self._theme_manager.typography
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
        row = QRectF(option.rect).adjusted(8, 4, -8, -4)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        background = (
            tokens.surface_selected
            if selected
            else tokens.surface_hover
            if hovered
            else tokens.surface
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(background))
        painter.drawRoundedRect(
            row,
            float(LAYOUT.radius_control),
            float(LAYOUT.radius_control),
        )
        left = row.left() + 16
        right_reserve = 160.0
        text_width = max(80.0, row.width() - 32 - right_reserve)
        meta_font = _font(option.font, typography.small_pt, QFont.Weight.Medium)
        title_font = _font(option.font, typography.heading_pt, QFont.Weight.DemiBold)
        body_font = _font(option.font, typography.body_pt, QFont.Weight.Normal)
        meta_metrics = QFontMetrics(meta_font)
        title_metrics = QFontMetrics(title_font)
        body_metrics = QFontMetrics(body_font)

        subscription_title = str(index.data(PodcastListRole.SUBSCRIPTION_TITLE) or "")
        meta = _episode_meta(episode, subscription_title)
        painter.setFont(meta_font)
        painter.setPen(
            QColor(tokens.accent if episode.on_device else tokens.text_secondary)
        )
        painter.drawText(
            QRectF(left, row.top() + 12, text_width, meta_metrics.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            meta.upper(),
        )
        title_y = row.top() + 12 + meta_metrics.height() + LAYOUT.space_3xs
        painter.setFont(title_font)
        painter.setPen(QColor(tokens.text))
        painter.drawText(
            QRectF(left, title_y, text_width, title_metrics.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            title_metrics.elidedText(
                episode.title or "Untitled Episode",
                Qt.TextElideMode.ElideRight,
                round(text_width),
            ),
        )
        description_y = title_y + title_metrics.height() + LAYOUT.space_2xs
        painter.setFont(body_font)
        painter.setPen(QColor(tokens.text_secondary))
        _draw_wrapped_text(
            painter,
            episode.description or "No episode notes are available.",
            QRectF(
                left,
                description_y,
                text_width,
                max(0.0, row.bottom() - description_y - 8),
            ),
            body_metrics,
            max_lines=2,
        )
        _paint_episode_state(painter, row, episode, option.font, typography, tokens)
        if focused:
            _paint_focus(painter, row, tokens)
        painter.restore()


class PodcastSearchResultDelegate(QStyledItemDelegate):
    """Paint directory matches as legible text without remote promotional art."""

    def __init__(
        self,
        theme_manager: ThemeManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager

    def sizeHint(
        self,
        _option: QStyleOptionViewItem,
        _index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        return QSize(560, _SEARCH_HEIGHT)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        result = index.data(PodcastListRole.RECORD)
        if not isinstance(result, PodcastSearchResult):
            return
        tokens = self._theme_manager.tokens
        typography = self._theme_manager.typography
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)
        row = QRectF(option.rect).adjusted(4, 4, -4, -4)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if selected or hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(
                QColor(tokens.surface_selected if selected else tokens.surface_hover)
            )
            painter.drawRoundedRect(
                row,
                float(LAYOUT.radius_control),
                float(LAYOUT.radius_control),
            )
        left = row.left() + 12
        width = max(80.0, row.right() - left - 12)
        title_font = _font(option.font, typography.heading_pt, QFont.Weight.DemiBold)
        detail_font = _font(option.font, typography.body_pt, QFont.Weight.Normal)
        small_font = _font(option.font, typography.small_pt, QFont.Weight.Medium)
        title_metrics = QFontMetrics(title_font)
        detail_metrics = QFontMetrics(detail_font)
        small_metrics = QFontMetrics(small_font)
        painter.setFont(title_font)
        painter.setPen(QColor(tokens.text))
        painter.drawText(
            QRectF(left, row.top() + 8, width, title_metrics.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            title_metrics.elidedText(
                result.title,
                Qt.TextElideMode.ElideRight,
                round(width),
            ),
        )
        painter.setFont(detail_font)
        painter.setPen(QColor(tokens.text_secondary))
        painter.drawText(
            QRectF(
                left,
                row.top() + 12 + title_metrics.height(),
                width,
                detail_metrics.height(),
            ),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            detail_metrics.elidedText(
                result.author or "Unknown publisher",
                Qt.TextElideMode.ElideRight,
                round(width),
            ),
        )
        details = " · ".join(
            part
            for part in (
                result.category,
                f"{result.episode_count} episodes" if result.episode_count else "",
            )
            if part
        )
        painter.setFont(small_font)
        painter.drawText(
            QRectF(
                left,
                row.bottom() - small_metrics.height() - 8,
                width,
                small_metrics.height(),
            ),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            details,
        )
        if focused:
            _paint_focus(painter, row, tokens)
        painter.restore()


def _paint_episode_state(
    painter: QPainter,
    row: QRectF,
    episode: PodcastEpisode,
    base_font: QFont,
    typography: TypographyTokens,
    tokens: ThemeTokens,
) -> None:
    font = _font(base_font, typography.small_pt, QFont.Weight.DemiBold)
    painter.setFont(font)
    metrics = QFontMetrics(font)
    state_text = episode_status_text(episode)
    width = min(132, metrics.horizontalAdvance(state_text) + LAYOUT.space_lg)
    rect = QRectF(
        row.right() - width - LAYOUT.space_md,
        row.top() + LAYOUT.space_md,
        width,
        LAYOUT.control_height_compact,
    )
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(
        QColor(tokens.surface_selected if episode.on_device else tokens.accent)
    )
    painter.drawRoundedRect(
        rect,
        rect.height() / 2,
        rect.height() / 2,
    )
    painter.setPen(QColor(tokens.accent if episode.on_device else tokens.accent_ink))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, state_text)
    if episode.on_device:
        circle = QRectF(row.right() - 56, row.bottom() - 56, 40, 40)
        painter.setBrush(QColor(tokens.accent))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(circle)
        path = QPainterPath()
        path.moveTo(circle.left() + 16, circle.top() + 12)
        path.lineTo(circle.left() + 16, circle.bottom() - 12)
        path.lineTo(circle.right() - 12, circle.center().y())
        path.closeSubpath()
        painter.setBrush(QColor(tokens.accent_ink))
        painter.drawPath(path)


def episode_status_text(episode: PodcastEpisode) -> str:
    """Return the concise device action or state shown beside an Episode."""

    if not episode.on_device:
        return "Add to iPod"
    states = ["ON IPOD"]
    if episode.listened:
        states.append("LISTENED")
    return " · ".join(states)


def _episode_meta(episode: PodcastEpisode, subscription_title: str = "") -> str:
    parts = [subscription_title] if subscription_title else []
    if episode.published_at:
        with suppress(OSError, OverflowError, ValueError):
            parts.append(
                datetime.fromtimestamp(episode.published_at, UTC).strftime("%b %d, %Y")
            )
    if episode.duration_seconds > 0:
        hours, remainder = divmod(episode.duration_seconds, 3600)
        minutes = remainder // 60
        parts.append(f"{hours} hr {minutes} min" if hours else f"{minutes} min")
    if episode.episode_number is not None:
        parts.append(f"Episode {episode.episode_number}")
    return " · ".join(parts) or "Episode"


def _draw_wrapped_text(
    painter: QPainter,
    text: str,
    rect: QRectF,
    metrics: QFontMetrics,
    *,
    max_lines: int,
) -> None:
    lines = _wrapped_lines(text, metrics, round(rect.width()), max_lines)
    y = rect.top()
    for line in lines:
        painter.drawText(
            QRectF(rect.left(), y, rect.width(), metrics.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            line,
        )
        y += metrics.lineSpacing()


def _wrapped_lines(
    text: str,
    metrics: QFontMetrics,
    width: int,
    max_lines: int,
) -> tuple[str, ...]:
    clean = " ".join(text.split())
    if not clean or width <= 0 or max_lines <= 0:
        return ()
    words = clean.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if metrics.horizontalAdvance(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = word
        else:
            lines.append(metrics.elidedText(word, Qt.TextElideMode.ElideRight, width))
            current = ""
        if len(lines) == max_lines:
            lines[-1] = metrics.elidedText(
                f"{lines[-1]} {current}".strip(),
                Qt.TextElideMode.ElideRight,
                width,
            )
            return tuple(lines)
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = metrics.elidedText(lines[-1], Qt.TextElideMode.ElideRight, width)
    elif len(lines) == max_lines and metrics.horizontalAdvance(lines[-1]) > width:
        lines[-1] = metrics.elidedText(lines[-1], Qt.TextElideMode.ElideRight, width)
    return tuple(lines)


def _font(base: QFont, size: float, weight: QFont.Weight) -> QFont:
    font = QFont(base)
    font.setPointSizeF(size)
    font.setWeight(weight)
    return font


def _paint_focus(painter: QPainter, rect: QRectF, tokens: ThemeTokens) -> None:
    pen = QPen(QColor(tokens.focus))
    pen.setWidthF(2)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(
        rect.adjusted(1, 1, -1, -1),
        float(LAYOUT.radius_control),
        float(LAYOUT.radius_control),
    )


__all__ = [
    "PodcastEpisodeDelegate",
    "PodcastSearchResultDelegate",
    "PodcastShowDelegate",
    "episode_status_text",
]
