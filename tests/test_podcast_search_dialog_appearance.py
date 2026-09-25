from types import SimpleNamespace

from PyQt6.QtWidgets import QScrollArea

from iopenpod.gui.styles import paint_css
from iopenpod.gui.widgets.podcastSearchDialog import PodcastSearchDialog, _SearchResultCard


def test_podcast_search_dialog_uses_resolved_modal_and_surface_paints(qtbot) -> None:
    dialog = PodcastSearchDialog()
    qtbot.addWidget(dialog)
    result = SimpleNamespace(
        title="Example Podcast",
        artist="Example Artist",
        genre="Technology",
        track_count=12,
        artwork_url_small="",
        artwork_url="",
        feed_url="https://example.com/feed.xml",
    )
    card = _SearchResultCard(result, dialog)
    qtbot.addWidget(card)

    scroll = dialog.findChild(QScrollArea)

    assert paint_css("modal.background") in dialog.styleSheet()
    assert scroll is not None
    assert paint_css("border.subtle") in scroll.styleSheet()
    assert paint_css("surface.inset") in card.styleSheet()
    assert paint_css("surface.hover") in card.styleSheet()
