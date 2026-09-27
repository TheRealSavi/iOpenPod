"""Typed Qt projections for Podcast catalogue, episodes, and directory results."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
)

if TYPE_CHECKING:
    from iOpenPod.app.podcasts.models import (
        PodcastEpisode,
        PodcastSearchResult,
        PodcastSubscription,
    )

_ROOT_INDEX = QModelIndex()
ALL_PODCASTS_SOURCE_ID = "all-podcasts"


@dataclass(frozen=True, slots=True)
class _PodcastEpisodeItem:
    subscription_id: str
    subscription_title: str
    subscription_author: str
    episode: PodcastEpisode


@dataclass(frozen=True, slots=True)
class PodcastEpisodeFilter:
    """Independent inclusion choices for Episode listening and device state."""

    include_listened: bool = True
    include_unlistened: bool = True
    include_on_ipod: bool = True
    include_not_on_ipod: bool = True

    @property
    def active(self) -> bool:
        return not all(
            (
                self.include_listened,
                self.include_unlistened,
                self.include_on_ipod,
                self.include_not_on_ipod,
            )
        )

    def accepts(self, episode: PodcastEpisode) -> bool:
        listened_matches = (
            self.include_listened if episode.listened else self.include_unlistened
        )
        device_matches = (
            self.include_on_ipod if episode.on_device else self.include_not_on_ipod
        )
        return listened_matches and device_matches


class PodcastListRole(IntEnum):
    RECORD = Qt.ItemDataRole.UserRole.value + 1
    IDENTITY = Qt.ItemDataRole.UserRole.value + 2
    SEARCH_TEXT = Qt.ItemDataRole.UserRole.value + 3
    IS_AGGREGATE = Qt.ItemDataRole.UserRole.value + 4
    EPISODE_COUNT = Qt.ItemDataRole.UserRole.value + 5
    ON_DEVICE_COUNT = Qt.ItemDataRole.UserRole.value + 6
    SUBSCRIPTION_TITLE = Qt.ItemDataRole.UserRole.value + 7
    SUBSCRIPTIONS = Qt.ItemDataRole.UserRole.value + 8


class PodcastSubscriptionListModel(QAbstractListModel):
    """Replaceable, typed projection of subscribed Podcast shows."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._items: tuple[PodcastSubscription, ...] = ()
        self._include_all = False

    def replace(
        self,
        items: tuple[PodcastSubscription, ...],
        *,
        include_all: bool = False,
    ) -> None:
        self.beginResetModel()
        self._items = items
        self._include_all = include_all and bool(items)
        self.endResetModel()

    def subscription_at(self, row: int) -> PodcastSubscription | None:
        item_row = row - int(self._include_all)
        return self._items[item_row] if 0 <= item_row < len(self._items) else None

    def is_all_at(self, row: int) -> bool:
        return self._include_all and row == 0

    def row_for_id(self, subscription_id: str | None) -> int:
        if self._include_all and subscription_id in (None, ALL_PODCASTS_SOURCE_ID):
            return 0
        return next(
            (
                row + int(self._include_all)
                for row, item in enumerate(self._items)
                if item.subscription_id == subscription_id
            ),
            -1,
        )

    def rowCount(
        self,
        parent: QModelIndex | QPersistentModelIndex = _ROOT_INDEX,
    ) -> int:
        return 0 if parent.isValid() else len(self._items) + int(self._include_all)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole.value,
    ) -> object | None:
        if not index.isValid():
            return None
        if self.is_all_at(index.row()):
            if role == Qt.ItemDataRole.DisplayRole:
                return self.tr("All Podcasts")
            if role == PodcastListRole.IDENTITY:
                return ALL_PODCASTS_SOURCE_ID
            if role == PodcastListRole.SEARCH_TEXT:
                return self.tr("All Podcasts").casefold()
            if role == PodcastListRole.IS_AGGREGATE:
                return True
            if role == PodcastListRole.EPISODE_COUNT:
                return sum(len(item.episodes) for item in self._items)
            if role == PodcastListRole.ON_DEVICE_COUNT:
                return sum(item.on_device_count for item in self._items)
            if role == PodcastListRole.SUBSCRIPTIONS:
                return self._items
            return None
        item = self.subscription_at(index.row())
        if item is None:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return item.title
        if role == PodcastListRole.RECORD:
            return item
        if role == PodcastListRole.IDENTITY:
            return item.subscription_id
        if role == PodcastListRole.SEARCH_TEXT:
            return "\x1f".join((item.title, item.author, item.category)).casefold()
        if role == PodcastListRole.IS_AGGREGATE:
            return False
        if role == PodcastListRole.EPISODE_COUNT:
            return len(item.episodes)
        if role == PodcastListRole.ON_DEVICE_COUNT:
            return item.on_device_count
        return None

    def retranslate(self) -> None:
        """Refresh the aggregate label and its localized search text."""

        if self._include_all:
            aggregate = self.index(0, 0)
            self.dataChanged.emit(
                aggregate,
                aggregate,
                [Qt.ItemDataRole.DisplayRole.value, PodcastListRole.SEARCH_TEXT.value],
            )


class PodcastEpisodeListModel(QAbstractListModel):
    """Typed, filtered projection of one show or the combined Podcast feed."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._items: tuple[_PodcastEpisodeItem, ...] = ()

    def replace(
        self,
        subscription_id: str,
        items: tuple[PodcastEpisode, ...],
        query: str = "",
        episode_filter: PodcastEpisodeFilter | None = None,
    ) -> None:
        self._replace(
            tuple(
                _PodcastEpisodeItem(subscription_id, "", "", episode)
                for episode in items
            ),
            query,
            episode_filter,
        )

    def replace_all(
        self,
        subscriptions: tuple[PodcastSubscription, ...],
        query: str = "",
        episode_filter: PodcastEpisodeFilter | None = None,
    ) -> None:
        """Project every subscribed Episode into one newest-first feed."""

        items = tuple(
            sorted(
                (
                    _PodcastEpisodeItem(
                        subscription.subscription_id,
                        subscription.title,
                        subscription.author,
                        episode,
                    )
                    for subscription in subscriptions
                    for episode in subscription.episodes
                ),
                key=lambda item: (
                    -item.episode.published_at,
                    item.subscription_title.casefold(),
                    item.episode.title.casefold(),
                    item.subscription_id,
                    item.episode.episode_id,
                ),
            )
        )
        self._replace(items, query, episode_filter)

    def _replace(
        self,
        items: tuple[_PodcastEpisodeItem, ...],
        query: str,
        episode_filter: PodcastEpisodeFilter | None,
    ) -> None:
        needle = query.strip().casefold()
        active_filter = episode_filter or PodcastEpisodeFilter()
        visible = tuple(
            item
            for item in items
            if active_filter.accepts(item.episode)
            and (
                not needle
                or needle
                in "\x1f".join(
                    (
                        item.subscription_title,
                        item.subscription_author,
                        item.episode.title,
                        item.episode.description,
                    )
                ).casefold()
            )
        )
        self.beginResetModel()
        self._items = visible
        self.endResetModel()

    def episode_at(self, row: int) -> PodcastEpisode | None:
        return self._items[row].episode if 0 <= row < len(self._items) else None

    def identity_at(self, row: int) -> tuple[str, str] | None:
        item = self._items[row] if 0 <= row < len(self._items) else None
        return (
            (item.subscription_id, item.episode.episode_id)
            if item is not None and item.subscription_id
            else None
        )

    def rowCount(
        self,
        parent: QModelIndex | QPersistentModelIndex = _ROOT_INDEX,
    ) -> int:
        return 0 if parent.isValid() else len(self._items)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole.value,
    ) -> object | None:
        row = index.row()
        item = (
            self._items[row]
            if index.isValid() and 0 <= row < len(self._items)
            else None
        )
        if item is None:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return item.episode.title
        if role == PodcastListRole.RECORD:
            return item.episode
        if role == PodcastListRole.IDENTITY:
            return (item.subscription_id, item.episode.episode_id)
        if role == PodcastListRole.SEARCH_TEXT:
            return "\x1f".join(
                (
                    item.subscription_title,
                    item.subscription_author,
                    item.episode.title,
                    item.episode.description,
                )
            ).casefold()
        if role == PodcastListRole.SUBSCRIPTION_TITLE:
            return item.subscription_title
        return None


class PodcastSearchResultListModel(QAbstractListModel):
    """Typed projection of one directory search response."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._items: tuple[PodcastSearchResult, ...] = ()

    def replace(self, items: tuple[PodcastSearchResult, ...]) -> None:
        self.beginResetModel()
        self._items = items
        self.endResetModel()

    def result_at(self, row: int) -> PodcastSearchResult | None:
        return self._items[row] if 0 <= row < len(self._items) else None

    def rowCount(
        self,
        parent: QModelIndex | QPersistentModelIndex = _ROOT_INDEX,
    ) -> int:
        return 0 if parent.isValid() else len(self._items)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole.value,
    ) -> object | None:
        item = self.result_at(index.row()) if index.isValid() else None
        if item is None:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return item.title
        if role == PodcastListRole.RECORD:
            return item
        if role == PodcastListRole.IDENTITY:
            return item.feed_url
        if role == PodcastListRole.SEARCH_TEXT:
            return "\x1f".join((item.title, item.author, item.category)).casefold()
        return None


__all__ = [
    "ALL_PODCASTS_SOURCE_ID",
    "PodcastEpisodeFilter",
    "PodcastEpisodeListModel",
    "PodcastListRole",
    "PodcastSearchResultListModel",
    "PodcastSubscriptionListModel",
]
