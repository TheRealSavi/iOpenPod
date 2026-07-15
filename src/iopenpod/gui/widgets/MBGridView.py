import logging
from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from PIL import Image
from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication

from iopenpod.search import SearchText, matches_search_words, prepare_search_text

from ..artwork_rendering import virtual_artwork_payload
from .gridItem import GridItem as MusicBrowserGridItem
from .gridItem import GridItemModel
from .pooledGrid import PooledGridView

if TYPE_CHECKING:
    from iopenpod.application.services import DeviceSessionService, LibraryCacheLike, SettingsService

# Fuzzy search: only attempt fuzzy matching for tokens at least this long,
# and require a SequenceMatcher ratio above the threshold.
_FUZZY_MIN_LEN = 3
_FUZZY_THRESHOLD = 0.78

_ART_BATCH_SIZE = 20


class _ArtCacheUnset:
    """Sentinel returned when artwork is not yet cached but may still exist."""


_ART_CACHE_UNSET = _ArtCacheUnset()


log = logging.getLogger(__name__)


@dataclass(frozen=True)
class GridRecord:
    """Normalized grid data used by the pooled viewport."""

    source: dict[str, Any]
    key: Hashable
    title: str
    subtitle: str
    payload: dict[str, Any]
    artwork_id: int | None
    artwork_key: Hashable | None
    search_words: tuple[SearchText, ...]


@dataclass(frozen=True)
class ArtworkResult:
    """Artwork payload cached by artwork key."""

    image: Image.Image
    dominant_color: tuple[int, int, int] | None
    album_colors: dict[str, Any] | None


CachedArtworkLookup = ArtworkResult | None | _ArtCacheUnset


class MusicBrowserGrid(PooledGridView):
    """Grid view that displays albums, artists, or genres as clickable items."""

    item_selected = pyqtSignal(dict)
    item_context_requested = pyqtSignal(object, QPoint)
    item_selection_changed = pyqtSignal(object)

    def __init__(
        self,
        *,
        device_sessions: "DeviceSessionService | None" = None,
        library_cache: "LibraryCacheLike | None" = None,
        settings_service: "SettingsService | None" = None,
        multi_select_enabled: bool = False,
    ):
        super().__init__()
        self._device_sessions = device_sessions
        self._library_cache = library_cache
        self._settings_service = settings_service
        self._multi_select_enabled = multi_select_enabled

        self._current_category = "Albums"

        self._all_items: list[dict[str, Any]] = []
        self._records: list[GridRecord] = []
        self._visible_records: list[GridRecord] = []
        self._sort_key = "title"
        self._sort_reverse = False
        self._search_query = ""

        self._art_cache: dict[Hashable, ArtworkResult | None] = {}
        self._art_pending: set[Hashable] = set()
        self._art_seen: set[Hashable] = set()
        self._selected_record_keys: set[Hashable] = set()
        self._selection_anchor_key: Hashable | None = None
        self.itemActivated.connect(self._onRecordActivated)
        self.contextRequested.connect(self._onRecordContextRequested)

    def loadCategory(self, category: str) -> None:
        """Load and display items for the specified category."""
        from iopenpod.application.runtime import (
            build_album_list,
            build_artist_list,
            build_genre_list,
        )

        log.debug("loadCategory() called: %s", category)
        self._current_category = category

        cache = self._library_cache
        if cache is None or not cache.is_ready():
            return

        if category == "Albums":
            items = build_album_list(cache)
        elif category == "Artists":
            items = build_artist_list(cache)
        elif category == "Genres":
            items = build_genre_list(cache)
        else:
            return

        self._set_source_items(items, reset_scroll=True)

    def populateGrid(
        self,
        items: Sequence[dict[str, Any] | MusicBrowserGridItem],
    ) -> None:
        """Compatibility entry point for setting grid contents directly."""
        normalized_items: list[dict[str, Any]] = []
        for item in items:
            if isinstance(item, MusicBrowserGridItem):
                normalized_items.append(dict(item.item_data))
            elif isinstance(item, dict):
                normalized_items.append(dict(item))
        self._set_source_items(normalized_items, reset_scroll=True)

    def setSort(self, key: str, reverse: bool = False) -> None:
        """Apply a new sort order to the current item list."""
        self._sort_key = key
        self._sort_reverse = reverse
        self._apply_filter_and_sort(reset_scroll=False)

    def setSearchFilter(self, query: str) -> None:
        """Filter grid items whose title contains *query* (case-insensitive)."""
        self._search_query = query
        self._apply_filter_and_sort(reset_scroll=False)

    def resetFilters(self) -> None:
        """Reset sort and search to defaults without reloading source data."""
        self._sort_key = "title"
        self._sort_reverse = False
        self._search_query = ""
        self._apply_filter_and_sort(reset_scroll=False)

    def clearGrid(self, preserve_all_items: bool = False) -> None:
        """Clear all rendered widgets and cancel pending artwork work."""
        self.invalidate_artwork_cache(clear_visible=False)
        self._visible_records = []

        if not preserve_all_items:
            self._all_items = []
            self._records = []
            self._clear_item_selection(emit_signal=False)
        super().clearGrid(preserve_all_items=False)

    def invalidate_artwork_cache(self, *, clear_visible: bool = True) -> None:
        """Drop cached artwork payloads and force visible cards to rebind."""
        self._art_cache.clear()
        self._art_pending.clear()
        self._art_seen.clear()
        self._bound_widget_state.clear()

        if clear_visible:
            for widget in list(self._visible_widgets.values()):
                if isinstance(widget, MusicBrowserGridItem):
                    widget.apply_image_result(None, None, None)

    @staticmethod
    def _item_key(item: dict[str, Any]) -> Hashable:
        return cast(Hashable, (
            item.get("category", ""),
            item.get("album") or "",
            item.get("artist") or "",
            item.get("title") or "",
            item.get("filter_key") or "",
            item.get("filter_value") or "",
        ))

    @classmethod
    def _build_record(cls, item: dict[str, Any]) -> GridRecord:
        source = dict(item)
        title = source.get("title") or source.get("album") or ""
        subtitle = source.get("subtitle") or source.get("artist") or ""
        artwork_id = source.get("artwork_id_ref")
        artwork_key = source.get("_grid_art_key", artwork_id)

        payload = {
            key: value
            for key, value in source.items()
            if not str(key).startswith("_")
        }
        payload["title"] = title
        payload["subtitle"] = subtitle
        payload["artwork_id_ref"] = artwork_id
        payload.setdefault("category", "Albums")
        payload.setdefault("filter_key", "Album")
        payload.setdefault("filter_value", title)
        payload.setdefault("album", source.get("album"))
        payload.setdefault("artist", source.get("artist"))

        parts: list[str] = []
        for field in ("title", "artist"):
            value = payload.get(field)
            if value:
                parts.append(str(value))
        year = payload.get("year")
        if year:
            parts.append(str(year))

        return GridRecord(
            source=source,
            key=cls._item_key(payload),
            title=title,
            subtitle=subtitle,
            payload=payload,
            artwork_id=artwork_id,
            artwork_key=artwork_key,
            search_words=tuple(
                prepare_search_text(word) for word in " ".join(parts).split()
            ),
        )

    def _set_source_items(
        self,
        items: list[dict[str, Any]],
        *,
        reset_scroll: bool,
    ) -> None:
        self.invalidate_artwork_cache()
        self._all_items = [dict(item) for item in items]
        self._records = [self._build_record(item) for item in self._all_items]
        self._apply_filter_and_sort(reset_scroll=reset_scroll)

    def _apply_filter_and_sort(self, *, reset_scroll: bool) -> None:
        # Any active artwork batch was bound to the previous viewport/load_id.
        # Clear pending markers so filtered/re-sorted cards can request art again.
        self._art_pending.clear()
        records = self._records

        if self._search_query:
            filtered: list[GridRecord] = []
            for record in records:
                if matches_search_words(
                    self._search_query,
                    record.search_words,
                    fuzzy_min_length=_FUZZY_MIN_LEN,
                    fuzzy_threshold=_FUZZY_THRESHOLD,
                ):
                    filtered.append(record)
            records = filtered

        def _key_fn(record: GridRecord):
            value = record.source.get(self._sort_key)
            if isinstance(value, str):
                return value.lower()
            return value if value is not None else 0

        self._visible_records = sorted(
            records,
            key=_key_fn,
            reverse=self._sort_reverse,
        )
        selection_changed = self._prune_item_selection_to(self._visible_records)
        self._set_viewport_records(
            self._visible_records,
            reset_scroll=reset_scroll,
            preserve_selection=False,
            fallback_index=-1,
        )
        if selection_changed:
            self.item_selection_changed.emit(self.selectedItemData())

    def selectedItemData(self) -> list[dict[str, Any]]:
        """Return selected item payloads in the current visible grid order."""
        if not self._selected_record_keys:
            return []
        return [
            dict(record.payload)
            for record in self._visible_records
            if record.key in self._selected_record_keys
        ]

    def clearItemSelection(self) -> None:
        """Clear file-browser style grid selection."""
        self._clear_item_selection(emit_signal=True)

    def _clear_item_selection(self, *, emit_signal: bool) -> None:
        if not self._selected_record_keys and self._selection_anchor_key is None:
            return
        self._selected_record_keys.clear()
        self._selection_anchor_key = None
        self._sync_visible_selection()
        if emit_signal:
            self.item_selection_changed.emit([])

    def _prune_item_selection_to(self, records: Sequence[GridRecord]) -> bool:
        if not self._selected_record_keys and self._selection_anchor_key is None:
            return False

        valid_keys = {record.key for record in records}
        next_keys = self._selected_record_keys & valid_keys
        changed = next_keys != self._selected_record_keys
        self._selected_record_keys = next_keys

        if self._selection_anchor_key not in valid_keys:
            if self._selection_anchor_key is not None:
                changed = True
            self._selection_anchor_key = None

        return changed

    def _set_item_selection_keys(
        self,
        keys: set[Hashable],
        *,
        anchor_key: Hashable | None,
    ) -> None:
        valid_keys = {record.key for record in self._visible_records}
        next_keys = keys & valid_keys
        next_anchor = anchor_key if anchor_key in valid_keys else None
        if (
            self._selected_record_keys == next_keys
            and self._selection_anchor_key == next_anchor
        ):
            return

        self._selected_record_keys = next_keys
        self._selection_anchor_key = next_anchor
        self._sync_visible_selection()
        self.item_selection_changed.emit(self.selectedItemData())

    def _record_index_for_item_data(self, item_data: dict[str, Any]) -> int | None:
        key = self._item_key(item_data)
        for index, record in enumerate(self._visible_records):
            if record.key == key:
                return index
        return None

    def _selection_anchor_index(self) -> int | None:
        if self._selection_anchor_key is None:
            return None
        for index, record in enumerate(self._visible_records):
            if record.key == self._selection_anchor_key:
                return index
        return None

    def _apply_selection_click(
        self,
        record_index: int,
        modifiers: Any,
    ) -> bool:
        if not self._multi_select_enabled:
            return False

        ctrl = bool(
            modifiers
            & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
        )
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        if not ctrl and not shift:
            return False
        if not (0 <= record_index < len(self._visible_records)):
            return True

        clicked_key = self._visible_records[record_index].key
        selected = set(self._selected_record_keys)
        anchor_key = self._selection_anchor_key

        if shift:
            anchor_index = self._selection_anchor_index()
            if anchor_index is None:
                anchor_index = record_index
                anchor_key = clicked_key

            lo, hi = sorted((anchor_index, record_index))
            range_keys = {
                self._visible_records[index].key
                for index in range(lo, hi + 1)
            }
            selected = selected | range_keys if ctrl else range_keys
        elif ctrl:
            if clicked_key in selected:
                selected.remove(clicked_key)
            else:
                selected.add(clicked_key)
            anchor_key = clicked_key

        self._set_item_selection_keys(selected, anchor_key=anchor_key)
        return True

    def _model_for_record(
        self,
        record: GridRecord,
        cached_artwork: CachedArtworkLookup,
    ) -> GridItemModel:
        if isinstance(cached_artwork, ArtworkResult):
            return GridItemModel(
                title=record.title,
                subtitle=record.subtitle,
                artwork_id=record.artwork_id,
                payload=record.payload,
                image=cached_artwork.image,
                dominant_color=cached_artwork.dominant_color,
                album_colors=cached_artwork.album_colors,
            )

        return GridItemModel(
            title=record.title,
            subtitle=record.subtitle,
            artwork_id=record.artwork_id,
            payload=record.payload,
        )

    def _record_identity(self, record: GridRecord) -> Hashable:
        return record.key

    def _create_pooled_widget(self) -> MusicBrowserGridItem:
        return MusicBrowserGridItem()

    def _connect_widget(self, widget) -> None:
        super()._connect_widget(widget)

    def _bind_widget(
        self,
        widget,
        record_index: int,
        record: GridRecord,
    ) -> None:
        assert isinstance(widget, MusicBrowserGridItem)
        cached_artwork = self._lookup_cached_artwork(record)
        widget.set_rounded_artwork(self._rounded_artwork_enabled())
        widget.set_model(self._model_for_record(record, cached_artwork))

    def _apply_widget_selection(self, widget, selected: bool) -> None:
        if not isinstance(widget, MusicBrowserGridItem):
            return
        if not self._multi_select_enabled:
            widget.setSelected(False)
            return
        record_index = self._record_index_for_widget(widget)
        if record_index is None or not (0 <= record_index < len(self._visible_records)):
            widget.setSelected(False)
            return
        record = self._visible_records[record_index]
        widget.setSelected(record.key in self._selected_record_keys)

    def _after_viewport_refresh(self) -> None:
        self._load_art_async()

    def _lookup_cached_artwork(
        self,
        record: GridRecord,
    ) -> CachedArtworkLookup:
        art_key = record.artwork_key
        if art_key is None:
            return None
        if art_key in self._art_cache:
            return self._art_cache[art_key]
        if art_key in self._art_seen:
            return None

        cached = self._load_cached_artwork(record)
        if isinstance(cached, _ArtCacheUnset):
            return _ART_CACHE_UNSET

        self._art_cache[art_key] = cached
        if cached is None:
            self._art_seen.add(art_key)
        return cached

    def _load_cached_artwork(
        self,
        record: GridRecord,
    ) -> CachedArtworkLookup:
        if record.artwork_id is None:
            return None

        try:
            from ..imgMaker import get_artwork
        except Exception:
            return _ART_CACHE_UNSET

        cached = get_artwork(int(record.artwork_id), mode="cache_only")
        if cached is None:
            return _ART_CACHE_UNSET

        image, _dominant_color, _album_colors = cached
        image, dominant_color, album_colors = virtual_artwork_payload(
            image,
            sharpen=self._sharpen_artwork_enabled(),
        )
        return ArtworkResult(image, dominant_color, album_colors)

    def _apply_art_to_widget(
        self,
        widget: MusicBrowserGridItem,
        record: GridRecord,
    ) -> None:
        cached = self._lookup_cached_artwork(record)
        if isinstance(cached, _ArtCacheUnset):
            widget.apply_image_result(None, None, None)
            return
        if cached is None:
            widget.apply_image_result(None, None, None)
            return
        widget.apply_image_result(
            cached.image,
            cached.dominant_color,
            cached.album_colors,
        )

    def _visible_records_needing_art(self) -> list[GridRecord]:
        needed: list[GridRecord] = []
        seen_keys: set[Hashable] = set()
        for record_index in sorted(self._visible_widgets):
            record = self._visible_records[record_index]
            art_key = record.artwork_key
            if (
                art_key is None
                or art_key in seen_keys
                or art_key in self._art_cache
                or art_key in self._art_pending
                or art_key in self._art_seen
            ):
                continue
            if self._lookup_cached_artwork(record) is _ART_CACHE_UNSET:
                needed.append(record)
                seen_keys.add(art_key)
        return needed

    def _load_art_async(self) -> None:
        """Collect visible artwork keys and load missing art in batches."""
        from iopenpod.application.runtime import ThreadPoolSingleton, Worker

        records = self._visible_records_needing_art()
        if not records or self._device_sessions is None:
            return

        session = self._device_sessions.current_session()
        if not session.device_path or not session.artworkdb_path:
            return

        artwork_folder = session.artwork_folder_path or ""
        cancellation_token = self._device_sessions.manager().cancellation_token
        load_id = self._load_id
        pool = ThreadPoolSingleton.get_instance()

        pairs: list[tuple[Hashable, int]] = []
        for record in records:
            art_key = record.artwork_key
            if art_key is None or record.artwork_id is None:
                continue
            self._art_pending.add(art_key)
            pairs.append((art_key, int(record.artwork_id)))

        for i in range(0, len(pairs), _ART_BATCH_SIZE):
            chunk = pairs[i:i + _ART_BATCH_SIZE]
            worker = Worker(
                self._load_art_batch,
                chunk,
                session.artworkdb_path,
                artwork_folder,
                cancellation_token,
            )
            worker.signals.result.connect(
                lambda result, lid=load_id: self._on_art_loaded(result, lid)
            )
            pool.start(worker)

    def _load_art_batch(
        self,
        pairs: list[tuple[Hashable, int]],
        artworkdb_path: str,
        artwork_folder: str,
        cancellation_token: Any,
    ) -> dict[Hashable, tuple[int, int, bytes, tuple[int, int, int] | None, dict[str, Any] | None] | None]:
        """Background worker: decode artwork + colors for a batch of artwork keys."""
        import os

        from ..imgMaker import configure_artwork_api, get_artwork

        if not artworkdb_path or not os.path.exists(artworkdb_path):
            return {}

        configure_artwork_api(artworkdb_path, artwork_folder)
        results: dict[
            Hashable,
            tuple[int, int, bytes, tuple[int, int, int] | None, dict[str, Any] | None]
            | None,
        ] = {}

        for art_key, link in pairs:
            if cancellation_token.is_cancelled():
                break
            image = get_artwork(link, mode="image_only")
            if image is None:
                results[art_key] = None
                continue

            pil_img, dominant_color, album_colors = virtual_artwork_payload(
                image,
                sharpen=self._sharpen_artwork_enabled(),
            )
            pil_img = pil_img.convert("RGBA")
            results[art_key] = (
                pil_img.width,
                pil_img.height,
                pil_img.tobytes("raw", "RGBA"),
                dominant_color,
                album_colors,
            )

        return results

    def _on_art_loaded(
        self,
        results: dict[
            Hashable,
            tuple[int, int, bytes, tuple[int, int, int] | None, dict[str, Any] | None]
            | None,
        ]
        | None,
        load_id: int,
    ) -> None:
        """Main-thread callback: apply artwork to currently bound widgets."""
        if results is None or self._load_id != load_id:
            return

        try:
            for art_key, data in results.items():
                self._art_pending.discard(art_key)
                if data is None:
                    self._art_cache[art_key] = None
                    self._art_seen.add(art_key)
                    self._apply_art_to_visible_widgets(art_key)
                    continue

                width, height, rgba, dominant_color, album_colors = data
                pil_img = Image.frombytes("RGBA", (width, height), rgba)
                self._art_cache[art_key] = ArtworkResult(
                    pil_img,
                    dominant_color,
                    album_colors,
                )
                self._apply_art_to_visible_widgets(art_key)
        except RuntimeError:
            pass

    def _apply_art_to_visible_widgets(self, artwork_key: Hashable) -> None:
        for record_index, widget in list(self._visible_widgets.items()):
            if record_index >= len(self._visible_records):
                continue
            if not isinstance(widget, MusicBrowserGridItem):
                continue
            record = self._visible_records[record_index]
            if record.artwork_key != artwork_key:
                continue
            self._apply_art_to_widget(widget, record)

    def _onRecordActivated(self, _key: object, record_index: int) -> None:
        if not (0 <= record_index < len(self._visible_records)):
            return
        if self._apply_selection_click(
            record_index,
            QApplication.keyboardModifiers(),
        ):
            return
        item_data = dict(self._visible_records[record_index].payload)
        widget = self._visible_widgets.get(record_index)
        if isinstance(widget, MusicBrowserGridItem):
            # The pooled card carries artwork-derived display colors after its
            # image has been rendered; the normalized record payload does not.
            item_data.update(widget.item_data)
        self.item_selected.emit(item_data)

    def _onRecordContextRequested(
        self,
        _key: object,
        record_index: int,
        global_pos: QPoint,
    ) -> None:
        if not (0 <= record_index < len(self._visible_records)):
            return
        item_data = dict(self._visible_records[record_index].payload)
        if not self._multi_select_enabled:
            self.item_context_requested.emit([item_data], global_pos)
            return

        clicked_key = self._visible_records[record_index].key
        if clicked_key not in self._selected_record_keys:
            self._set_item_selection_keys({clicked_key}, anchor_key=clicked_key)

        targets = self.selectedItemData()
        if targets:
            self.item_context_requested.emit(targets, global_pos)

    def refresh_artwork_appearance(self) -> None:
        """Re-render visible artwork using the current UI appearance settings."""
        rounded = self._rounded_artwork_enabled()
        for widget in list(self._visible_widgets.values()):
            if isinstance(widget, MusicBrowserGridItem):
                widget.set_rounded_artwork(rounded)

    def _rounded_artwork_enabled(self) -> bool:
        if self._settings_service is None:
            return False
        try:
            return bool(self._settings_service.get_effective_settings().rounded_artwork)
        except Exception:
            return False

    def _sharpen_artwork_enabled(self) -> bool:
        if self._settings_service is None:
            return True
        try:
            return bool(self._settings_service.get_effective_settings().sharpen_artwork)
        except Exception:
            return True
