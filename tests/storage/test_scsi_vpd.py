"""Deterministic SCSI VPD collection independent of a native Host."""

from storage import HardwareProbeObservation, ScsiVpdPagePlan
from storage.scsi_vpd import collect_scsi_vpd


def _vpd(page: int, payload: bytes) -> bytes:
    return bytes((0, page, 0, len(payload))) + payload


def test_scsi_vpd_collects_standard_identity_serial_and_vendor_payload() -> None:
    standard = bytearray(96)
    standard[8:16] = b"Apple   "
    standard[16:32] = b"iPod            "
    standard[32:36] = b"2.01"
    responses = {
        (False, 0): bytes(standard),
        (True, 0x80): _vpd(0x80, b"8P840FN62C7\x00"),
        (True, 0xC0): _vpd(0xC0, bytes((0x80, 0xC2, 0xC3))),
        (True, 0xC2): _vpd(0xC2, b"<?xml version='1.0'?><plist>"),
        (True, 0xC3): _vpd(0xC3, b"<dict></dict></plist>\x00"),
    }

    def inquiry(*, evpd: bool, page: int, alloc_len: int) -> bytes:
        assert alloc_len > 0
        return responses[(evpd, page)]

    observation = collect_scsi_vpd(
        inquiry,
        source="test_scsi",
        page_plan=ScsiVpdPagePlan(0xC0, 0xC2, 0xFF, True),
    )

    assert observation == HardwareProbeObservation(
        source="test_scsi",
        vendor="Apple",
        product="iPod",
        firmware_revision="2.01",
        unit_serial="8P840FN62C7",
        vendor_payload=(b"<?xml version='1.0'?><plist><dict></dict></plist>"),
    )
