# pyright: strict, reportPrivateUsage=false
"""Exercise the Linux eject adapter against the published UDisks D-Bus API."""

from xml.etree import ElementTree

import pytest

from storage import EjectError, UnsupportedStorageOperationError
from storage.platform.linux_eject import (
    LinuxDeviceEjector,
    UDisksError,
    _QtUDisksClient,
)

_ROOT = "/org/freedesktop/UDisks2"
_DRIVE = _ROOT + "/drives/selected"
_BLOCK = _ROOT + "/block_devices/sdb1"


class _Reply:
    def __init__(self, value: object) -> None:
        self.value = value

    def arguments(self) -> list[object]:
        return [self.value]


class _ServiceClient(_QtUDisksClient):
    """Keep the real client policy and substitute only the D-Bus transport."""

    def __init__(self) -> None:
        self.objects: dict[str, dict[str, dict[str, object]]] = {
            _DRIVE: {self._DRIVE: {"CanPowerOff": True, "SiblingId": "usb-device"}},
            _BLOCK: {
                self._BLOCK: {"Drive": _DRIVE},
                self._FILESYSTEM: {"MountPoints": [b"/media/selected\0"]},
            },
        }
        self.mutations: list[tuple[str, str]] = []
        self.inventory_reply: _Reply | None = None
        self.errors: dict[tuple[str, str], UDisksError] = {}

    def _call(
        self,
        path: str,
        interface: str,
        method: str,
        *arguments: object,
        timeout_ms: int = 30_000,
    ) -> object:
        if error := self.errors.get((path, method)):
            raise error
        if interface == self._MANAGER:
            assert path == _ROOT + "/Manager"
            if method == "ResolveDevice":
                assert arguments == ({"path": "/dev/sdb1"}, {})
                return _Reply([_BLOCK])
            if method == "GetBlockDevices":
                assert arguments == ({},)
                return _Reply(
                    [key for key, value in self.objects.items() if self._BLOCK in value]
                )
            # Manager.GetDrives is absent before UDisks 2.11 (issue #313).
            raise UDisksError("org.freedesktop.DBus.Error.UnknownMethod", method)
        if interface == "org.freedesktop.DBus.Introspectable":
            assert (path, method, arguments) == (_ROOT + "/drives", "Introspect", ())
            if self.inventory_reply is not None:
                return self.inventory_reply
            node = ElementTree.Element("node", name=path)
            for key, value in self.objects.items():
                if self._DRIVE in value:
                    ElementTree.SubElement(node, "node", name=key.rsplit("/", 1)[1])
            return _Reply(ElementTree.tostring(node, encoding="unicode"))
        if interface == self._PROPERTIES:
            assert method == "Get" and len(arguments) == 2
            target_interface, name = arguments
            assert isinstance(target_interface, str) and isinstance(name, str)
            try:
                return _Reply(self.objects[path][target_interface][name])
            except KeyError as error:
                raise UDisksError(
                    "org.freedesktop.DBus.Error.UnknownProperty", name
                ) from error
        assert (interface, method) in {
            (self._FILESYSTEM, "Unmount"),
            (self._DRIVE, "PowerOff"),
        }
        assert arguments == ({},)
        self.mutations.append((path, method))
        return _Reply(None)


def test_eject_with_nonempty_sibling_id_uses_supported_udisks_api() -> None:
    client = _ServiceClient()

    result = LinuxDeviceEjector(client).eject("/dev/sdb1")

    assert "powered off" in result.detail
    assert client.mutations == [(_BLOCK, "Unmount"), (_DRIVE, "PowerOff")]


def test_eject_checks_other_drives_and_unmounts_only_target_filesystems() -> None:
    client = _ServiceClient()
    other_drive = _ROOT + "/drives/unrelated"
    client.objects[other_drive] = {client._DRIVE: {"SiblingId": "other-usb-device"}}
    client.objects[_BLOCK + "_other"] = {
        client._BLOCK: {"Drive": other_drive},
        client._FILESYSTEM: {"MountPoints": [b"/media/other\0"]},
    }
    client.objects[_BLOCK + "_second"] = {
        client._BLOCK: {"Drive": _DRIVE},
        client._FILESYSTEM: {"MountPoints": [b"/media/second\0"]},
    }
    client.objects[_BLOCK + "_unmounted"] = {
        client._BLOCK: {"Drive": _DRIVE},
        client._FILESYSTEM: {"MountPoints": []},
    }
    client.objects[_BLOCK + "_whole_disk"] = {client._BLOCK: {"Drive": _DRIVE}}

    LinuxDeviceEjector(client).eject("/dev/sdb1")

    assert client.mutations == [
        (_BLOCK, "Unmount"),
        (_BLOCK + "_second", "Unmount"),
        (_DRIVE, "PowerOff"),
    ]


def test_shared_power_off_is_refused_even_when_sibling_has_no_block_device() -> None:
    client = _ServiceClient()
    client.objects[_ROOT + "/drives/empty_reader"] = {
        client._DRIVE: {"SiblingId": "usb-device"}
    }

    with pytest.raises(UnsupportedStorageOperationError, match="other media"):
        LinuxDeviceEjector(client).eject("/dev/sdb1")

    assert client.mutations == []


def test_empty_sibling_id_does_not_group_unrelated_drives() -> None:
    client = _ServiceClient()
    client.objects[_DRIVE][client._DRIVE]["SiblingId"] = ""
    client.objects[_ROOT + "/drives/unrelated"] = {client._DRIVE: {"SiblingId": ""}}

    LinuxDeviceEjector(client).eject("/dev/sdb1")

    assert client.mutations == [(_BLOCK, "Unmount"), (_DRIVE, "PowerOff")]


@pytest.mark.parametrize("drive_name", ["selected", "other"])
@pytest.mark.parametrize("sibling_id", [None, 42, [], {}])
def test_invalid_sibling_property_is_not_evidence_of_no_siblings(
    drive_name: str, sibling_id: object
) -> None:
    client = _ServiceClient()
    properties = client.objects.setdefault(
        _ROOT + "/drives/" + drive_name, {}
    ).setdefault(client._DRIVE, {})
    properties["SiblingId"] = sibling_id

    with pytest.raises(UnsupportedStorageOperationError, match="Drive inventory"):
        LinuxDeviceEjector(client).eject("/dev/sdb1")

    assert client.mutations == []


@pytest.mark.parametrize(
    "reply",
    [
        None,
        {},
        "not XML",
        "<interface/>",
        '<node name="/wrong"><node name="selected"/></node>',
        "<node/>",
        '<node><node name="other"/></node>',
        '<node><node name="selected"/><node/></node>',
        '<node><node name="selected"/><node name="../other"/></node>',
        '<node><node name="selected"/><node name="nested/other"/></node>',
        '<node><node name="selected"/><node name="selected"/></node>',
    ],
)
def test_incomplete_or_malformed_inventory_stops_before_unmount(reply: object) -> None:
    client = _ServiceClient()
    client.inventory_reply = _Reply(reply)

    with pytest.raises(UnsupportedStorageOperationError, match="Drive inventory"):
        LinuxDeviceEjector(client).eject("/dev/sdb1")

    assert client.mutations == []


def test_introspection_with_doctype_and_omitted_root_name_is_supported() -> None:
    client = _ServiceClient()
    client.inventory_reply = _Reply(
        '<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN" '
        '"http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">'
        '<node><interface name="org.freedesktop.DBus.Introspectable"/>'
        '<node name="selected"/></node>'
    )

    LinuxDeviceEjector(client).eject("/dev/sdb1")

    assert client.mutations == [(_BLOCK, "Unmount"), (_DRIVE, "PowerOff")]


@pytest.mark.parametrize("method", ["Introspect", "Get"])
def test_inventory_read_errors_stop_before_unmount(method: str) -> None:
    client = _ServiceClient()
    other_drive = _ROOT + "/drives/other"
    client.objects[other_drive] = {client._DRIVE: {"SiblingId": "other-usb-device"}}
    path = _ROOT + "/drives" if method == "Introspect" else other_drive
    client.errors[path, method] = UDisksError(
        "org.freedesktop.DBus.Error.NoReply", "service did not reply"
    )

    with pytest.raises(EjectError, match="service did not reply") as raised:
        LinuxDeviceEjector(client).eject("/dev/sdb1")

    assert raised.value.volume_unmounted is False
    assert client.mutations == []


def test_power_off_authorization_failure_retains_partial_eject_state() -> None:
    client = _ServiceClient()
    client.errors[_DRIVE, "PowerOff"] = UDisksError(
        "org.freedesktop.UDisks2.Error.NotAuthorized", "denied"
    )

    with pytest.raises(EjectError, match="authorization was denied") as raised:
        LinuxDeviceEjector(client).eject("/dev/sdb1")

    assert raised.value.volume_unmounted is True
    assert client.mutations == [(_BLOCK, "Unmount")]
