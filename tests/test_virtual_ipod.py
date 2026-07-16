import json

from iopenpod.device import (
    ChecksumType,
    available_virtual_ipod_models,
    create_virtual_ipod,
    detect_checksum_type,
    get_firewire_id,
    has_virtual_ipod_info,
    identify_ipod_at_path,
    load_virtual_ipod_info,
)


def test_create_virtual_ipod_seeds_identity_and_layout(tmp_path) -> None:
    device = create_virtual_ipod(tmp_path, "MC297")

    assert has_virtual_ipod_info(tmp_path)
    assert (tmp_path / "iPod_Control" / "Device" / "SysInfo").exists()
    assert (tmp_path / "iPod_Control" / "Device" / "HashInfo").exists()
    assert (tmp_path / "iPod_Control" / "iTunes").is_dir()
    assert (tmp_path / "iPod_Control" / "iTunes" / "iTunesDB").exists()
    assert (tmp_path / "iPod_Control" / "Music").is_dir()
    assert (tmp_path / "iPod_Control" / "Artwork").is_dir()

    payload = json.loads((tmp_path / "iPodInfo.json").read_text())
    assert payload["model_number"] == "MC297"
    assert payload["model_family"] == "iPod Classic"
    assert payload["generation"] == "7th Gen"
    assert payload["serial"].endswith(payload["serial_suffix"])

    assert device.model_number == "MC297"
    assert device.serial.endswith(payload["serial_suffix"])
    assert device.firewire_id_bytes == bytes.fromhex(payload["firewire_guid"])
    assert device.checksum_type == ChecksumType.HASH58


def test_virtual_ipod_loads_through_normal_identification(tmp_path) -> None:
    create_virtual_ipod(tmp_path, "MA005")

    identified = identify_ipod_at_path(str(tmp_path))
    loaded = load_virtual_ipod_info(tmp_path)

    assert identified is not None
    assert identified.model_number == loaded.model_number == "MA005"
    assert identified.model_family == "iPod Nano"
    assert identified.serial == loaded.serial
    assert detect_checksum_type(str(tmp_path)) == ChecksumType.NONE
    assert get_firewire_id(str(tmp_path)) == loaded.firewire_id_bytes


def test_create_virtual_ipod_uses_device_database_filename(tmp_path) -> None:
    create_virtual_ipod(tmp_path, "MC060")

    assert (tmp_path / "iPod_Control" / "iTunes" / "iTunesCDB").exists()
    assert not (tmp_path / "iPod_Control" / "iTunes" / "iTunesDB").exists()


def test_virtual_ipod_identification_repairs_missing_database(tmp_path) -> None:
    create_virtual_ipod(tmp_path, "MC297")
    db_path = tmp_path / "iPod_Control" / "iTunes" / "iTunesDB"
    db_path.unlink()

    identified = identify_ipod_at_path(str(tmp_path))

    assert identified is not None
    assert db_path.exists()


def test_available_virtual_ipod_models_have_known_serial_suffixes() -> None:
    rows = available_virtual_ipod_models()

    assert rows
    assert all(row["model_number"] and row["serial_suffix"] for row in rows)
    assert any(row["model_number"] == "MC297" for row in rows)


def test_virtual_ipods_preserve_published_serial_suffix_length(tmp_path) -> None:
    expected_suffix_lengths = {
        "MB453": 3,
        "MC525": 4,
        "MD475": 4,
        "MD773": 4,
    }

    for model_number, suffix_length in expected_suffix_lengths.items():
        model_path = tmp_path / model_number
        device = create_virtual_ipod(model_path, model_number)
        payload = json.loads((model_path / "iPodInfo.json").read_text())

        assert len(payload["serial_suffix"]) == suffix_length
        assert device.serial.endswith(payload["serial_suffix"])
