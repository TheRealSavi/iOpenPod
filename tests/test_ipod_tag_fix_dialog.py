from types import SimpleNamespace
from typing import Any, cast

from iopenpod.gui.widgets.ipodTagFixDialog import IpodLibraryTagFixDialog


def test_tag_fix_search_matches_symbol_variants() -> None:
    track = {"Title": "John’s Song"}
    dialog = SimpleNamespace(
        _tracks=[track],
        _suggestion=SimpleNamespace(
            changes_by_track={id(track): {"Title": "John’s Song (Live)"}},
        ),
        _selected_field=None,
        _search_text="john's",
        _preview_search_text=lambda *args: IpodLibraryTagFixDialog._preview_search_text(
            cast(Any, dialog),
            *args,
        ),
    )

    rows, count = IpodLibraryTagFixDialog._filtered_preview_rows(cast(Any, dialog))

    assert count == 1
    assert len(rows) == 1
