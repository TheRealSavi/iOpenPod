from iopenpod.infrastructure.theme_catalog import load_theme_catalog
from iopenpod.infrastructure.theme_renderer import render_theme
from iopenpod.infrastructure.theme_runtime import ThemeRuntime


def test_runtime_replaces_the_active_immutable_resolved_theme() -> None:
    dark = render_theme(load_theme_catalog().get("dark"))
    light = render_theme(load_theme_catalog().get("light"))
    runtime = ThemeRuntime(dark)

    assert runtime.current is dark

    runtime.replace(light)

    assert runtime.current is light
    assert dark.theme_id == "dark"
    assert light.theme_id == "light"
