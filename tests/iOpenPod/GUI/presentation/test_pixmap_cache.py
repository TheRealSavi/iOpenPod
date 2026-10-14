"""Pixmap ownership stays bounded even when Qt independently discards images."""

from PySide6.QtGui import QColor, QPixmap, QPixmapCache
from tests.iOpenPod.GUI.presentation.test_artwork_provider import APPLICATION

from iOpenPod.GUI.presentation.pixmap_cache import PixmapCache


def test_pixmap_lru_evicts_old_keys_and_keeps_recently_used_images() -> None:
    APPLICATION.processEvents()
    cache = PixmapCache("test/lru/", max_entries=2)
    image = QPixmap(2, 2)
    image.fill(QColor("red"))
    try:
        cache.insert("first", image)
        cache.insert("second", image)
        assert cache.get("first") is not None
        cache.insert("third", image)
        assert cache.get("second") is None
        assert cache.get("first") is not None
        assert cache.get("third") is not None
    finally:
        cache.clear()
    assert cache.get("first") is None
    assert cache.get("third") is None


def test_key_bookkeeping_is_bounded_when_qt_evicts_pixmaps_independently() -> None:
    cache = PixmapCache("test/qt-eviction/", max_entries=2)
    image = QPixmap(2, 2)
    image.fill(QColor("blue"))
    try:
        for index in range(20):
            cache.insert(str(index), image)
            QPixmapCache.remove(f"test/qt-eviction/{index}")
        assert len(cache._keys) <= 2  # pyright: ignore[reportPrivateUsage]
        assert cache.get("19") is None
    finally:
        cache.clear()
