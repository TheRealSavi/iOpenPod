from iopenpod.device import (
    IPOD_MODELS,
    USB_PID_TO_MODEL,
    DeviceInfo,
    canonicalize_model_identity,
    capabilities_for_family_gen,
    get_friendly_model_name,
    get_model_info,
)

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
