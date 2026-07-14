from iopenpod.gui.styles import Colors


def _color_state() -> dict[str, object]:
    return {
        name: value
        for name, value in vars(Colors).items()
        if name.isupper() or name.startswith("_active_")
    }


def test_auto_theme_uses_the_matching_configured_palette(monkeypatch) -> None:
    before = _color_state()
    monkeypatch.setattr(
        Colors,
        "_detect_system_dark",
        classmethod(lambda cls: False),
    )
    try:
        Colors.apply_theme_selection(
            "auto",
            "catppuccin-latte",
            "catppuccin-mocha",
        )
        assert Colors._active_theme == "catppuccin-latte"
        assert Colors._active_mode == "light"
    finally:
        for name, value in before.items():
            setattr(Colors, name, value)
