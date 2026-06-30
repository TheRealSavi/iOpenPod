"""Helpers for opening local files through the operating system."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QFileDialog, QWidget


def open_files_with_default_app(paths: Iterable[str | Path]) -> bool:
    """Open local files with the OS default application for each file type."""

    opened_any = False
    for path in _existing_paths(paths):
        opened_any = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))) or opened_any
    return opened_any


def open_file_with_app_picker(path: str | Path, parent: QWidget | None = None) -> bool:
    """Open one file after forcing the OS/user app picker path."""

    return open_files_with_app_picker([path], parent)


def open_files_with_app_picker(paths: Iterable[str | Path], parent: QWidget | None = None) -> bool:
    """Open files after choosing one application for the whole selection."""

    file_paths = _existing_paths(paths)
    if not file_paths:
        return False

    if sys.platform == "win32" and len(file_paths) == 1:
        return _windows_open_with(file_paths[0])
    if sys.platform == "win32":
        return _windows_open_with_files(file_paths, parent)
    if sys.platform == "darwin":
        return _macos_open_with(file_paths, parent)
    return _linux_open_with(file_paths, parent)


def _existing_paths(paths: Iterable[str | Path]) -> list[Path]:
    return [path for path in (Path(item) for item in paths) if path.is_file()]


def _windows_open_with(path: Path) -> bool:
    try:
        import ctypes

        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "openas",
            str(path),
            None,
            None,
            1,
        )
        return int(result) > 32
    except Exception:
        return False


def _windows_open_with_files(paths: list[Path], parent: QWidget | None) -> bool:
    app_path = _choose_windows_application(parent)
    if not app_path:
        return False
    return _launch_detached([app_path, *(str(path) for path in paths)])


def _choose_windows_application(parent: QWidget | None) -> str:
    start_dir = os.environ.get("ProgramFiles", "C:\\")
    selected, _ = QFileDialog.getOpenFileName(
        parent,
        "Open With",
        start_dir,
        "Applications (*.exe);;All Files (*)",
    )
    return selected


def _macos_open_with(paths: list[Path], parent: QWidget | None) -> bool:
    app_path = _choose_macos_application(parent)
    if not app_path:
        return False
    return _launch_detached(["open", "-a", app_path, *(str(path) for path in paths)])


def _choose_macos_application(parent: QWidget | None) -> str:
    selected, _ = QFileDialog.getOpenFileName(
        parent,
        "Open With",
        "/Applications",
        "Applications (*.app);;All Files (*)",
    )
    return selected


def _linux_open_with(paths: list[Path], parent: QWidget | None) -> bool:
    if len(paths) == 1 and _linux_portal_open_with(paths[0]):
        return True

    app_path = _choose_linux_application(parent)
    if not app_path:
        return False

    selected = Path(app_path)
    if selected.suffix == ".desktop":
        commands = _desktop_entry_commands(selected, paths)
        return _launch_detached_commands(commands)

    return _launch_detached([str(selected), *(str(path) for path in paths)])


def _linux_portal_open_with(path: Path) -> bool:
    gdbus = shutil.which("gdbus")
    if not gdbus:
        return False

    uri = QUrl.fromLocalFile(str(path)).toString()
    return _launch_detached(
        [
            gdbus,
            "call",
            "--session",
            "--dest",
            "org.freedesktop.portal.Desktop",
            "--object-path",
            "/org/freedesktop/portal/desktop",
            "--method",
            "org.freedesktop.portal.OpenURI.OpenURI",
            "",
            uri,
            "{'ask': <true>}",
        ]
    )


def _choose_linux_application(parent: QWidget | None) -> str:
    start_dir = "/usr/share/applications" if Path("/usr/share/applications").is_dir() else "/usr/bin"
    selected, _ = QFileDialog.getOpenFileName(
        parent,
        "Open With",
        start_dir,
        "Applications (*.desktop);;Executables (*)",
    )
    return selected


def _desktop_entry_command(desktop_file: Path, path: Path) -> list[str] | None:
    commands = _desktop_entry_commands(desktop_file, [path])
    return commands[0] if commands else None


def _desktop_entry_commands(desktop_file: Path, paths: list[Path]) -> list[list[str]]:
    try:
        lines = desktop_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    exec_line = ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Exec="):
            exec_line = stripped.removeprefix("Exec=").strip()
            break
    if not exec_line:
        return []

    try:
        parts = shlex.split(exec_line)
    except ValueError:
        return []
    if not parts:
        return []

    command: list[str] = []
    inserted_path = False
    single_file_field = False
    for part in parts:
        if part in ("%F", "%U"):
            command.extend(str(path) for path in paths)
            inserted_path = True
        elif part in ("%f", "%u"):
            command.append(str(paths[0]))
            inserted_path = True
            single_file_field = len(paths) > 1
        elif "%" in part:
            continue
        else:
            command.append(part)

    if not inserted_path:
        command.extend(str(path) for path in paths)
    if not single_file_field:
        return [command]

    commands = [command]
    for path in paths[1:]:
        one_file_command: list[str] = []
        for part in parts:
            if part in ("%f", "%u", "%F", "%U"):
                one_file_command.append(str(path))
            elif "%" in part:
                continue
            else:
                one_file_command.append(part)
        commands.append(one_file_command)
    return commands


def _launch_detached_commands(commands: list[list[str]]) -> bool:
    if not commands:
        return False
    launched = [_launch_detached(command) for command in commands]
    return all(launched)


def _launch_detached(command: list[str]) -> bool:
    if not command:
        return False
    try:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=os.name != "nt",
        )
        return True
    except OSError:
        return False
