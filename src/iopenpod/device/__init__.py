"""
ipod_device — unified iPod device identification & management package.

Re-exports device-identification and model-capability APIs that were
historically spread across multiple legacy modules.
"""

# flake8: noqa: F401

# ── artwork ──────────────────────────────────────────────────────────
from .artwork import (
    ARTWORK_FORMATS_BY_ID,
    ITHMB_FORMAT_MAP,
    ITHMB_SIZE_MAP,
    cover_art_format_definitions_for_device,
    ithmb_formats_for_device,
    photo_formats_for_device,
    resolve_cover_art_format_definitions,
    resolve_cover_art_format_definitions_for_device,
)

# ── authority ────────────────────────────────────────────────────────
from .authority import (
    AUTHORITY_FILENAME,
    SOURCE_RANK,
    SYSINFO_FIELDS,
    cache_sysinfo_extended,
    check_authority_coverage,
    read_authority,
    update_sysinfo,
)
from .bootstrap import ensure_device_itunes_database

# ── capabilities ─────────────────────────────────────────────────────
from .capabilities import (
    ArtworkFormat,
    DeviceCapabilities,
    capabilities_for_family_gen,
    checksum_type_for_family_gen,
    cover_art_formats_for_family_gen,
)
from .checksum import (
    CHECKSUM_MHBD_SCHEME,
    MHBD_SCHEME_TO_CHECKSUM,
    ChecksumType,
)

# ── images ───────────────────────────────────────────────────────────
from .images import (
    COLOR_MAP,
    FAMILY_FALLBACK,
    GENERIC_IMAGE,
    IMAGE_COLORS,
    MODEL_IMAGE,
    color_for_image,
    image_for_model,
    resolve_image_filename,
)

# ── info (device_info) ───────────────────────────────────────────────
from .info import (
    DeviceInfo,
    UnidentifiedDeviceError,
    clear_current_device,
    detect_checksum_type,
    enrich,
    get_current_device,
    get_current_device_for_path,
    get_firewire_id,
    has_exact_model_number,
    itdb_write_filename,
    read_sysinfo,
    require_exact_model_number,
    resolve_itdb_path,
    set_current_device,
)

# ── lookup ───────────────────────────────────────────────────────────
from .lookup import (
    extract_model_number,
    get_friendly_model_name,
    get_model_info,
    infer_generation,
    lookup_by_serial,
    match_serial_suffix,
)

# ── models ───────────────────────────────────────────────────────────
from .models import (
    IPOD_MODELS,
    IPOD_RECOVERY_USB_PIDS,
    IPOD_USB_PIDS,
    SERIAL_LAST3_TO_MODEL,
    SERIAL_SUFFIX_TO_MODEL,
    USB_PID_TO_MODEL,
    canonicalize_model_identity,
)

# ── sysinfo parsing/evidence ─────────────────────────────────────────
from .sysinfo import (
    DeviceEvidence,
    EvidenceValue,
    ParsedSysInfoExtended,
    identity_from_sysinfo,
    identity_from_sysinfo_extended,
    parse_sysinfo_extended,
    parse_sysinfo_text,
)

# ── virtual iPods ─────────────────────────────────────────────────────
from .virtual import (
    VIRTUAL_IPOD_INFO_FILENAME,
    available_virtual_ipod_models,
    create_virtual_ipod,
    ensure_virtual_itunes_database,
    has_virtual_ipod_info,
    load_virtual_ipod_info,
    virtual_ipod_info_path,
)

# ── checksum ─────────────────────────────────────────────────────────
from .vpd_libusb import (
    identify_via_vpd,
)
from .vpd_libusb import (
    query_all_ipods as usb_query_all_ipods,
)

# ── vpd_libusb ───────────────────────────────────────────────────────
from .vpd_libusb import (
    query_ipod_vpd as usb_query_ipod_vpd,
)
from .vpd_libusb import (
    write_sysinfo as usb_write_sysinfo,
)
from .vpd_usb_control import (
    query_all_ipod_usb_sysinfo_extended,
    query_ipod_usb_sysinfo_extended,
)

try:
    from .vpd_linux import query_ipod_vpd_for_path as linux_query_ipod_vpd_for_path
except ImportError:
    pass

try:
    from .vpd_windows import query_ipod_vpd_for_path as windows_query_ipod_vpd_for_path
except ImportError:
    pass

# ── vpd_iokit is macOS-only and raises ImportError on other platforms,
#    so we don't import it at package level.  Import directly:
#        from iopenpod.device.vpd_iokit import query_ipod_vpd

# ── scanner (src/iopenpod/gui/device_scanner) ────────────────────────────────────
from .scanner import identify_ipod_at_path, scan_for_ipods
