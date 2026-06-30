from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from PyQt6.QtCore import QPoint

from GUI.styles import context_menu_css
from GUI.widgets import photoBrowser as photo_browser_module
from GUI.widgets.photoBrowser import PhotoBrowserWidget, _album_display_label
from infrastructure.i18n import set_language
from SyncEngine.photos import PhotoEntry


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


def _patch_menu(monkeypatch, choose_label: str | None = None) -> None:
    _Menu.last = None
    _Menu.choose_label = choose_label
    monkeypatch.setattr("GUI.widgets.photoBrowser.QMenu", _Menu)


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


def test_album_display_label_translates_only_builtin_all_photos() -> None:
    try:
        set_language("zh")

        assert _album_display_label("All Photos") == "所有照片"
        assert _album_display_label("Settings") == "Settings"
    finally:
        set_language("en")


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
