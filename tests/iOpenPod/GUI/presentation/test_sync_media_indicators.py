"""Sync badges describe existing iPod media and checkbox colors describe intent."""

from collections.abc import Iterator
from dataclasses import replace
from typing import cast
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem, QWidget
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.core.settings.definitions import AppearanceMode, DarkTheme, LightTheme
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.app.host_media_library import HostMediaCacheStats, HostMediaLibrary
from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.models.album_list_model import AlbumListModel, AlbumRole
from iOpenPod.app.models.collection_list_model import (
    CollectionKind,
    CollectionListModel,
    CollectionRole,
)
from iOpenPod.app.models.photo_list_model import PhotoListModel, PhotoRole
from iOpenPod.app.models.sync_selection import SyncSelection
from iOpenPod.app.models.track_table_model import (
    TrackColumn,
    TrackRole,
    TrackTableModel,
)
from iOpenPod.app.sync_plan import (
    SyncPlan,
    SyncPlanAction,
    SyncPlanBasis,
    SyncPlanItem,
    SyncPlanMediaKind,
)
from iOpenPod.GUI.delegates.photo_card_delegate import PhotoCardDelegate
from iOpenPod.GUI.delegates.sync_track_delegate import SyncTrackDelegate
from iOpenPod.GUI.presentation.photo_provider import PhotoPixmapProvider
from iOpenPod.GUI.presentation.selection_checkbox import (
    library_card_checkbox_rect,
    paint_library_card_checkbox,
)
from iOpenPod.GUI.presentation.sync_media import (
    library_card_ipod_rect,
    sync_checkbox_tokens,
)
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import Theme, tokens_for
from iPodDB.library import (
    LibrarySnapshot,
    Photo,
    PhotoAlbum,
    PhotoLibrary,
    PhotoRepresentation,
    PhotoRepresentationKind,
    Track,
    TrackMetadata,
)


@pytest.fixture
def theme() -> Iterator[ThemeManager]:
    settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
    manager = ThemeManager(APPLICATION, settings)
    yield manager
    manager.close()


def test_ipod_presence_is_independent_of_selection_and_aggregates_any_match() -> None:
    tracks = tuple(
        Track(
            identity,
            f"Track {identity}",
            artist,
            album,
            1000,
            metadata=TrackMetadata(location=f"C:/Music/{identity}.mp3"),
        )
        for identity, artist, album in (
            (1, "Mixed artist", "Mixed album"),
            (2, "Mixed artist", "Mixed album"),
            (3, "New artist", "New album"),
        )
    )
    host = HostMediaLibrary(LibrarySnapshot(tracks), (), (), HostMediaCacheStats())
    selection = SyncSelection()
    match = SyncPlanItem(
        SyncPlanAction.UNCHANGED,
        SyncPlanMediaKind.TRACK,
        SyncPlanBasis.CONTENT_MATCH,
        "Existing",
        "",
        tracks[0].metadata.location,
        "iPod_Control/Music/F00/old.mp3",
        10,
    )
    selection.reset(host, SyncPlan((match,)))
    model = TrackTableModel()
    model.replace_tracks(tracks)
    albums = AlbumListModel(model)
    collections = CollectionListModel(model, CollectionKind.ARTIST)
    for projection in (model, albums, collections):
        projection.set_sync_selection(selection)

    for checked in (True, False):
        selection.set_all_host_media_checked(checked)
        assert [
            model.index(row, TrackColumn.SYNC_SELECTION).data(TrackRole.ON_IPOD)
            for row in range(3)
        ] == [True, False, False]
        assert [albums.index(row, 0).data(AlbumRole.ON_IPOD) for row in range(2)] == [
            True,
            False,
        ]
        assert [
            collections.index(row, 0).data(CollectionRole.ON_IPOD) for row in range(2)
        ] == [True, False]

    selection.revert_host_media_selection()
    assert (
        albums.index(0, 0).data(Qt.ItemDataRole.CheckStateRole)
        is Qt.CheckState.PartiallyChecked
    )
    assert albums.index(0, 0).data(AlbumRole.ON_IPOD) is True
    selection.reset(
        host, SyncPlan((replace(match, host_path=tracks[2].metadata.location),))
    )
    assert albums.index(0, 0).data(AlbumRole.ON_IPOD) is False
    assert albums.index(1, 0).data(AlbumRole.ON_IPOD) is True
    selection.clear()
    assert not selection.track_on_ipod(1)
    assert not selection.track_group_on_ipod(())
    for projection in (model, albums, collections):
        projection.set_sync_selection(None)
    assert model.index(0, TrackColumn.SYNC_SELECTION).data(TrackRole.ON_IPOD) is None
    assert albums.index(0, 0).data(AlbumRole.ON_IPOD) is None
    assert collections.index(0, 0).data(CollectionRole.ON_IPOD) is None


@pytest.mark.parametrize("mode", [AppearanceMode.LIGHT, AppearanceMode.DARK])
@pytest.mark.parametrize("dpr", [1, 2])
@pytest.mark.parametrize("on_ipod", [False, True])
@pytest.mark.parametrize("state", list(Qt.CheckState))
def test_grid_and_track_checkbox_colors_and_ipod_markers(
    theme: ThemeManager,
    mode: AppearanceMode,
    dpr: int,
    on_ipod: bool,
    state: Qt.CheckState,
) -> None:
    theme.set_mode(mode)
    widget = QWidget()
    option = QStyleOptionViewItem()
    option.initFrom(widget)
    option.widget = widget
    option.state = QStyle.StateFlag.State_Enabled
    option.rect = QRect(0, 0, 200, 250)
    tokens = theme.tokens
    expected = (
        tokens.accent
        if state is Qt.CheckState.PartiallyChecked
        else tokens.accent
        if on_ipod and state is Qt.CheckState.Checked
        else tokens.danger
        if on_ipod
        else tokens.success
        if state is Qt.CheckState.Checked
        else tokens.surface
    )
    card = QImage(200 * dpr, 250 * dpr, QImage.Format.Format_ARGB32)
    card.setDevicePixelRatio(dpr)
    card.fill(Qt.GlobalColor.transparent)
    painter = QPainter(card)
    paint_library_card_checkbox(
        painter, option, state, tokens, theme.typography, on_ipod=on_ipod
    )
    painter.end()
    checkbox = library_card_checkbox_rect(option, theme.typography)
    assert card.pixelColor(
        round(checkbox.center().x() * dpr), round((checkbox.top() + 6) * dpr)
    ) == QColor(expected)
    marker = library_card_ipod_rect(option, theme.typography).toRect()
    assert _has_color(card, marker, QColor(tokens.text), dpr) is on_ipod

    # Track rows only have binary selection; the card test covers mixed groups.
    if state is not Qt.CheckState.PartiallyChecked:
        model = QStandardItemModel()
        item = QStandardItem()
        item.setCheckable(True)
        item.setCheckState(state)
        item.setData(False, TrackRole.STREAM_MANUAL)
        item.setData(on_ipod, TrackRole.ON_IPOD)
        model.appendRow(item)
        delegate = SyncTrackDelegate(theme, widget)
        option.rect = QRect(0, 0, 200, 36)
        row = QImage(200 * dpr, 36 * dpr, QImage.Format.Format_ARGB32)
        row.setDevicePixelRatio(dpr)
        row.fill(Qt.GlobalColor.transparent)
        painter = QPainter(row)
        delegate.paint(painter, option, model.index(0, 0))
        painter.end()
        row_checkbox = delegate.checkbox_rect(option.rect)
        assert row.pixelColor(
            row_checkbox.center().x() * dpr, (row_checkbox.top() + 6) * dpr
        ) == QColor(expected)
        assert (
            _has_color(row, delegate.ipod_rect(option.rect), QColor(tokens.text), dpr)
            is on_ipod
        )
    widget.close()


def _has_color(image: QImage, rect: QRect, color: QColor, dpr: int) -> bool:
    return any(
        image.pixelColor(x, y) == color
        for x in range(rect.left() * dpr, (rect.right() + 1) * dpr)
        for y in range(rect.top() * dpr, (rect.bottom() + 1) * dpr)
    )


@pytest.mark.parametrize("mode", [AppearanceMode.LIGHT, AppearanceMode.DARK])
@pytest.mark.parametrize("dpr", [1, 2])
def test_photo_cards_show_presence_and_sync_colors_in_all_photos_and_albums(
    theme: ThemeManager, mode: AppearanceMode, dpr: int
) -> None:
    theme.set_mode(mode)
    photos = tuple(
        Photo(
            identity,
            representations=(
                PhotoRepresentation(
                    PhotoRepresentationKind.FULL_RESOLUTION,
                    1,
                    f"C:/Photos/{identity}.jpg",
                    0,
                    100,
                    10,
                    10,
                ),
            ),
        )
        for identity in (1, 2)
    )
    snapshot = LibrarySnapshot(
        photos=PhotoLibrary(
            photos=photos, albums=(PhotoAlbum(10, "Trip", photo_ids=(1, 2, 1)),)
        )
    )
    host = HostMediaLibrary(snapshot, (), (), HostMediaCacheStats())
    match = SyncPlanItem(
        SyncPlanAction.UNCHANGED,
        SyncPlanMediaKind.PHOTO,
        SyncPlanBasis.CONTENT_MATCH,
        "Existing Photo",
        "",
        "C:/Photos/1.jpg",
        "Photos/Full Resolution/1.jpg",
        100,
    )
    selection = SyncSelection()
    selection.reset(host, SyncPlan((match,)))
    workspace = LibraryWorkspace()
    workspace.load(snapshot)
    model = PhotoListModel(workspace)
    assert model.index(0, 0).data(PhotoRole.ON_IPOD) is None
    model.set_sync_selection(selection)
    provider = Mock(spec=PhotoPixmapProvider)
    provider.pixmap.return_value = None
    widget = QWidget()
    delegate = PhotoCardDelegate(theme, cast("PhotoPixmapProvider", provider), widget)
    option = QStyleOptionViewItem()
    option.initFrom(widget)
    option.widget = widget
    option.state = QStyle.StateFlag.State_Enabled
    option.rect = QRect(0, 0, 200, 250)
    checkbox = library_card_checkbox_rect(option, theme.typography)
    marker = library_card_ipod_rect(option, theme.typography).toRect()
    tokens = theme.tokens

    for album_id in (None, 10):
        model.set_album_id(album_id)
        for checked in (True, False):
            selection.set_all_host_media_checked(checked)
            for row in range(model.rowCount()):
                index = model.index(row, 0)
                on_ipod = index.data(PhotoRole.ID) == 1
                assert index.data(PhotoRole.ON_IPOD) is on_ipod
                expected = (
                    (tokens.accent if on_ipod else tokens.success)
                    if checked
                    else (tokens.danger if on_ipod else tokens.surface)
                )
                card = QImage(200 * dpr, 250 * dpr, QImage.Format.Format_ARGB32)
                card.setDevicePixelRatio(dpr)
                card.fill(Qt.GlobalColor.transparent)
                painter = QPainter(card)
                delegate.paint(painter, option, index)
                painter.end()
                assert card.pixelColor(
                    round(checkbox.center().x() * dpr),
                    round((checkbox.top() + 6) * dpr),
                ) == QColor(expected)
                assert _has_color(card, marker, QColor(tokens.text), dpr) is on_ipod

    selection.revert_host_media_selection()
    assert selection.photo_on_ipod(1)
    assert not selection.photo_on_ipod(2)
    selection.reset(host, SyncPlan((replace(match, host_path="C:/Photos/2.jpg"),)))
    assert model.index(0, 0).data(PhotoRole.ON_IPOD) is False
    assert model.index(1, 0).data(PhotoRole.ON_IPOD) is True
    selection.clear()
    assert model.index(1, 0).data(PhotoRole.ON_IPOD) is False
    model.set_sync_selection(None)
    assert model.index(0, 0).data(PhotoRole.ON_IPOD) is None
    assert model.index(0, 0).data(Qt.ItemDataRole.CheckStateRole) is None
    widget.close()


@pytest.mark.parametrize("exact_theme", [*LightTheme, *DarkTheme])
def test_new_media_checkmark_has_readable_contrast(exact_theme: Theme) -> None:
    tokens = sync_checkbox_tokens(tokens_for(exact_theme), Qt.CheckState.Checked, False)
    luminances: list[float] = []
    for value in (tokens.accent, tokens.accent_ink):
        color = QColor(value)
        channels = (color.redF(), color.greenF(), color.blueF())
        linear = [
            channel / 12.92
            if channel <= 0.04045
            else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        luminances.append(
            sum(
                weight * channel
                for weight, channel in zip(
                    (0.2126, 0.7152, 0.0722), linear, strict=True
                )
            )
        )
    assert (max(luminances) + 0.05) / (min(luminances) + 0.05) >= 4.5
