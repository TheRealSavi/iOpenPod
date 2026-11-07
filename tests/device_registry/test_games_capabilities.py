"""Native click-wheel games eligibility across the marketed catalog."""

from device_registry import DEFAULT_DEVICE_REGISTRY


def test_games_support_is_limited_to_game_capable_generations() -> None:
    supported = {
        ("iPod", "5th Gen"),
        ("iPod", "5.5th Gen"),
        ("iPod Classic", "6th Gen"),
        ("iPod Classic", "6.5th Gen"),
        ("iPod Classic", "7th Gen"),
        ("iPod Nano", "3rd Gen"),
        ("iPod Nano", "4th Gen"),
        ("iPod Nano", "5th Gen"),
    }
    observed: set[tuple[str, str]] = set()
    for profile in DEFAULT_DEVICE_REGISTRY.profiles:
        identity = (profile.family, profile.generation)
        assert profile.capabilities.supports_games == (identity in supported), (
            profile.model_number
        )
        if profile.capabilities.supports_games:
            observed.add(identity)
    assert observed == supported
