"""Rating stars preview without edits and support mouse and keyboard selection."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.GUI.widgets.star_rating import StarRating


def test_rating_hover_preserves_exact_value_and_click_again_clears() -> None:
    rating = StarRating(81)
    try:
        rating.resize(180, 40)
        rating.show()
        APPLICATION.processEvents()
        QTest.mouseMove(rating, rating.rect().center())
        assert rating.text() == "★★★☆☆"
        assert rating.property("ratingHover") is True
        assert rating.rating == 81
        APPLICATION.sendEvent(rating, QEvent(QEvent.Type.Leave))
        assert rating.text() == "★★★★☆"
        assert rating.property("ratingHover") is False
        assert rating.accessibleDescription() == "4.05 of 5 stars"

        QTest.mouseClick(rating, Qt.MouseButton.LeftButton, pos=rating.rect().center())
        assert rating.rating == 60
        assert rating.text() == "★★★☆☆"
        QTest.mouseClick(rating, Qt.MouseButton.LeftButton, pos=rating.rect().center())
        assert rating.rating == 0
        assert rating.text() == "☆☆☆☆☆"
    finally:
        rating.close()
        rating.deleteLater()


def test_rating_keyboard_selects_and_clears_and_disabled_rating_cannot_change() -> None:
    rating = StarRating()
    try:
        rating.show()
        rating.setFocus()
        QTest.keyClick(rating, Qt.Key.Key_5)
        assert rating.rating == 100
        QTest.keyClick(rating, Qt.Key.Key_Left)
        assert rating.rating == 80
        QTest.keyClick(rating, Qt.Key.Key_Home)
        assert rating.rating == 0
        QTest.keyClick(rating, Qt.Key.Key_Right)
        assert rating.rating == 20
        QTest.keyClick(rating, Qt.Key.Key_End)
        assert rating.rating == 100
        QTest.keyClick(rating, Qt.Key.Key_0)
        assert rating.rating == 0
        rating.setEnabled(False)
        QTest.keyClick(rating, Qt.Key.Key_5)
        QTest.mouseClick(rating, Qt.MouseButton.LeftButton, pos=rating.rect().center())
        assert rating.rating == 0
    finally:
        rating.close()
        rating.deleteLater()
