"""Bundled icon pack v2: the default source for every mapped icon name.

The pack ships inside virtdeck/ui/icons_pack (78 icons × light/dark
variants, 128 viewBox). Every name in _PACK_MAP loads from the bundle
without env vars; VIRTDECK_ICON_PACK remains an override for external
pack trials. Only app/loading/restore stay builtin-token-driven.
"""
import os

import pytest

from virtdeck.ui import icons


@pytest.fixture(autouse=True)
def _restore_icon_state():
    yield
    os.environ.pop("VIRTDECK_ICON_PACK", None)
    icons.reset_icons()


def test_bundled_pack_loads_without_env_vars():
    os.environ.pop("VIRTDECK_ICON_PACK", None)
    icons.reset_icons()
    assert icons._PACK, "bundled pack must be the default source"
    for ours in icons._PACK_MAP:
        assert 'viewBox="0 0 128 128"' in icons._PACK[ours], ours
    # a mapped name really comes from the pack, not the builtin glyph
    assert icons._PACK["start"] != icons._BUILTINS["start"]


def test_pack_covers_every_builtin_except_brand_and_spinner():
    assert set(icons._BUILTINS) - set(icons._PACK_MAP) == {"app", "restore"}


def test_no_missing_pack_files(qapp):
    os.environ.pop("VIRTDECK_ICON_PACK", None)
    icons.reset_icons()
    assert len(icons._PACK) == len(icons._PACK_MAP)


def test_variant_follows_the_active_theme(qapp):
    from virtdeck.ui.theme import load_theme

    try:
        os.environ.pop("VIRTDECK_ICON_PACK", None)
        load_theme("light", persist=False)
        icons.reset_icons()
        light_start = icons._PACK["start"]
        load_theme("graphite", persist=False)
        icons.reset_icons()
        assert icons._PACK["start"] != light_start
    finally:
        load_theme("light", persist=False)


def test_env_var_still_overrides_the_bundle(tmp_path, qapp):
    (tmp_path / "light").mkdir()
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
           '<rect width="24" height="24" fill="#123456"/></svg>')
    (tmp_path / "light" / "start.svg").write_text(svg, encoding="utf-8")
    os.environ["VIRTDECK_ICON_PACK"] = str(tmp_path)
    icons.reset_icons()
    assert icons._PACK["start"] == svg


def test_pack_dot_geometry_fits_the_reserved_zone():
    """The pack reserves a bottom-right clearance: dot center (110,110),
    r14 + stroke ≈ 17 (see the pack's validation.json)."""
    cx, r = icons._dot_geometry(icons._PACK["host"])
    assert (cx, r) == (110.0, 14.0)
