from iopenpod.application.jobs import build_imported_photo_edit_state


def test_build_imported_photo_edit_state_skips_empty_imports() -> None:
    assert build_imported_photo_edit_state(()) is None
    assert build_imported_photo_edit_state(None) is None


def test_build_imported_photo_edit_state_tracks_imported_files() -> None:
    imported_files = (
        ("C:/Photos/one.jpg", "Vacation"),
        ("C:/Photos/two.jpg", "Vacation"),
    )

    photo_edits = build_imported_photo_edit_state(imported_files)

    assert photo_edits is not None
    assert photo_edits.imported_files == list(imported_files)
    assert photo_edits.has_changes is True
