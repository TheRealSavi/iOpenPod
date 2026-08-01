from __future__ import annotations

from iopenpod.gui.styles import paint_css
from iopenpod.gui.widgets.podcastStates import PodcastStatePanel


def test_podcast_state_error_message_reserves_wrapped_height(qtbot) -> None:
    panel = PodcastStatePanel()
    qtbot.addWidget(panel)
    panel.resize(360, 260)

    panel.show_error(
        "No internet connection",
        "iOpenPod could not reach the podcast service. Check your connection and try again.",
        code="NETWORK_UNAVAILABLE",
    )
    panel.resize(360, 260)

    message = panel._message
    expected_height = message.heightForWidth(message.width())

    assert expected_height > 0
    assert message.height() >= expected_height
    assert paint_css("text.secondary") in panel._message.styleSheet()
    assert paint_css("surface.raised") in panel._code.styleSheet()
    assert paint_css("border.subtle") in panel._code.styleSheet()
