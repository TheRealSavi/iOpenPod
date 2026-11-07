"""Applied Chapter artwork previews through real application composition."""

from time import monotonic

from PySide6.QtGui import QColor
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.GUI.dialogs.artwork_editor import ArtworkEditor
from iOpenPod.GUI.dialogs.metadata_editor import MetadataEditorDialog
from iOpenPod.GUI.presentation.artwork_provider import ArtworkPixmapProvider
from iOpenPod.GUI.widgets.artwork_view import ArtworkView
from iOpenPod.GUI.widgets.player_bar import PlayerBar
from iPodDB.library import (
    ArtworkPixels,
    LibrarySnapshot,
    Track,
    TrackChapter,
    TrackMetadata,
)


def _wait_for_color(bar: PlayerBar, expected: QColor) -> None:
    view = bar.findChild(ArtworkView, "playerArtwork")
    assert view is not None
    deadline = monotonic() + 5
    while monotonic() < deadline:
        APPLICATION.processEvents()
        image = view.grab().toImage()
        if image.pixelColor(image.width() // 2, image.height() // 2) == expected:
            return
    raise AssertionError(f"Player never displayed {expected.name()}")


def test_applied_chapter_artwork_previews_before_device_save_and_clears_on_reset() -> (
    None
):
    context = build_context()
    provider = ArtworkPixmapProvider(context.artwork_controller)
    bar = PlayerBar(context.theme_manager, provider)
    bar.resize(1100, bar.height())
    track = Track(
        1,
        "Episode",
        "Host",
        "Series",
        60_000,
        metadata=TrackMetadata(
            chapters=(TrackChapter("Opening", 0), TrackChapter("Interview", 30_000))
        ),
    )
    workspace = context.library_workspace
    workspace.load(LibrarySnapshot((track,)))
    dialog = MetadataEditorDialog(workspace, (1,), artwork_provider=provider)
    try:
        artwork = dialog.findChild(ArtworkEditor)
        assert artwork is not None
        artwork.set_pending_artwork(ArtworkPixels(1, 1, b"\xff\x00\x00"))
        artwork.add_pending_artwork(ArtworkPixels(1, 1, b"\x00\x00\xff"), 30_000)
        dialog.accept()
        edited = workspace.track(1)
        assert edited is not None and edited.artwork_id < 0 and workspace.dirty
        bar.set_track(edited)
        _wait_for_color(bar, QColor("red"))
        bar.set_position(30_000)
        _wait_for_color(bar, QColor("blue"))
        bar.set_position(0)
        _wait_for_color(bar, QColor("red"))
        workspace.load(LibrarySnapshot((track,)))
        assert provider.display_times(edited.artwork_id) == ()
        assert provider.pixmap(edited.artwork_id, 40, 1) is None
        assert not workspace.dirty
    finally:
        dialog.close()
        bar.close()
        provider.shutdown()
        context.shutdown()
