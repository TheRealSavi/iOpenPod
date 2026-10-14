"""Bounded ownership bookkeeping for Qt's independently byte-limited pixmaps."""

from collections import OrderedDict

from PySide6.QtGui import QPixmap, QPixmapCache


class PixmapCache:
    """Retain at most one small LRU of keys, including keys Qt has evicted."""

    def __init__(self, prefix: str, *, max_entries: int = 512) -> None:
        if max_entries <= 0:
            raise ValueError("Pixmap cache entry limit must be positive")
        self._prefix = prefix
        self._max_entries = max_entries
        self._keys: OrderedDict[str, None] = OrderedDict()

    def get(self, identity: str) -> QPixmap | None:
        key = f"{self._prefix}{identity}"
        pixmap = QPixmap()
        if not QPixmapCache.find(key, pixmap) or pixmap.isNull():
            self._keys.pop(key, None)
            return None
        self._remember(key)
        return pixmap

    def insert(self, identity: str, pixmap: QPixmap) -> None:
        key = f"{self._prefix}{identity}"
        if QPixmapCache.insert(key, pixmap):
            self._remember(key)

    def clear(self) -> None:
        for key in self._keys:
            QPixmapCache.remove(key)
        self._keys.clear()

    def _remember(self, key: str) -> None:
        self._keys[key] = None
        self._keys.move_to_end(key)
        while len(self._keys) > self._max_entries:
            discarded, _ = self._keys.popitem(last=False)
            QPixmapCache.remove(discarded)
