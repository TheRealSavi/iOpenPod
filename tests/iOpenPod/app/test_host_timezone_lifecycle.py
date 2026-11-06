"""Application activation refreshes Host calendars without touching iPod evidence."""

import pytest
from PySide6.QtCore import Qt
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.app import (
    _install_host_timezone_refresh,  # pyright: ignore[reportPrivateUsage]
    _refresh_host_timezone_on_activation,  # pyright: ignore[reportPrivateUsage]
)
from iOpenPod.app.core.dates import (
    HostDateZone,
    parse_iso_instant,
    refresh_host_timezone,
)
from iOpenPod.app.metadata_fields import FieldKind, display_value
from iPodDB.device_time import DeviceTimeContext, DeviceTimeSource, mac_to_unix


def test_activation_refreshes_display_and_editor_zone_but_not_captured_device_zone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = DeviceTimeContext("America/New_York", DeviceTimeSource.PREFERENCES_CITY)
    device_date = mac_to_unix(3_900_000_000, captured)
    try:
        with monkeypatch.context() as patch:
            patch.setenv("TZ", "UTC")
            _install_host_timezone_refresh(APPLICATION)
            try:
                assert display_value(1, FieldKind.DATE) == "1970-01-01T00:00:01+00:00"
                patch.setenv("TZ", "America/New_York")
                APPLICATION.applicationStateChanged.emit(
                    Qt.ApplicationState.ApplicationInactive
                )
                assert display_value(1, FieldKind.DATE) == "1970-01-01T00:00:01+00:00"
                APPLICATION.applicationStateChanged.emit(
                    Qt.ApplicationState.ApplicationActive
                )
                assert display_value(1, FieldKind.DATE) == "1969-12-31T19:00:01-05:00"
                assert (
                    parse_iso_instant(
                        "1970-01-01", naive_zone=HostDateZone.SYSTEM
                    ).timestamp()
                    == 18_000
                )
                assert mac_to_unix(3_900_000_000, captured) == device_date
                patch.setenv("TZ", "Not/A_Zone")
                APPLICATION.applicationStateChanged.emit(
                    Qt.ApplicationState.ApplicationActive
                )
                assert (
                    parse_iso_instant(
                        "1970-01-01", naive_zone=HostDateZone.SYSTEM
                    ).timestamp()
                    == 0
                )
            finally:
                APPLICATION.applicationStateChanged.disconnect(
                    _refresh_host_timezone_on_activation
                )
    finally:
        refresh_host_timezone()
