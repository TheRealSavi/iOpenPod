from types import SimpleNamespace

from iopenpod.application.device_identity import (
    format_checksum_type_name,
    generic_ipod_image_filename,
    refresh_device_disk_usage,
    resolve_device_image_filename,
    resolve_ipod_image_color,
    resolve_ipod_product_image_filename,
)


def test_refresh_device_disk_usage_updates_device_fields() -> None:
    device = SimpleNamespace(path="E:/")

    refresh_device_disk_usage(
        device,
        disk_usage_fn=lambda path: (64_000_000_000, 16_000_000_000, 48_000_000_000),
    )

    assert device.disk_size_gb == 64.0
    assert device.free_space_gb == 48.0


def test_refresh_device_disk_usage_ignores_missing_device() -> None:
    refresh_device_disk_usage(None)


def test_format_checksum_type_name_handles_known_and_unknown_values() -> None:
    assert format_checksum_type_name(1) == "HASH58"
    assert format_checksum_type_name(12345) == "Unknown"


def test_resolve_device_image_filename_prefers_model_number(monkeypatch) -> None:
    monkeypatch.setattr(
        "iopenpod.device.image_for_model",
        lambda model_number: "classic-black.png",
    )

    device = SimpleNamespace(
        model_number="MC297",
        model_family="iPod Classic",
        generation="7th Gen",
        color="Black",
    )

    assert resolve_device_image_filename(device) == "classic-black.png"


def test_resolve_device_image_filename_falls_back_to_family(monkeypatch) -> None:
    monkeypatch.setattr("iopenpod.device.image_for_model", lambda model_number: "")
    monkeypatch.setattr(
        "iopenpod.device.resolve_image_filename",
        lambda family, generation, color: f"{family}-{generation}-{color}.png",
    )

    device = SimpleNamespace(
        model_number="",
        model_family="iPod Nano",
        generation="4th Gen",
        color="Blue",
    )

    assert resolve_device_image_filename(device) == "iPod Nano-4th Gen-Blue.png"


def test_resolve_ipod_product_image_filename_uses_family_fields(monkeypatch) -> None:
    monkeypatch.setattr(
        "iopenpod.device.resolve_image_filename",
        lambda family, generation, color: f"{family}-{generation}-{color}.png",
    )

    assert (
        resolve_ipod_product_image_filename("iPod Mini", "2nd Gen", "Silver")
        == "iPod Mini-2nd Gen-Silver.png"
    )


def test_resolve_ipod_image_color_uses_product_image_color(monkeypatch) -> None:
    monkeypatch.setattr(
        "iopenpod.device.color_for_image",
        lambda filename: (64, 156, 255) if filename == "blue.png" else None,
    )

    assert resolve_ipod_image_color("blue.png") == (64, 156, 255)
    assert resolve_ipod_image_color("") is None


def test_generic_ipod_image_filename_uses_device_default() -> None:
    assert generic_ipod_image_filename() == "iPodGeneric.png"
