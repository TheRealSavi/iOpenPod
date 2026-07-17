from __future__ import annotations

from pathlib import Path

from iopenpod.gui import system_open


def test_open_files_with_default_app_opens_existing_files(
    monkeypatch,
    tmp_path: Path,
) -> None:
    existing = tmp_path / "Song.mp3"
    missing = tmp_path / "Missing.mp3"
    existing.write_bytes(b"audio")
    opened: list[str] = []

    monkeypatch.setattr(
        system_open.QDesktopServices,
        "openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )

    assert system_open.open_files_with_default_app([existing, missing]) is True
    assert [Path(path) for path in opened] == [existing]


def test_macos_open_with_chooses_one_app_for_multiple_files(
    monkeypatch,
    tmp_path: Path,
) -> None:
    first = tmp_path / "One.mp3"
    second = tmp_path / "Two.mp3"
    first.write_bytes(b"audio")
    second.write_bytes(b"audio")
    launched: list[list[str]] = []

    monkeypatch.setattr(system_open.sys, "platform", "darwin")
    monkeypatch.setattr(
        system_open,
        "_choose_macos_application",
        lambda _parent: "/Applications/Player.app",
    )
    monkeypatch.setattr(
        system_open,
        "_launch_detached",
        lambda command: launched.append(command) or True,
    )

    assert system_open.open_files_with_app_picker([first, second]) is True
    assert launched == [
        [
            "open",
            "-a",
            "/Applications/Player.app",
            str(first),
            str(second),
        ]
    ]


def test_desktop_entry_command_replaces_file_field_code(tmp_path: Path) -> None:
    desktop_file = tmp_path / "player.desktop"
    track_path = tmp_path / "Song.mp3"
    desktop_file.write_text(
        "[Desktop Entry]\nExec=player --new-window %f %i\n",
        encoding="utf-8",
    )

    assert system_open._desktop_entry_command(desktop_file, track_path) == [
        "player",
        "--new-window",
        str(track_path),
    ]


def test_desktop_entry_commands_replaces_multi_file_field_code(tmp_path: Path) -> None:
    desktop_file = tmp_path / "player.desktop"
    first = tmp_path / "One.mp3"
    second = tmp_path / "Two.mp3"
    desktop_file.write_text(
        "[Desktop Entry]\nExec=player --new-window %F %i\n",
        encoding="utf-8",
    )

    assert system_open._desktop_entry_commands(desktop_file, [first, second]) == [
        [
            "player",
            "--new-window",
            str(first),
            str(second),
        ]
    ]


def test_desktop_entry_command_appends_path_without_field_code(tmp_path: Path) -> None:
    desktop_file = tmp_path / "player.desktop"
    track_path = tmp_path / "Song.mp3"
    desktop_file.write_text(
        "[Desktop Entry]\nExec=player --queue\n",
        encoding="utf-8",
    )

    assert system_open._desktop_entry_command(desktop_file, track_path) == [
        "player",
        "--queue",
        str(track_path),
    ]
