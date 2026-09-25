"""Generic collection of SCSI INQUIRY Vital Product Data observations."""

from __future__ import annotations

from typing import Protocol

from storage.models import HardwareProbeObservation, ScsiVpdPagePlan

_STANDARD_INQUIRY_LENGTH = 96
_VPD_INQUIRY_LENGTH = 255


class ScsiInquiry(Protocol):
    """One platform-specific SCSI INQUIRY transport."""

    def __call__(self, *, evpd: bool, page: int, alloc_len: int) -> bytes: ...


def collect_scsi_vpd(
    inquiry: ScsiInquiry,
    *,
    source: str,
    page_plan: ScsiVpdPagePlan | None = None,
) -> HardwareProbeObservation:
    """Collect standard identity, page 0x80, and explicitly requested pages.

    Platform adapters supply only the transport. A higher layer may provide a
    generic page plan and remains solely responsible for the payload's meaning.
    """

    vendor = ""
    product = ""
    firmware = ""
    try:
        standard = inquiry(
            evpd=False,
            page=0,
            alloc_len=_STANDARD_INQUIRY_LENGTH,
        )
    except OSError:
        standard = b""
    if len(standard) >= 36:
        vendor = _ascii(standard[8:16])
        product = _ascii(standard[16:32])
        firmware = _ascii(standard[32:36])

    try:
        serial_response = inquiry(
            evpd=True,
            page=0x80,
            alloc_len=_VPD_INQUIRY_LENGTH,
        )
    except OSError:
        serial_response = b""
    unit_serial = _ascii(_vpd_payload(serial_response))

    pages = _planned_payload_pages(inquiry, page_plan)
    chunks: list[bytes] = []
    for page in pages:
        try:
            response = inquiry(
                evpd=True,
                page=page,
                alloc_len=_VPD_INQUIRY_LENGTH,
            )
        except OSError:
            continue
        payload = _vpd_payload(response)
        if payload and any(payload):
            chunks.append(payload)

    return HardwareProbeObservation(
        source=source,
        vendor=vendor,
        product=product,
        firmware_revision=firmware,
        unit_serial=unit_serial,
        vendor_payload=b"".join(chunks).rstrip(b"\x00"),
    )


def _planned_payload_pages(
    inquiry: ScsiInquiry,
    plan: ScsiVpdPagePlan | None,
) -> tuple[int, ...]:
    if plan is None:
        return ()
    try:
        response = inquiry(
            evpd=True,
            page=plan.index_page,
            alloc_len=_VPD_INQUIRY_LENGTH,
        )
    except OSError:
        response = b""
    listed = tuple(
        dict.fromkeys(
            page
            for page in _vpd_payload(response)
            if plan.first_data_page <= page <= plan.last_data_page
        )
    )
    if listed:
        return listed
    if plan.scan_range_when_index_empty:
        return tuple(range(plan.first_data_page, plan.last_data_page + 1))
    return ()


def _vpd_payload(response: bytes) -> bytes:
    if len(response) < 4:
        return b""
    length = int.from_bytes(response[2:4], byteorder="big")
    if length <= 0:
        return b""
    return response[4 : 4 + min(length, len(response) - 4)]


def _ascii(payload: bytes) -> str:
    return (
        payload.split(b"\x00", maxsplit=1)[0]
        .decode(
            "ascii",
            errors="replace",
        )
        .strip()
    )
