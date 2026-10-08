"""Brand: designer assets render, locale and tray states."""

import pytest

from virtdeck.ui import brand
from virtdeck.ui.brand import BrandWidget


class TestAssets:
    def test_mark_renders(self, qtbot):
        for v in ("light", "dark", "mono", "mono-white"):
            pm = brand.render_pixmap(64, v)
            assert not pm.isNull() and pm.width() == 64

    def test_lockup_aspect(self, qtbot):
        pm = brand.lockup_pixmap(20, "light")
        assert not pm.isNull()
        assert pm.width() == round(20 * 1240 / 320)

    def test_logo_icon(self, qtbot):
        for v in ("light", "dark"):
            assert not brand.make_logo_icon(64, v).isNull()

    def test_tray_states(self, qtbot):
        for st in brand.TRAY_STATES:
            icon = brand.tray_icon(st, "light")
            assert not icon.isNull()
        assert not brand.tray_icon("ok", "dark", compact=True).isNull()

    def test_tray_unknown_state(self, qtbot):
        with pytest.raises(ValueError):
            brand.tray_icon("bogus")

    def test_asset_files_complete(self):
        names = ["icon", "lockup", "mark", "mark-mono", "mark-mono-white"]
        for n in names:
            assert (brand.ASSETS / f"{n}-light.svg").exists() or \
                (brand.ASSETS / f"{n}.svg").exists()
        for st in brand.TRAY_STATES:
            for v in ("light", "dark"):
                assert (brand.ASSETS / f"tray-{st}-{v}.svg").exists()


class TestVariant:
    def test_is_dark_follows_bg(self):
        from virtdeck.ui.theme import LIGHT_TOKENS, Color

        old = Color.BG
        try:
            Color.BG = "#000000"
            assert brand.is_dark() is True
            Color.BG = "#ffffff"
            assert brand.is_dark() is False
        finally:
            Color.BG = old
        assert LIGHT_TOKENS["BG"] == old

    def test_variant_resolution(self):
        assert brand._variant("dark") == "dark"
        with pytest.raises(ValueError):
            brand._variant("mono")


class TestBrandWidget:
    def test_lockup_variant_follows_theme(self, qtbot):
        from virtdeck.ui.theme import Color

        w = BrandWidget()
        old = Color.BG
        try:
            Color.BG = "#000000"
            w.restyle()
            assert w._variant == "dark"
            assert not w._label.pixmap().isNull()
        finally:
            Color.BG = old
            w.restyle()
        assert w._variant == "light"

    def test_toolbar_lockup(self, main_window):
        """Locale replaces the text label on the right of the toolbar."""
        widget = main_window._brand
        assert isinstance(widget, brand.BrandWidget)
        assert not widget._label.pixmap().isNull()


class TestTrayIntegration:
    def test_update_tray_state(self, main_window):
        from PySide6.QtWidgets import QSystemTrayIcon

        mw = main_window
        tray = QSystemTrayIcon(mw)
        old = (mw._tray, mw.nodes_cfg, mw._soft_had_errors, mw._offline_mode)
        mw._tray = tray
        try:
            mw.nodes_cfg, mw._offline_mode = [], True
            mw._update_tray_state()
            assert mw._tray_state == "offline"
            mw.nodes_cfg, mw._offline_mode = [{"name": "pve1"}], False
            mw._soft_had_errors = True
            mw._update_tray_state()
            assert mw._tray_state == "error"
            mw._soft_had_errors = False
            mw._update_tray_state()
            assert mw._tray_state == "ok"
            assert not tray.icon().isNull()
        finally:
            mw._tray, mw.nodes_cfg, mw._soft_had_errors, mw._offline_mode = old
            tray.hide()
