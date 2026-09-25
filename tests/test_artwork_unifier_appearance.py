from PIL import Image

from iopenpod.gui.styles import paint_css
from iopenpod.gui.widgets.artworkUnifier import (
    ArtworkUnifyChoice,
    ArtworkUnifyContext,
    UnifyArtworkDialog,
)


def test_artwork_unifier_dialog_uses_resolved_modal_and_control_paints(qtbot) -> None:
    choice = ArtworkUnifyChoice(
        digest="example",
        image=Image.new("RGBA", (4, 4), "red"),
        source_img_id=1,
        source_label="Artwork 1",
        first_track_title="Example",
        first_track_index=0,
        track_count=1,
    )
    dialog = UnifyArtworkDialog(
        ArtworkUnifyContext(
            title="Album",
            tracks=[{"Title": "Example"}],
            choices=[choice],
            missing_count=0,
        )
    )
    qtbot.addWidget(dialog)

    css = dialog.styleSheet()
    assert paint_css("modal.background") in css
    assert paint_css("surface.default") in css
    assert paint_css("focus.border") in css
