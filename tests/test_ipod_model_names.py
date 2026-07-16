from iopenpod.device import (
    IPOD_MODELS,
    IPOD_RECOVERY_USB_PIDS,
    SERIAL_SUFFIX_TO_MODEL,
    USB_PID_TO_MODEL,
    DeviceInfo,
    canonicalize_model_identity,
    capabilities_for_family_gen,
    get_friendly_model_name,
    get_model_info,
    lookup_by_serial,
)
from iopenpod.device.scanner import _resolve_model
from iopenpod.device.virtual import _usb_pid_for_identity

ALLOWED_MODEL_GENERATIONS = {
    "iPod Shuffle": {"1st Gen", "2nd Gen", "3rd Gen", "4th Gen"},
    "iPod": {
        "1st Gen",
        "2nd Gen",
        "3rd Gen",
        "4th Gen (mono)",
        "4th Gen (photo)",
        "4th Gen (color)",
        "5th Gen",
        "5.5th Gen",
    },
    "iPod Classic": {"6th Gen", "6.5th Gen", "7th Gen"},
    "iPod Nano": {
        "1st Gen",
        "2nd Gen",
        "3rd Gen",
        "4th Gen",
        "5th Gen",
        "6th Gen",
        "7th Gen",
    },
    "iPod Mini": {"1st Gen", "2nd Gen"},
}


def test_model_database_uses_only_canonical_community_model_names() -> None:
    for model_number, (family, generation, _capacity, _color) in IPOD_MODELS.items():
        assert family in ALLOWED_MODEL_GENERATIONS, model_number
        assert generation in ALLOWED_MODEL_GENERATIONS[family], model_number
        assert "Video" not in family
        assert "U2" not in family


def test_usb_pid_model_hints_use_only_canonical_community_model_names() -> None:
    for pid, (family, generation) in USB_PID_TO_MODEL.items():
        assert family in ALLOWED_MODEL_GENERATIONS, hex(pid)
        if generation:
            assert generation in ALLOWED_MODEL_GENERATIONS[family], hex(pid)
        assert "Video" not in family
        assert "U2" not in family


def test_recovery_usb_pids_resolve_to_their_supported_device_generations() -> None:
    expected_recovery_pids = {
        # Bootrom DFU mode. 0x1223 is shared by Nano 3G and every Classic
        # revision, so it must remain a deliberately coarse family hint.
        0x1220: ("iPod Nano", "2nd Gen"),
        0x1223: ("iPod", ""),
        0x1224: ("iPod Nano", "3rd Gen"),
        0x1225: ("iPod Nano", "4th Gen"),
        0x1231: ("iPod Nano", "5th Gen"),
        0x1232: ("iPod Nano", "6th Gen"),
        0x1233: ("iPod Shuffle", "4th Gen"),
        0x1234: ("iPod Nano", "7th Gen"),
        # WTF/recovery-loader mode.
        0x1240: ("iPod Nano", "2nd Gen"),
        0x1241: ("iPod Classic", "6th Gen"),
        0x1242: ("iPod Nano", "3rd Gen"),
        0x1243: ("iPod Nano", "4th Gen"),
        0x1245: ("iPod Classic", "6.5th Gen"),
        0x1246: ("iPod Nano", "5th Gen"),
        0x1247: ("iPod Classic", "7th Gen"),
        0x1248: ("iPod Nano", "6th Gen"),
        0x1249: ("iPod Nano", "7th Gen"),
        0x124A: ("iPod Nano", "7th Gen"),
        # Alternate Nano 4G DFU identity published by the USB ID repository.
        0x1255: ("iPod Nano", "4th Gen"),
    }

    assert {pid: USB_PID_TO_MODEL.get(pid) for pid in expected_recovery_pids} == expected_recovery_pids
    assert IPOD_RECOVERY_USB_PIDS == frozenset(expected_recovery_pids)


def test_virtual_ipods_never_use_a_recovery_mode_usb_pid() -> None:
    assert _usb_pid_for_identity("iPod Nano", "3rd Gen") == 0x1262
    assert _usb_pid_for_identity("iPod Nano", "6th Gen") == 0x1266
    assert _usb_pid_for_identity("iPod Nano", "7th Gen") == 0x1267
    assert _usb_pid_for_identity("iPod Shuffle", "4th Gen") == 0x1303


def test_full_size_ipod_model_number_samples_are_canonical() -> None:
    assert get_model_info("M9787") == ("iPod", "4th Gen (mono)", "20GB", "U2")
    assert get_model_info("M9585") == ("iPod", "4th Gen (photo)", "40GB", "White")
    assert get_model_info("MA079") == ("iPod", "4th Gen (color)", "20GB", "White")
    assert get_model_info("MA452") == ("iPod", "5th Gen", "30GB", "U2")
    assert get_model_info("MA664") == ("iPod", "5.5th Gen", "30GB", "U2")


def test_classic_model_number_samples_continue_ipod_generation_numbers() -> None:
    assert get_model_info("MB029") == ("iPod Classic", "6th Gen", "80GB", "Silver")
    assert get_model_info("MB562") == ("iPod Classic", "6.5th Gen", "120GB", "Silver")
    assert get_model_info("MC297") == ("iPod Classic", "7th Gen", "160GB", "Black")


def test_nano_3g_pink_serial_suffix_resolves_exact_model_number() -> None:
    assert lookup_by_serial("6U804D0N13F") == (
        "MB453",
        ("iPod Nano", "3rd Gen", "8GB", "Pink"),
    )


def test_four_character_serial_suffix_must_match_all_four_characters() -> None:
    assert lookup_by_serial("SERIALF0GD") == (
        "MD475",
        ("iPod Nano", "7th Gen", "16GB", "Pink"),
    )
    assert lookup_by_serial("SERIALX0GD") is None
    assert lookup_by_serial("0GD") is None


def test_longest_matching_serial_suffix_wins(monkeypatch) -> None:
    monkeypatch.setitem(SERIAL_SUFFIX_TO_MODEL, "0GD", "MB453")

    assert lookup_by_serial("SERIALF0GD") == (
        "MD475",
        ("iPod Nano", "7th Gen", "16GB", "Pink"),
    )


def test_three_character_serial_suffixes_remain_supported() -> None:
    assert lookup_by_serial("6U804D0N13F") == (
        "MB453",
        ("iPod Nano", "3rd Gen", "8GB", "Pink"),
    )


def test_serial_suffix_table_preserves_published_key_lengths() -> None:
    three_character_suffixes = {
        suffix for suffix in SERIAL_SUFFIX_TO_MODEL if len(suffix) == 3
    }
    four_character_suffixes = {
        suffix for suffix in SERIAL_SUFFIX_TO_MODEL if len(suffix) == 4
    }

    assert len(four_character_suffixes) == 57
    assert all(suffix.isalnum() and suffix == suffix.upper() for suffix in SERIAL_SUFFIX_TO_MODEL)
    assert set(map(len, SERIAL_SUFFIX_TO_MODEL)) == {3, 4}
    assert three_character_suffixes.isdisjoint(
        suffix[-3:] for suffix in four_character_suffixes
    )


def test_scanner_resolves_nano_3g_pink_serial_to_exact_model_number() -> None:
    resolved = _resolve_model(
        {"usb_pid": 0x1262, "model_family": "iPod Nano", "generation": "3rd Gen"},
        {"serial": "6U804D0N13F"},
        disk_size_gb=7.4,
    )

    assert resolved["model_number"] == "MB453"
    assert resolved["model_family"] == "iPod Nano"
    assert resolved["generation"] == "3rd Gen"
    assert resolved["capacity"] == "8GB"
    assert resolved["color"] == "Pink"


def test_scanner_resolves_four_character_serial_suffix() -> None:
    resolved = _resolve_model(
        {"usb_pid": 0x1267, "model_family": "iPod Nano", "generation": "7th Gen"},
        {"serial": "C8T00000F0GD"},
        disk_size_gb=15.0,
    )

    assert resolved["model_number"] == "MD475"
    assert resolved["model_family"] == "iPod Nano"
    assert resolved["generation"] == "7th Gen"
    assert resolved["capacity"] == "16GB"
    assert resolved["color"] == "Pink"


def test_reference_serial_suffixes_resolve_to_exact_model_numbers() -> None:
    expected_models = {
        # Full-size iPod and iPod Mini variants.
        "U5H": "MA215",
        "WEM": "MA664",
        "S4G": "M9805",
        "S4H": "M9805",
        # iPod Nano variants.
        "37G": "MB651",
        "72D": "MC043",
        # iPod Nano 6th generation variants use four-character suffixes.
        "DCMN": "MC525",
        "DCMP": "MC526",
        "DDVX": "MC688",
        "DDVY": "MC689",
        "DDW0": "MC690",
        "DDW1": "MC691",
        "DDW2": "MC692",
        "DDW3": "MC693",
        "DDW4": "MC694",
        "DDW5": "MC695",
        "DDW6": "MC696",
        "DDW7": "MC697",
        "DDW8": "MC698",
        "DDW9": "MC699",
        # iPod Nano 7th generation variants.
        "F0GD": "MD475",
        "F0GM": "MD475",
        "F0GF": "MD476",
        "F0GN": "MD476",
        "F0GG": "MD477",
        "F0GP": "MD477",
        "F0GH": "MD478",
        "F0GQ": "MD478",
        "F0GJ": "MD479",
        "F0GR": "MD479",
        "F0GK": "MD480",
        "F0GT": "MD480",
        "F0GL": "MD481",
        "F0GV": "MD481",
        "F4LN": "MD744",
        "F4LP": "MD744",
        "FJQ1": "ME971",
        "GK60": "MKMV2",
        "GK61": "MKMX2",
        "GK62": "MKN02",
        "GK63": "MKN22",
        "GK64": "MKN52",
        "GK65": "MKN72",
        # iPod Shuffle 2nd generation variants.
        "YX7": "MB227",
        "YXH": "MB227",
        "1ZK": "MB520",
        "YXJ": "MB229",
        "1ZM": "MB522",
        "YXK": "MB231",
        "1ZP": "MB524",
        "YXL": "MB233",
        "1ZR": "MB526",
        "436": "MB811",
        "3FK": "MB681",
        "437": "MB813",
        "3FL": "MB683",
        "438": "MB815",
        "3FM": "MB685",
        "439": "MB817",
        "3W6": "MB779",
        # iPod Shuffle 4th generation variants also use four characters.
        "DCMJ": "MC584",
        "DCMK": "MC585",
        "DFDM": "MC749",
        "DFDN": "MC750",
        "DFDP": "MC751",
        "F4RT": "MD773",
        "F4RV": "MD774",
        "F4RW": "MD775",
        "F4RY": "MD776",
        "F4T0": "MD777",
        "F4T1": "MD778",
        "F4VF": "MD779",
        "F4VG": "MD780",
        "FJDH": "ME949",
        "GK67": "MKM72",
        "GK68": "MKM92",
        "GK69": "MKME2",
        "GK6C": "MKMG2",
        "GK6D": "MKMJ2",
        "GK6F": "MKML2",
    }

    resolved_models = {}
    for suffix in expected_models:
        resolved = lookup_by_serial(f"SERIAL{suffix}")
        resolved_models[suffix] = resolved[0] if resolved else None

    assert set(expected_models) <= set(SERIAL_SUFFIX_TO_MODEL)
    assert resolved_models == expected_models


def test_friendly_model_names_do_not_add_video_or_u2_to_model_family() -> None:
    assert get_friendly_model_name("MA664") == "iPod 5.5th Gen 30GB U2"
    assert get_friendly_model_name("MC297") == "iPod Classic 7th Gen 160GB Black"


def test_canonical_model_labels_are_normalized() -> None:
    assert canonicalize_model_identity("ipod", "4th gen color") == (
        "iPod",
        "4th Gen (color)",
        "",
    )
    assert canonicalize_model_identity("ipod classic", "7th gen") == (
        "iPod Classic",
        "7th Gen",
        "",
    )


def test_every_exact_model_row_resolves_capabilities() -> None:
    for model_number, (family, generation, capacity, _color) in IPOD_MODELS.items():
        assert capabilities_for_family_gen(
            family,
            generation,
            capacity=capacity,
            model_number=model_number,
        ), model_number


def test_u2_color_does_not_override_generation_capabilities() -> None:
    mono = capabilities_for_family_gen(
        "iPod",
        "4th Gen (mono)",
        capacity="20GB",
        model_number="M9787",
    )
    color = capabilities_for_family_gen(
        "iPod",
        "4th Gen (color)",
        capacity="20GB",
        model_number="MA127",
    )

    assert mono is not None
    assert color is not None
    assert mono.supports_artwork is False
    assert mono.supports_photo is False
    assert color.supports_artwork is True
    assert color.supports_photo is True


def test_full_size_display_ipod_icon_does_not_depend_on_old_family_words() -> None:
    assert DeviceInfo(model_family="iPod", generation="5th Gen").icon == "\U0001f4f1"
    assert DeviceInfo(model_family="iPod", generation="4th Gen (photo)").icon == "\U0001f4f1"
    assert DeviceInfo(model_family="iPod", generation="4th Gen (mono)").icon == "\U0001f3b5"
