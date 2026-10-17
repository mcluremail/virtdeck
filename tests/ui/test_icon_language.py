"""Д5/S2: the icon color layer as brand — one shape language in every theme.

The builtin SVG set (~50 icons) is token-driven: object bodies use the
ICON_BRAND family, actions use ICON_OK/ICON_ERR/ICON_WARN, pools use
ICON_POOL. The colors come from the active theme's ICON_* tokens, so a
theme CAN mute the layer — but every builtin ships the same brand hues,
and switching the theme no longer changes the graphic language.
"""
import re

import pytest

from virtdeck.ui import icons
from virtdeck.ui.theme import load_theme

ICON_TOKENS = ("ICON_BRAND", "ICON_BRAND_DEEP", "ICON_BRAND_SOFT",
               "ICON_OK", "ICON_ERR", "ICON_WARN", "ICON_POOL")

# The brand hues shipped by every builtin theme (Д5: the layer is a brand
# — it does not drift from theme to theme).
BRAND = {
    "ICON_BRAND": "#3d8bfd",
    "ICON_BRAND_DEEP": "#2563eb",
    "ICON_BRAND_SOFT": "#93c5fd",
    "ICON_OK": "#22c55e",
    "ICON_ERR": "#ef4444",
    "ICON_WARN": "#f59e0b",
    "ICON_POOL": "#8b5cf6",
}


def _tokens(theme_id):
    from virtdeck.plugins import get_registry

    return get_registry().get_theme(theme_id).tokens()


def test_every_builtin_theme_defines_the_icon_layer():
    for tid in ("light", "breeze", "breeze_dark", "oxygen", "graphite",
                "system"):
        tokens = _tokens(tid)
        for name in ICON_TOKENS:
            assert tokens[name] == BRAND[name], (tid, name)


def test_light_defaults_match_the_brand_layer():
    from virtdeck.ui import theme

    for name, value in BRAND.items():
        assert getattr(theme.Color, name) == value, name


def test_semantic_mapping_of_actions_and_objects():
    """Objects are the brand family, actions speak the status language."""
    used = lambda n: set(re.findall(r"\{(\w+)\}", icons._BUILTINS[n]))

    assert used("vm") == {"brand", "deep"}
    assert used("storage") == {"brand", "deep"}
    assert used("cluster") == {"brand", "deep"}
    assert "ok" in used("host")            # health LED
    assert used("pool") == {"pool"}
    assert used("start") == {"ok"}
    assert used("resume") == {"brand", "deep"}   # play-in-circle, brand blue
    assert "err" in used("stop")
    assert used("shutdown") == {"warn"}
    assert "err" in used("reset")


def test_no_unfilled_placeholders_in_any_theme(qapp):
    """_fmt resolves every placeholder; a foreign/unknown one is a bug."""
    try:
        for tid in ("light", "breeze", "breeze_dark", "oxygen", "graphite"):
            load_theme(tid, persist=False)
            icons.reset_icons()
            for name, tmpl in icons._BUILTINS.items():
                formatted = icons._fmt(tmpl)
                leftover = re.findall(r"\{(\w+)\}", formatted)
                assert not leftover, (tid, name, leftover)
    finally:
        load_theme("light", persist=False)
        icons.reset_icons()


def test_neutral_parts_follow_the_theme_icon_fg(qapp):
    """{c}/{c2} parts stay theme-addressable (usb plug, spinner) while the
    brand layer stays fixed — recoloring proves both mechanisms work."""
    try:
        load_theme("light", persist=False)
        light_usb = icons._fmt(icons._BUILTINS["usb"])
        load_theme("graphite", persist=False)
        graphite_usb = icons._fmt(icons._BUILTINS["usb"])
        assert light_usb != graphite_usb
        # the brand hues are identical — only the neutral strokes moved
        assert "#3d8bfd" in graphite_usb.lower()
    finally:
        load_theme("light", persist=False)


def test_icons_recache_on_theme_change(qapp):
    """The reset_icons() contract: the cache is rebuilt from the active
    theme's tokens (load_theme does this — verify the observable)."""
    try:
        load_theme("graphite", persist=False)
        assert icons._icons is None
        icons.get_icon("vm")
        assert icons._icons and "vm" in icons._icons
    finally:
        load_theme("light", persist=False)


@pytest.mark.parametrize("name", ["vm", "host", "pool", "start", "app"])
def test_svgs_render(qtbot, name):
    from PySide6.QtCore import QSize

    icon = icons.get_icon(name)
    assert not icon.isNull(), name
    assert icon.availableSizes(), name
    assert QSize(24, 24) in icon.availableSizes() or name == "app"
