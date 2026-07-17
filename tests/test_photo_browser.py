from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from PyQt6.QtCore import QPoint

from iopenpod.device.path_safety import UnsafeDevicePathError
from iopenpod.gui.styles import context_menu_css
from iopenpod.gui.widgets import photoBrowser as photo_browser_module
from iopenpod.gui.widgets.photoBrowser import PhotoBrowserWidget
from iopenpod.gui.widgets.photoViewer import PhotoViewerPane
from iopenpod.sync.photos import PhotoEntry


def test_photo_viewer_action_buttons_collapse_to_glyphs_when_narrow(qtbot):
    viewer = PhotoViewerPane(heading="")
    qtbot.addWidget(viewer)
    buttons = viewer.configureActionRow(
        [
            ("export", "Export", "download", False),
            ("add", "Add to Album", "plus", False),
            ("remove", "Remove from Album", "minus", False),
            ("delete", "Delete Photo", "trash", True),
        ]
    )

    viewer.resize(320, 500)
    viewer.show()
    qtbot.wait(50)

    assert all(button.text() == "" for button in buttons.values())
    assert buttons["add"].toolTip() == "Add to Album"
    assert all(button.width() == 32 for button in buttons.values())

    viewer.resize(900, 500)
    qtbot.wait(50)

    assert buttons["add"].text() == "Add to Album"
    assert buttons["remove"].text() == "Remove from Album"


class _Action:
    def __init__(self, label: str) -> None:
        self.label = label
        self._enabled = True

    def setIcon(self, _icon) -> None:
        pass

    def setEnabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def isEnabled(self) -> bool:
        return self._enabled


class _Menu:
    last: _Menu | None = None
    choose_label: str | None = None

    def __init__(self, _parent) -> None:
        self.actions: list[_Action] = []
        self._style = ""
        self.exec_pos = None
        _Menu.last = self

    def setStyleSheet(self, style: str) -> None:
        self._style = style

    def styleSheet(self) -> str:
        return self._style

    def addAction(self, label: str) -> _Action:
        action = _Action(label)
        self.actions.append(action)
        return action

    def addSeparator(self) -> None:
        pass

    def exec(self, pos: QPoint):
        self.exec_pos = pos
        for action in self.actions:
            if action.label == self.choose_label:
                return action
        return None

    def action(self, label: str) -> _Action:
        return next(action for action in self.actions if action.label == label)


def _allow_photo_write(monkeypatch) -> None:
    profile = object()

    class _Guard:
        def __init__(self, _root, *, volume_key: str):
            assert volume_key == "test-volume"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(
        photo_browser_module,
        "inspect_device_write_readiness",
        lambda *_args, **_kwargs: profile,
    )
    monkeypatch.setattr(
        photo_browser_module,
        "revalidate_device_write_readiness",
        lambda retained: retained,
    )
    monkeypatch.setattr(
        photo_browser_module,
        "volume_lock_key",
        lambda _profile: "test-volume",
    )
    monkeypatch.setattr(photo_browser_module, "DeviceWriteGuard", _Guard)


def _patch_menu(monkeypatch, choose_label: str | None = None) -> None:
    _Menu.last = None
    _Menu.choose_label = choose_label
    monkeypatch.setattr("iopenpod.gui.widgets.photoBrowser.QMenu", _Menu)


def _photo(**values):
    defaults = {
        "image_id": 101,
        "album_names": {"Vacation"},
    }
    defaults.update(values)
    return SimpleNamespace(**defaults)


def _attach_menu_action_helper(browser: SimpleNamespace) -> None:
    browser._add_menu_action = (
        lambda menu, label, **kwargs: PhotoBrowserWidget._add_menu_action(
            cast(Any, browser),
            menu,
            label,
            **kwargs,
        )
    )


def test_photo_search_matches_symbol_variants() -> None:
    photo = PhotoEntry(
        image_id=101,
        display_name="John’s Photo.jpg",
        full_res_path="Full Resolution/John’s Photo.jpg",
    )
    browser = SimpleNamespace(
        _search_query="john's",
        _device_photo_title=lambda value: value.display_name,
        _device_storage_size=lambda _value: 0,
        _photo_format_ids=lambda _value: (),
    )

    assert PhotoBrowserWidget._matches_search(cast(Any, browser), photo)


def test_sync_running_check_does_not_recurse_before_widget_is_attached() -> None:
    browser = SimpleNamespace()
    browser.window = lambda: browser
    browser._is_sync_running = lambda: PhotoBrowserWidget._is_sync_running(
        cast(Any, browser)
    )

    assert PhotoBrowserWidget._is_sync_running(cast(Any, browser)) is False


def test_photo_context_menu_uses_shared_style_and_disables_invalid_add(monkeypatch):
    _patch_menu(monkeypatch)
    pos = QPoint(12, 34)
    browser = SimpleNamespace(
        _filtered_items=[(101, _photo())],
        photo_grid=SimpleNamespace(setCurrentIndex=lambda _index: None),
        _photo_actions_locked=lambda: False,
        _available_album_targets=lambda _photo: [],
        _selected_album_target=lambda: "",
        _set_menu_icon=lambda *_args: None,
        _add_to_album=lambda: None,
        _remove_from_album=lambda: None,
        _delete_photo=lambda: None,
    )
    _attach_menu_action_helper(browser)

    PhotoBrowserWidget._on_photo_context_requested(
        cast(Any, browser),
        101,
        0,
        pos,
    )

    assert _Menu.last is not None
    assert _Menu.last.styleSheet() == context_menu_css()
    assert _Menu.last.exec_pos == pos
    assert _Menu.last.action("Add to Album").isEnabled() is False
    assert _Menu.last.action("Delete Photo").isEnabled() is True


def test_photo_context_menu_delete_dispatches_current_photo_action(monkeypatch):
    _patch_menu(monkeypatch, choose_label="Delete Photo")
    calls: list[str] = []
    browser = SimpleNamespace(
        _filtered_items=[(101, _photo())],
        photo_grid=SimpleNamespace(setCurrentIndex=lambda _index: None),
        _photo_actions_locked=lambda: False,
        _available_album_targets=lambda _photo: [],
        _selected_album_target=lambda: "",
        _set_menu_icon=lambda *_args: None,
        _add_to_album=lambda: calls.append("add"),
        _remove_from_album=lambda: calls.append("remove"),
        _delete_photo=lambda: calls.append("delete"),
    )
    _attach_menu_action_helper(browser)

    PhotoBrowserWidget._on_photo_context_requested(
        cast(Any, browser),
        101,
        0,
        QPoint(1, 2),
    )

    assert calls == ["delete"]


def test_photo_context_menu_export_dispatches_current_photo_action(monkeypatch):
    _patch_menu(monkeypatch, choose_label="Export Photo...")
    calls: list[str] = []
    browser = SimpleNamespace(
        _filtered_items=[(101, _photo())],
        photo_grid=SimpleNamespace(setCurrentIndex=lambda _index: None),
        _photo_actions_locked=lambda: False,
        _available_album_targets=lambda _photo: [],
        _selected_album_target=lambda: "",
        _set_menu_icon=lambda *_args: None,
        _export_current_photo=lambda: calls.append("export"),
        _add_to_album=lambda: calls.append("add"),
        _remove_from_album=lambda: calls.append("remove"),
        _delete_photo=lambda: calls.append("delete"),
    )
    _attach_menu_action_helper(browser)

    PhotoBrowserWidget._on_photo_context_requested(
        cast(Any, browser),
        101,
        0,
        QPoint(1, 2),
    )

    assert calls == ["export"]


def test_photo_context_menu_rename_dispatches_current_photo_action(monkeypatch):
    _patch_menu(monkeypatch, choose_label="Rename Photo")
    calls: list[str] = []
    browser = SimpleNamespace(
        _filtered_items=[(101, _photo())],
        photo_grid=SimpleNamespace(setCurrentIndex=lambda _index: None),
        _photo_actions_locked=lambda: False,
        _available_album_targets=lambda _photo: [],
        _selected_album_target=lambda: "",
        _set_menu_icon=lambda *_args: None,
        _rename_photo=lambda: calls.append("rename"),
        _add_to_album=lambda: calls.append("add"),
        _remove_from_album=lambda: calls.append("remove"),
        _delete_photo=lambda: calls.append("delete"),
    )
    _attach_menu_action_helper(browser)

    PhotoBrowserWidget._on_photo_context_requested(
        cast(Any, browser),
        101,
        0,
        QPoint(1, 2),
    )

    assert calls == ["rename"]


def test_photo_write_worker_renames_full_resolution_file_and_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _allow_photo_write(monkeypatch)
    root = tmp_path / "ipod"
    old_path = root / "Photos" / "Full Resolution" / "old_name.jpg"
    old_path.parent.mkdir(parents=True)
    old_path.write_bytes(b"photo")
    photodb = photo_browser_module.PhotoDB(
        photos={
            101: PhotoEntry(
                image_id=101,
                display_name="old_name.jpg",
                full_res_path="Full Resolution/old_name.jpg",
            )
        }
    )
    written: list[PhotoEntry] = []

    def fake_write(_root, db, **_kwargs):
        written.append(db.photos[101])

    monkeypatch.setattr(photo_browser_module, "write_photo_db_metadata_only", fake_write)
    worker = photo_browser_module._PhotoWriteWorker(
        str(root),
        photodb,
        "rename_photo",
        image_id=101,
        new_name="Sunset",
    )
    worker.run()

    renamed = root / "Photos" / "Full Resolution" / "Sunset.jpg"
    assert renamed.read_bytes() == b"photo"
    assert not old_path.exists()
    assert written[0].display_name == "Sunset.jpg"
    assert written[0].full_res_path == "Full Resolution/Sunset.jpg"


def test_photo_write_worker_rejects_rename_collision(monkeypatch, tmp_path: Path) -> None:
    _allow_photo_write(monkeypatch)
    root = tmp_path / "ipod"
    photo_dir = root / "Photos" / "Full Resolution"
    photo_dir.mkdir(parents=True)
    old_path = photo_dir / "old_name.jpg"
    old_path.write_bytes(b"old")
    (photo_dir / "Sunset.jpg").write_bytes(b"existing")
    photodb = photo_browser_module.PhotoDB(
        photos={
            101: PhotoEntry(
                image_id=101,
                display_name="old_name.jpg",
                full_res_path="Full Resolution/old_name.jpg",
            )
        }
    )
    errors: list[str] = []
    worker = photo_browser_module._PhotoWriteWorker(
        str(root), photodb, "rename_photo", image_id=101, new_name="Sunset"
    )
    worker.failed.connect(errors.append)
    worker.run()

    assert errors and "already exists" in errors[0]
    assert old_path.read_bytes() == b"old"


def test_photo_write_worker_rolls_back_file_and_metadata_on_write_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _allow_photo_write(monkeypatch)
    root = tmp_path / "ipod"
    old_path = root / "Photos" / "Full Resolution" / "old_name.jpg"
    old_path.parent.mkdir(parents=True)
    old_path.write_bytes(b"photo")
    db_path = root / "Photos" / "Photo Database"
    db_path.write_bytes(b"old-db")
    predictable_restore_temp = db_path.with_name(f".{db_path.name}.restore-tmp")
    predictable_restore_temp.write_bytes(b"do-not-truncate")
    photodb = photo_browser_module.PhotoDB(
        photos={
            101: PhotoEntry(
                image_id=101,
                display_name="old_name.jpg",
                full_res_path="Full Resolution/old_name.jpg",
            )
        }
    )

    def fake_write(_root, _db, **_kwargs):
        db_path.write_bytes(b"new-db")
        raise OSError("mapping disk full")

    monkeypatch.setattr(photo_browser_module, "write_photo_db_metadata_only", fake_write)
    errors: list[str] = []
    worker = photo_browser_module._PhotoWriteWorker(
        str(root), photodb, "rename_photo", image_id=101, new_name="Sunset"
    )
    worker.failed.connect(errors.append)
    worker.run()

    assert errors
    assert old_path.read_bytes() == b"photo"
    assert not (old_path.parent / "Sunset.jpg").exists()
    assert db_path.read_bytes() == b"old-db"
    assert predictable_restore_temp.read_bytes() == b"do-not-truncate"


def test_photo_write_worker_allows_case_only_rename(monkeypatch, tmp_path: Path) -> None:
    _allow_photo_write(monkeypatch)
    monkeypatch.setattr(
        photo_browser_module.os.path,
        "normcase",
        lambda value: str(value).lower(),
    )
    root = tmp_path / "ipod"
    old_path = root / "Photos" / "Full Resolution" / "sunset.jpg"
    old_path.parent.mkdir(parents=True)
    old_path.write_bytes(b"photo")
    predictable_rename_temp = old_path.with_name(f".{old_path.name}.rename-tmp")
    predictable_rename_temp.write_bytes(b"do-not-delete")
    photodb = photo_browser_module.PhotoDB(
        photos={
            101: PhotoEntry(
                image_id=101,
                display_name="sunset.jpg",
                full_res_path="Full Resolution/sunset.jpg",
            )
        }
    )
    monkeypatch.setattr(
        photo_browser_module,
        "write_photo_db_metadata_only",
        lambda *_args, **_kwargs: None,
    )
    worker = photo_browser_module._PhotoWriteWorker(
        str(root), photodb, "rename_photo", image_id=101, new_name="Sunset"
    )
    worker.run()

    assert (old_path.parent / "Sunset.jpg").read_bytes() == b"photo"
    assert predictable_rename_temp.read_bytes() == b"do-not-delete"


@pytest.mark.parametrize("path_kind", ["absolute", "traversal"])
def test_device_full_res_path_rejects_database_path_escape(
    tmp_path: Path,
    path_kind: str,
) -> None:
    root = tmp_path / "ipod"
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"outside")
    full_res_path = (
        str(outside)
        if path_kind == "absolute"
        else "Full Resolution/../../../outside.jpg"
    )

    with pytest.raises(UnsafeDevicePathError):
        photo_browser_module._device_full_res_path(
            root,
            PhotoEntry(image_id=101, full_res_path=full_res_path),
        )


def test_photo_write_worker_checks_readiness_and_guard_before_each_mutation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "ipod"
    full_res = root / "Photos" / "Full Resolution" / "photo.jpg"
    full_res.parent.mkdir(parents=True)
    full_res.write_bytes(b"photo")
    photodb = photo_browser_module.PhotoDB(
        photos={
            101: PhotoEntry(
                image_id=101,
                full_res_path="Full Resolution/photo.jpg",
            )
        }
    )
    profile = object()
    events: list[str] = []

    class _Guard:
        def __init__(self, _root, *, volume_key: str):
            assert volume_key == "volume-key"

        def __enter__(self):
            events.append("guard_enter")
            return self

        def __exit__(self, *_args):
            events.append("guard_exit")

    def inspect(_root, *, reported_volume_format: str = ""):
        assert reported_volume_format == "FAT32"
        events.append("inspect")
        return profile

    def revalidate(retained):
        assert retained is profile
        events.append("revalidate")
        return profile

    def durable_unlink(path, *, missing_ok: bool = False):
        events.append("unlink")
        Path(path).unlink(missing_ok=missing_ok)

    def commit(*_args, before_device_mutation, **_kwargs):
        before_device_mutation()
        events.append("commit")

    monkeypatch.setattr(
        photo_browser_module,
        "inspect_device_write_readiness",
        inspect,
        raising=False,
    )
    monkeypatch.setattr(
        photo_browser_module,
        "revalidate_device_write_readiness",
        revalidate,
        raising=False,
    )
    monkeypatch.setattr(
        photo_browser_module,
        "volume_lock_key",
        lambda retained: "volume-key",
        raising=False,
    )
    monkeypatch.setattr(photo_browser_module, "DeviceWriteGuard", _Guard, raising=False)
    monkeypatch.setattr(
        photo_browser_module,
        "durable_unlink",
        durable_unlink,
        raising=False,
    )
    monkeypatch.setattr(
        photo_browser_module,
        "write_photo_db_metadata_only",
        commit,
    )

    worker = photo_browser_module._PhotoWriteWorker(
        str(root),
        photodb,
        "delete_photo",
        image_id=101,
        reported_volume_format="FAT32",
    )
    worker.run()

    assert events == [
        "inspect",
        "guard_enter",
        "revalidate",
        "unlink",
        "revalidate",
        "revalidate",
        "commit",
        "guard_exit",
    ]


def test_photo_write_worker_stops_when_mounted_volume_identity_changed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "ipod"
    profile = object()
    errors: list[str] = []
    commits: list[object] = []

    monkeypatch.setattr(
        photo_browser_module,
        "inspect_device_write_readiness",
        lambda *_args, **_kwargs: profile,
    )
    monkeypatch.setattr(
        photo_browser_module,
        "volume_lock_key",
        lambda _profile: "replacement-volume",
    )
    monkeypatch.setattr(
        photo_browser_module,
        "DeviceWriteGuard",
        lambda *_args, **_kwargs: pytest.fail("writer guard must not be acquired"),
    )
    monkeypatch.setattr(
        photo_browser_module,
        "write_photo_db_metadata_only",
        lambda *_args, **_kwargs: commits.append(object()),
    )

    worker = photo_browser_module._PhotoWriteWorker(
        str(root),
        photo_browser_module.PhotoDB(),
        "create_album",
        album_name="Vacation",
        expected_volume_identity_key="original-volume",
    )
    worker.failed.connect(errors.append)
    worker.run()

    assert commits == []
    assert errors and "volume changed" in errors[0]


def test_album_context_menu_export_targets_right_clicked_album(monkeypatch):
    _patch_menu(monkeypatch, choose_label="Export Album...")
    calls: list[tuple[str, str]] = []
    browser = SimpleNamespace(
        _photo_actions_locked=lambda: False,
        _photos_for_album_target=lambda _album: [_photo()],
        _set_menu_icon=lambda *_args: None,
        _export_album_target=lambda album: calls.append(("export", album)),
        _create_album=lambda: calls.append(("new", "")),
        _rename_album_target=lambda album: calls.append(("rename", album)),
        _delete_album_target=lambda album: calls.append(("delete", album)),
    )
    _attach_menu_action_helper(browser)

    PhotoBrowserWidget._on_album_context_requested(
        cast(Any, browser),
        "Vacation",
        QPoint(4, 5),
    )

    assert calls == [("export", "Vacation")]


def test_album_context_menu_rename_targets_right_clicked_album(monkeypatch):
    _patch_menu(monkeypatch, choose_label="Rename Album")
    calls: list[tuple[str, str]] = []
    browser = SimpleNamespace(
        _photo_actions_locked=lambda: False,
        _photos_for_album_target=lambda _album: [_photo()],
        _set_menu_icon=lambda *_args: None,
        _create_album=lambda: calls.append(("new", "")),
        _rename_album_target=lambda album: calls.append(("rename", album)),
        _delete_album_target=lambda album: calls.append(("delete", album)),
    )
    _attach_menu_action_helper(browser)

    PhotoBrowserWidget._on_album_context_requested(
        cast(Any, browser),
        "Vacation",
        QPoint(4, 5),
    )

    assert calls == [("rename", "Vacation")]


def test_album_context_menu_disables_album_actions_while_locked(monkeypatch):
    _patch_menu(monkeypatch, choose_label="Delete Album")
    calls: list[tuple[str, str]] = []
    browser = SimpleNamespace(
        _photo_actions_locked=lambda: True,
        _photos_for_album_target=lambda _album: [_photo()],
        _set_menu_icon=lambda *_args: None,
        _create_album=lambda: calls.append(("new", "")),
        _rename_album_target=lambda album: calls.append(("rename", album)),
        _delete_album_target=lambda album: calls.append(("delete", album)),
    )
    _attach_menu_action_helper(browser)

    PhotoBrowserWidget._on_album_context_requested(
        cast(Any, browser),
        "Vacation",
        QPoint(4, 5),
    )

    assert _Menu.last is not None
    assert _Menu.last.action("New Album").isEnabled() is False
    assert _Menu.last.action("Rename Album").isEnabled() is False
    assert _Menu.last.action("Delete Album").isEnabled() is False
    assert calls == []


def test_export_photo_to_path_prefers_full_res_jpeg(tmp_path: Path) -> None:
    from PIL import Image

    ipod_root = tmp_path / "ipod"
    full_res = ipod_root / "Photos" / "Full Resolution" / "iOpenPod" / "source.jpg"
    full_res.parent.mkdir(parents=True)
    Image.new("RGB", (3, 2), (12, 34, 56)).save(full_res, format="JPEG")
    photo = PhotoEntry(
        image_id=101,
        full_res_path="Full Resolution/iOpenPod/source.jpg",
    )

    target = tmp_path / "exported.jpg"

    result = photo_browser_module._export_photo_to_path(photo, ipod_root, target)

    assert result == target
    with Image.open(target) as exported:
        assert exported.format == "JPEG"
        assert exported.size == (3, 2)


def test_export_photo_to_path_decodes_preview_as_normal_png(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from PIL import Image

    monkeypatch.setattr(
        photo_browser_module,
        "load_photo_preview",
        lambda *_args, **_kwargs: Image.new("RGBA", (2, 2), (10, 20, 30, 128)),
    )
    photo = PhotoEntry(image_id=102)

    target = tmp_path / "exported.png"

    result = photo_browser_module._export_photo_to_path(photo, tmp_path, target)

    assert result == target
    with Image.open(target) as exported:
        assert exported.format == "PNG"
        assert exported.mode == "RGBA"
        assert exported.size == (2, 2)


def test_export_targets_for_photos_avoid_name_collisions(tmp_path: Path) -> None:
    browser = SimpleNamespace(
        _device_photo_title=lambda photo: photo.display_name,
    )
    browser._unique_export_path = (
        lambda folder, filename, used: PhotoBrowserWidget._unique_export_path(
            cast(Any, browser),
            folder,
            filename,
            used,
        )
    )
    photos = [
        PhotoEntry(image_id=101, display_name="Beach.jpg"),
        PhotoEntry(image_id=102, display_name="Beach.jpg"),
    ]

    exports = PhotoBrowserWidget._export_targets_for_photos(
        cast(Any, browser),
        photos,
        tmp_path,
    )

    assert [Path(target).name for _photo, target in exports] == [
        "Beach.jpg",
        "Beach (2).jpg",
    ]
