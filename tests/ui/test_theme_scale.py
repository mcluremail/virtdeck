"""Stage 4 (theme engine v2) gates: type scale, spacing/radius scales,
QPalette from tokens, the single disabled language, menu/token hygiene,
pbs_panel reapply (A7/Д4).

Audit refs: Д1/Д2/Д3/Д4 (S1/S3), A1–A5, GAP-2, U38, U39, part of
DELIGHT-5; regress checks R1–R4 have runtime probes (stage4_probe).
"""

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from virtdeck.ui import theme
from virtdeck.ui.theme import (
    RADIUS,
    SPACING,
    SPACING_MICRO,
    Color,
    font_px,
    load_theme,
)


def _qss():
    load_theme("light", persist=False)
    return theme.QSS


def _ui_sources():
    root = Path(theme.__file__).parent
    return [p for p in root.rglob("*.py")]


@pytest.fixture(autouse=True)
def _qapp_ctx(qapp):
    """load_theme applies a QPalette — a QApplication must exist."""
    yield
    load_theme("light", persist=False)


# ── Д2: type scale (GAP-2/U38) ─────────────────────────────────────


class TestTypeScale:
    def test_qss_font_sizes_come_from_the_scale(self):
        """Every font-size in the built QSS is a scale-role value."""
        values = {int(m) for m in re.findall(r"font-size: (\d+)px", _qss())}
        expected = {font_px(r) for r in theme._FONT_MULT}
        assert values <= expected, (values, expected)

    def test_text_never_below_12px(self):
        """U38: the floor holds in the QSS and in font_px itself."""
        assert font_px("XS") >= 12
        values = {int(m) for m in re.findall(r"font-size: (\d+)px", _qss())}
        assert min(values) >= 12

    def test_scales_with_the_application_font(self, qapp):
        """R3 mechanism: a larger app font grows every role proportionally.

        The app font is not pinned (GAP-2): the platform default
        (~9 pt / 12 px) maps to the 14 px design baseline.
        """
        load_theme("light", persist=False)
        app = qapp
        f = app.font()
        saved_pt, saved_px = f.pointSizeF(), f.pixelSize()

        f.setPixelSize(-1)
        f.setPointSizeF(9.0)
        app.setFont(f)
        base_9 = font_px("BASE")
        f.setPointSizeF(12.0)
        app.setFont(f)
        base_12 = font_px("BASE")
        try:
            # design baseline at the platform default
            assert base_9 == 14
            # 12/9 growth, tolerant to rounding
            ratio = base_12 / base_9
            assert ratio == pytest.approx(12 / 9, abs=0.05)
        finally:
            f.setPixelSize(saved_px)
            if saved_px <= 0:
                f.setPointSizeF(saved_pt)
            app.setFont(f)
        load_theme("light", persist=False)

    def test_floor_at_tiny_system_font(self, qapp):
        """Even a 6 pt system font must not push text below 12 px."""
        app = qapp
        f = app.font()
        f.setPixelSize(-1)
        f.setPointSizeF(6.0)
        app.setFont(f)
        try:
            assert font_px("XS") == 12
            assert font_px("BASE") >= 12
        finally:
            f.setPointSizeF(9.0)
            app.setFont(f)

    def test_app_font_family_only_no_size_pin(self):
        """theme.load() swaps the family, keeping the platform size."""
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        before = app.font().pointSizeF()
        theme.load()
        assert app.font().pointSizeF() == before


# ── Д2: spacing/radius gates ───────────────────────────────────────


class TestScaleGates:
    def test_spacing_values_within_scale(self):
        """R1 autotest: no spacing literals outside the scale in the QSS.

        Allowed: 0, the primary scale (4/8/12/16/24) and the documented
        optical micro-steps (1/2/3/6 — hairlines and tight small-control
        paddings).
        """
        allowed = {0, *SPACING, *SPACING_MICRO}
        offenders = []
        for m in re.finditer(
                r"(?:^|[;{])\s*((?:padding|margin)(?:-[\w-]+)?|spacing)\s*:\s*"
                r"([^;}]+)", _qss()):
            for px in re.findall(r"(-?\d+)px", m.group(2)):
                if int(px) not in allowed:
                    offenders.append((m.group(1), m.group(2).strip()))
        assert not offenders, offenders

    def test_radius_values_within_scale(self):
        allowed = set(RADIUS.values())
        offenders = []
        for m in re.finditer(r"border(?:-[\w-]+)?-radius:\s*(\d+)px", _qss()):
            if int(m.group(1)) not in allowed:
                offenders.append(m.group(0))
        assert not offenders, offenders


# ── Д1: QPalette from tokens (S1) ──────────────────────────────────


class TestPalette:
    def test_highlight_follows_the_theme(self, qapp):
        from PySide6.QtGui import QPalette

        try:
            load_theme("graphite", persist=False)
            pal = qapp.palette()
            assert (pal.color(QPalette.ColorGroup.Active,
                              QPalette.ColorRole.Highlight).name().lower()
                    == Color.ACCENT_LIGHT.lower())
            assert (pal.color(QPalette.ColorGroup.Active,
                              QPalette.ColorRole.Window).name().lower()
                    == Color.BG.lower())
        finally:
            load_theme("light", persist=False)

    def test_disabled_group_is_muted(self, qapp):
        from PySide6.QtGui import QPalette

        load_theme("light", persist=False)
        pal = qapp.palette()
        assert (pal.color(QPalette.ColorGroup.Disabled,
                          QPalette.ColorRole.WindowText).name().lower()
                == Color.DISABLED.lower())


# ── Д3: the single disabled language ───────────────────────────────


class TestDisabledLanguage:
    def test_filled_buttons_disable_to_muted_outline(self):
        qss = _qss()
        block = re.search(
            r"QPushButton#accentBtn:disabled[^{]*\{([^}]*)\}", qss)
        assert block, "ID-scoped disabled rule missing (QSS specificity)"
        body = block.group(1)
        assert Color.DISABLED in body
        assert Color.ALT_ROW in body
        assert Color.BORDER_LIGHT in body
        # the old look: solid gray fill with on-accent text
        assert Color.DISABLED not in re.findall(
            r"background:\s*(\S+);", body)
        assert "ON_ACCENT" not in body

    def test_focus_ring_survives(self):
        """U34 (stage 1) must not regress with the disabled rework."""
        qss = _qss()
        assert "QPushButton:focus" in qss
        assert "QPushButton#accentBtn:focus, QPushButton#dangerBtn:focus" in qss


# ── A1: one menu language ──────────────────────────────────────────


class TestMenuLanguage:
    def test_no_inline_menu_styles(self):
        """A1: context menus carry no inline QSS — the global sheet only."""
        for path in _ui_sources():
            if path.name == "theme.py":
                continue  # the global sheet is the single menu language
            src = path.read_text(encoding="utf-8")
            assert "QMenu::item:selected" not in src, path
            assert "menu.setStyleSheet" not in src, path


# ── A2–A5: token hygiene ───────────────────────────────────────────


class TestTokenHygiene:
    def test_no_color_white_literal(self):
        for path in _ui_sources():
            assert "color: white" not in path.read_text(encoding="utf-8"), path

    def test_no_bare_monospace_family(self):
        for path in _ui_sources():
            src = path.read_text(encoding="utf-8")
            assert "font-family: monospace" not in src, path

    def test_no_absolute_point_sizes(self):
        """A4 + Д2: no absolute setPointSize in the UI (scale instead)."""
        for path in _ui_sources():
            src = path.read_text(encoding="utf-8")
            assert "setPointSize(" not in src, path

    def test_no_10_11px_font_literals(self):
        """U38 gate: no text below the 12 px floor in inline styles."""
        pattern = re.compile(r"font-size:\s*(?:10|11)px")
        for path in _ui_sources():
            assert not pattern.search(path.read_text(encoding="utf-8")), path


# ── U39: checkbox hit target ───────────────────────────────────────


class TestCheckboxTarget:
    def test_indicator_is_18px(self):
        qss = _qss()
        block = re.search(r"QCheckBox::indicator\s*\{([^}]*)\}", qss)
        assert block
        assert "width: 18px" in block.group(1)
        assert "height: 18px" in block.group(1)


# ── Д4/A7: pbs_panel in the reapply coverage ───────────────────────


class FakeDs(SimpleNamespace):
    pass


class TestPbsReapply:
    def _panel(self, qapp):
        from virtdeck.ui.pbs_panel import PbsPanel

        return PbsPanel()

    def test_reapply_recolors_labels_and_bar(self, qapp):
        panel = self._panel(qapp)
        ds = FakeDs(name="tank", status_ok=True, usage=0.5,
                    usage_pct=lambda: 50,
                    used_bytes=5, total_bytes=10, path="/backup/tank")
        from virtdeck.ui.theme import usage_color

        panel._fill_status(ds)
        panel._set_status("Updated", Color.TEXT_SEC)

        load_theme("graphite", persist=False)
        try:
            panel.reapply_theme()
            # labels carry the graphite TEXT_SEC, not the light one
            assert Color.TEXT_SEC in panel._path_lbl.styleSheet()
            assert Color.TEXT_SEC in panel._status_lbl.styleSheet()
            assert Color.TEXT_SEC in panel._jobs_hint.styleSheet()
            # the usage bar chunk follows the shared A8 contract
            assert f"background: {usage_color(50)}" in \
                panel._usage_bar.styleSheet()
        finally:
            load_theme("light", persist=False)

    def test_verify_and_ops_colors_resolve_live(self):
        from virtdeck.ui.pbs_panel import _verify_color

        load_theme("light", persist=False)
        ok = _verify_color("ok")
        load_theme("graphite", persist=False)
        try:
            assert _verify_color("ok") == Color.STATUS_OK != ok
        finally:
            load_theme("light", persist=False)

    def test_mainwindow_reaches_pbs_panel(self, main_window):
        """A7 end-to-end: the theme switch recolors the pbs panel."""
        panel = main_window.pbs_panel
        panel._set_status("Updated", Color.TEXT_SEC)
        combo = main_window._theme_combo
        idx = next(i for i in range(combo.count())
                   if combo.itemData(i) == "graphite")
        combo.setCurrentIndex(idx)
        try:
            assert Color.TEXT_SEC in panel._status_lbl.styleSheet()
        finally:
            light = next(i for i in range(combo.count())
                         if combo.itemData(i) == "light")
            combo.setCurrentIndex(light)


# ── A5/A11: status-bar combo and the icon-only toolbar ─────────────


class TestToolbarAndCombo:
    def test_lang_combo_uses_the_shared_style(self, main_window):
        assert main_window._lang_combo.styleSheet() \
            == main_window._status_combo_style()

    def test_no_text_only_quit_in_toolbar(self, main_window):
        texts = [a.text() for a in main_window._toolbar.actions()]
        assert "Quit" not in texts
        # the keyboard path stays (global.quit spec + tray menu)
        from virtdeck.ui.action_specs import build_registry

        quit_specs = [s for s in build_registry(main_window).all()
                      if s.action_id == "global.quit"]
        assert quit_specs and quit_specs[0].shortcut == "Ctrl+Q"


# ── repolish hygiene: repeated theme ops must be no-ops ─────────────


class TestRepolishHygiene:
    def test_palette_skips_when_signature_unchanged(self, qapp, monkeypatch):
        """_apply_palette must not setPalette twice for the same tokens
        (setPalette repolishes the whole widget tree)."""
        calls = []
        orig = qapp.setPalette

        def _spy(pal):
            calls.append(pal)
            orig(pal)

        monkeypatch.setattr(qapp, "setPalette", _spy)
        theme._PALETTE_SIG = None
        try:
            theme._apply_palette()
            theme._apply_palette()
            assert len(calls) == 1
        finally:
            theme._PALETTE_SIG = None

    def test_load_skips_noop_setfont(self, qapp, monkeypatch):
        """theme.load() must not setFont when the family is already the
        resolved one (setFont repolishes the whole widget tree)."""
        app = qapp
        f = app.font()
        f.setFamily(Color.UI_FONT)
        app.setFont(f)
        called = []
        orig = app.setFont

        def _spy(font):
            called.append(font)
            orig(font)

        monkeypatch.setattr(app, "setFont", _spy)
        theme.load()
        assert called == []
        # a different family goes through (GAP-2 family swap still works)
        other = app.font()
        other.setFamily("SomeOtherFamily")
        orig(other)
        theme.load()
        assert len(called) == 1
        assert app.font().family() == Color.UI_FONT
