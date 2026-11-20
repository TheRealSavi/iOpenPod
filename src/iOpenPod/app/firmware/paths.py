"""Persistent Host paths for bundled firmware preparation and installation."""

import sys
from pathlib import Path

from storage.host_files import application_data_file


def firmware_directory() -> Path:
    platform = {"win32": "windows", "darwin": "macos", "linux": "linux"}[sys.platform]
    return application_data_file("iOpenPod", "firmware", platform_name=platform)
