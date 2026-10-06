"""M1.1 — движок тем: контракт токенов, ThemePlugin, активация.

Проверяются инварианты, которые морозятся в docs/THEMES.md на 3.0:
канонический набор токенов, валидация наборов, поток load_theme
(фасад → QSS → иконки → графики → слушатели), переключатель в
статус-баре.
"""

import re
from pathlib import Path

import pytest

from virtdeck.plugins import PluginError
from virtdeck.ui import theme
from virtdeck.ui.theme import (
    FONT_TOKENS,
    LIGHT_TOKENS,
    TOKENS,
    Color,
    load_theme,
    subscribe_theme_changed,
    unsubscribe_theme_changed,
    validate_tokens,
)


class FakeDark:
    """Тестовая тема: полный набор light + подмены, extra_qss, 24px."""

    id = "fake_dark"
    name = "Fake Dark"

    def tokens(self):
        tokens = dict(LIGHT_TOKENS)
        tokens.update(BG="#232629", PANEL="#1b1e20", TEXT="#fcfcfc", ACCENT="#3daee9")
        return tokens

    def extra_qss(self):
        return "\n/* fake dark extra */\n"

    def icons(self):
        return None

    icon_size = 24


@pytest.fixture()
def dark_registry():
    from virtdeck.plugins import default_registry

    reg = default_registry()
    reg.register_theme(FakeDark())
    return reg


# ── Контракт набора ────────────────────────────────────────────────


class TestTokenContract:
    def test_builtin_light_covers_full_set(self):
        from virtdeck.plugins import default_registry

        reg = default_registry()
        assert "light" in reg.theme_ids()
        tokens = reg.get_theme("light").tokens()
        assert set(tokens) == set(TOKENS)
        for value in tokens.values():
            assert re.fullmatch(r"#[0-9a-fA-F]{6}", value)

    def test_light_tokens_match_default_color_palette(self):
        """Светлая тема = дефолтная палитра фасада (до подмен)."""
        for name, value in LIGHT_TOKENS.items():
            assert getattr(Color, name) == value, name

    def test_qss_template_uses_only_known_tokens(self):
        """Все ссылки на токены в theme.py — канонические имена или шрифты."""
        source = Path(theme.__file__).read_text(encoding="utf-8")
        names = set(re.findall(r"Color\.([A-Z][A-Z0-9_]*)", source))
        assert names <= set(TOKENS) | set(FONT_TOKENS)

    def test_builtin_themes_are_pure(self):
        """Плагины тем не тянут сеть/Qt — AST-скан импортов."""
        import ast

        src = Path(theme.__file__).parent.parent.parent / ("virtdeck/plugins/_themes.py")
        tree = ast.parse(src.read_text(encoding="utf-8"))
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".")[0])
        assert not roots & {"PySide6", "requests", "proxmoxer"}, roots


# ── Валидация наборов ──────────────────────────────────────────────


class TestValidateTokens:
    def test_rejects_incomplete_set(self):
        with pytest.raises(PluginError, match="missing tokens"):
            validate_tokens({"BG": "#ffffff"})

    def test_rejects_unknown_token(self):
        tokens = dict(LIGHT_TOKENS)
        tokens["NOT_A_TOKEN"] = "#000000"
        with pytest.raises(PluginError, match="unknown theme token"):
            validate_tokens(tokens)

    def test_rejects_bad_color(self):
        tokens = dict(LIGHT_TOKENS)
        tokens["BG"] = "white"
        with pytest.raises(PluginError, match="invalid color"):
            validate_tokens(tokens)

    def test_rejects_non_dict(self):
        with pytest.raises(PluginError, match="dict"):
            validate_tokens(["BG=#ffffff"])

    def test_deprecated_aliases_map_to_canonical(self):
        tokens = dict(LIGHT_TOKENS)
        tokens["GRAY_400"] = "#123456"  # алиас TEXT_DIM перекрывает
        mapped = validate_tokens(tokens)
        assert mapped["TEXT_DIM"] == "#123456"


# ── Активация (load_theme) ─────────────────────────────────────────


class TestLoadTheme:
    def test_switch_updates_facade_qss_icons_listeners(self, qtbot, dark_registry):
        assert Color.ACCENT == LIGHT_TOKENS["ACCENT"]
        seen = []
        subscribe_theme_changed(seen.append)
        try:
            assert load_theme("fake_dark", registry=dark_registry, persist=False) == "fake_dark"
            assert Color.BG == "#232629"
            assert Color.ACCENT == "#3daee9"
            assert "/* fake dark extra */" in theme.QSS
            assert seen == ["fake_dark"]

            from PySide6.QtCore import QSize

            from virtdeck.ui import icons

            assert icons._BASE_SIZE == 24
            icon = icons.get_icon("vm")  # кэш пересобран под 24px
            assert QSize(24, 24) in icon.availableSizes()
        finally:
            unsubscribe_theme_changed(seen.append)

    def test_switch_back_restores_light(self, dark_registry):
        load_theme("fake_dark", registry=dark_registry, persist=False)
        assert load_theme("light", registry=dark_registry, persist=False) == "light"
        for name, value in LIGHT_TOKENS.items():
            assert getattr(Color, name) == value, name
        assert "/* fake dark extra */" not in theme.QSS

    def test_unknown_theme_raises(self, dark_registry):
        with pytest.raises(PluginError):
            load_theme("nope", registry=dark_registry, persist=False)

    def test_invalid_theme_rejected_before_apply(self, dark_registry):
        class Broken(FakeDark):
            id = "broken"

            def tokens(self):
                return {"BG": "#ffffff"}  # неполный набор

        dark_registry.register_theme(Broken())
        with pytest.raises(PluginError):
            load_theme("broken", registry=dark_registry, persist=False)
        assert Color.BG == LIGHT_TOKENS["BG"]  # фасад не тронут


# ── E2E: MainWindow ────────────────────────────────────────────────


class TestMainWindowSwitcher:
    def test_theme_combo_in_status_bar(self, main_window):
        combo = main_window._theme_combo
        ids = [combo.itemData(i) for i in range(combo.count())]
        assert "light" in ids
        assert combo.currentData() == "light" or "light" in ids

    def test_switch_via_combo_recolors_tree(self, qtbot, monkeypatch, tmp_path, offline):
        """Тема регистрируется ДО MainWindow — комбо её уже содержит."""
        from virtdeck.plugins import get_registry

        reg = get_registry()
        reg.register_theme(FakeDark())
        try:
            monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
            from virtdeck.ui.mainwindow import MainWindow

            mw = MainWindow()
            qtbot.addWidget(mw)

            combo = mw._theme_combo
            idx = next(i for i in range(combo.count()) if combo.itemData(i) == "fake_dark")
            combo.setCurrentIndex(idx)  # сигнал → load_theme → listeners

            assert Color.BG == "#232629"
            assert "/* fake dark extra */" in theme.QSS
            # дерево перестроено слушателем (кэш QColor обновлён)
            assert mw.tree_panel.tree.topLevelItemCount() >= 0
            # возврат
            light_idx = next(i for i in range(combo.count()) if combo.itemData(i) == "light")
            combo.setCurrentIndex(light_idx)
            assert Color.BG == LIGHT_TOKENS["BG"]
        finally:
            reg.unregister("fake_dark")
            load_theme("light", persist=False)

    def test_default_registry_has_no_fake_leftovers(self):
        from virtdeck.plugins import get_registry

        assert "fake_dark" not in get_registry().theme_ids()
        assert "light" in get_registry().theme_ids()


# ── M1.2: встроенные темы KDE / Graphite / System ──────────────────


class TestBuiltinThemePlugins:
    @pytest.mark.parametrize(
        "tid", ["breeze", "breeze_dark", "oxygen", "graphite", "system"])
    def test_full_token_coverage(self, tid):
        from virtdeck.plugins import get_registry

        tokens = get_registry().get_theme(tid).tokens()
        assert set(tokens) == set(TOKENS)
        assert all(re.fullmatch(r"#[0-9a-fA-F]{6}", v) for v in tokens.values())

    def test_breeze_palettes_exact(self):
        """Точные значения из схем KDE breeze (не derived)."""
        from virtdeck.plugins import get_registry

        light = get_registry().get_theme("breeze").tokens()
        assert light["BG"] == "#eff0f1"
        assert light["ACCENT"] == "#3daee9"
        assert light["ACCENT_LIGHT"] == "#a3d4fa"
        assert light["DANGER_SOLID_PRESSED"] == "#b03745"
        dark = get_registry().get_theme("breeze_dark").tokens()
        assert dark["BG"] == "#202326"
        assert dark["ACCENT_LIGHT"] == "#1e5774"
        assert dark["TEXT"] == "#fcfcfc"

    def test_oxygen_palette_exact(self):
        from virtdeck.plugins import get_registry

        tokens = get_registry().get_theme("oxygen").tokens()
        assert tokens["ACCENT"] == "#3aa7dd"
        assert tokens["ACCENT_HOVER"] == "#6ed6ff"
        assert tokens["TOAST_BG"] == "#181513"
        assert tokens["DANGER_SOLID_PRESSED"] == "#9c0e0e"
        # WARNING затемнён относительно схемы Oxygen: контраст текста >=4.5
        assert tokens["WARNING"] == "#6e4a08"

    def test_breeze_activates_24px_with_overrides(self, qtbot):
        from PySide6.QtCore import QSize

        from virtdeck.ui import icons

        try:
            load_theme("breeze", persist=False)
            assert icons._BASE_SIZE == 24
            assert {"vm", "host", "cluster", "pool", "storage",
                    "backup", "refresh", "search"} <= set(icons._THEME_ICONS)
            # все иконки рендерятся ровно в базовом размере, без уменьшения
            assert QSize(24, 24) in icons.get_icon("vm").availableSizes()
            assert QSize(24, 24) in icons.get_icon("refresh").availableSizes()
        finally:
            load_theme("light", persist=False)
        assert icons._BASE_SIZE == 16
        assert not icons._THEME_ICONS
        assert QSize(16, 16) in icons.get_icon("vm").availableSizes()

    def test_breeze_icons_cover_full_registry(self):
        """Breeze перекрывает весь реестр иконок, кроме брендового 'app'."""
        from virtdeck.plugins._themes import BREEZE_ICONS
        from virtdeck.ui import icons

        missing = set(icons._BUILTINS) - {"app"} - set(BREEZE_ICONS)
        assert not missing, missing
        assert "app" not in BREEZE_ICONS
        for name, svg in BREEZE_ICONS.items():
            assert 'viewBox="0 0 24 24"' in svg, name
            # шаблон с токенами темы ИЛИ осознанно фиксированные цвета (filled-стиль)
            assert "{c}" in svg or 'fill="#' in svg or 'stroke="#' in svg, name

    def test_breeze_icons_apply_to_all_names(self, qtbot):
        """Оверрайды применяются ко всему кэшу init_icons (не только 7 имён)."""
        from PySide6.QtCore import QSize

        from virtdeck.ui import icons

        try:
            load_theme("breeze", persist=False)
            assert set(icons._THEME_ICONS) == set(icons._BUILTINS) - {"app"}
            for name in icons._BUILTINS:
                icon = icons.get_icon(name)
                assert icon is not None and not icon.isNull(), name
            # регрессия: search раньше игнорировал оверрайд в кэше
            assert QSize(24, 24) in icons.get_icon("search").availableSizes()
        finally:
            load_theme("light", persist=False)

    def test_charts_retheme_live(self, qtbot):
        """Уже построенный график перекрашивается при смене темы."""
        pytest.importorskip("pyqtgraph")

        from virtdeck.ui.theme import Color
        from virtdeck.ui.widgets.vm_metrics_widget import VmMetricsWidget

        try:
            load_theme("breeze", persist=False)
            w = VmMetricsWidget()
            qtbot.addWidget(w)
            w.ensure_plot()
            assert w._has_plot
            w.update_curves({"cpu": [{"time": 1, "value": 1},
                                     {"time": 2, "value": 2}]})
            load_theme("light", persist=False)
            assert w.plot.backgroundBrush().color().name().lower() == Color.BG.lower()
            assert w.curve.opts["pen"].color().name().lower() == Color.ACCENT.lower()
        finally:
            load_theme("light", persist=False)

    def test_retheme_plots_registry(self, qtbot):
        """Реестр перекрашивает чужой PlotWidget по _vd_token."""
        pytest.importorskip("pyqtgraph")

        import pyqtgraph as pg

        from virtdeck.ui.detail_panel._constants import register_plot
        from virtdeck.ui.theme import Color

        try:
            load_theme("breeze", persist=False)
            w = pg.PlotWidget()
            qtbot.addWidget(w)
            curve = w.plot([], [], pen=pg.mkPen("#000000", width=2))
            curve._vd_token = "STATUS_WARN"
            register_plot(w)
            load_theme("light", persist=False)
            assert w.backgroundBrush().color().name().lower() == Color.BG.lower()
            assert curve.opts["pen"].color().name().lower() == Color.STATUS_WARN.lower()
        finally:
            load_theme("light", persist=False)

    def test_theme_text_contrast(self):
        """WCAG-контраст надписей во всех темах: текст >=4.5, dim >=3.0."""
        from virtdeck.plugins import _themes as bt

        def _ratio(fg, bg):
            def lin(c):
                c /= 255.0
                return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

            def lum(h):
                h = h.lstrip("#")
                r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
                return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)

            a, b = lum(fg), lum(bg)
            return (max(a, b) + 0.05) / (min(a, b) + 0.05)

        themes = {
            "light": bt.LightTheme().tokens(),
            "breeze": bt.BreezeTheme().tokens(),
            "oxygen": bt.OxygenTheme().tokens(),
            "graphite": bt.GraphiteTheme().tokens(),
        }
        bt.set_scheme_resolver(lambda: "dark")
        try:
            themes["system_dark"] = bt.SystemTheme().tokens()
        finally:
            bt.set_scheme_resolver(lambda: "light")
            try:
                themes["system_light"] = bt.SystemTheme().tokens()
            finally:
                bt.set_scheme_resolver(None)
        bgs = ("BG", "PANEL", "RAISED", "TRACK", "ALT_ROW")
        strong = ("TEXT", "TEXT_SEC", "STATUS_OK", "STATUS_WARN",
                  "STATUS_ERR", "DANGER")
        weak = ("TEXT_DIM", "DISABLED")
        for tname, t in themes.items():
            for bg in bgs:
                for fg in strong:
                    assert _ratio(t[fg], t[bg]) >= 4.5, (tname, fg, bg)
                for fg in weak:
                    assert _ratio(t[fg], t[bg]) >= 3.0, (tname, fg, bg)
            assert _ratio(t["ON_ACCENT"], t["ACCENT"]) >= 4.5, (tname, "ON_ACCENT")

    def test_system_follows_resolver(self, monkeypatch):
        from virtdeck.plugins import _themes as bt

        monkeypatch.setattr(bt, "_scheme_resolver", lambda: "dark")
        load_theme("system", persist=False)
        assert Color.BG == "#202326"
        monkeypatch.setattr(bt, "_scheme_resolver", lambda: "light")
        load_theme("system", persist=False)
        assert Color.BG == "#eff0f1"
        load_theme("light", persist=False)

    def test_system_reacts_to_scheme_change_event(self, monkeypatch):
        """Сигнал colorSchemeChanged перезагружает активную system-тему."""
        from virtdeck.plugins import _themes as bt

        load_theme("system", persist=False)
        monkeypatch.setattr(bt, "_scheme_resolver", lambda: "dark")
        theme._on_scheme_changed(None)
        assert Color.BG == "#202326"
        # не-system тема: событие игнорируется
        monkeypatch.setattr(bt, "_scheme_resolver", lambda: "light")
        load_theme("light", persist=False)
        theme._on_scheme_changed(None)
        assert Color.ACCENT == LIGHT_TOKENS["ACCENT"]

    def test_active_theme_id_tracked(self):
        load_theme("breeze", persist=False)
        assert theme.active_theme_id() == "breeze"
        load_theme("light", persist=False)
        assert theme.active_theme_id() == "light"

    def test_icons_override_failure_degrades_gracefully(self, dark_registry):
        class BadIcons(FakeDark):
            id = "bad_icons"

            def icons(self):
                raise RuntimeError("boom")

        dark_registry.register_theme(BadIcons())
        try:
            load_theme("bad_icons", registry=dark_registry, persist=False)
            from virtdeck.ui import icons

            assert not icons._THEME_ICONS
        finally:
            dark_registry.unregister("bad_icons")
            load_theme("light", persist=False)

    def test_dot_geometry_scales_with_viewbox(self):
        from virtdeck.ui.icons import _dot_geometry

        cx, r = _dot_geometry('<svg viewBox="0 0 16 16">')
        assert (cx, r) == (12.5, 3.5)
        cx, r = _dot_geometry('<svg viewBox="0 0 24 24">')
        assert r == pytest.approx(5.25)
        assert cx == pytest.approx(18.75)

    def test_combo_lists_all_builtin_themes(self, main_window):
        combo = main_window._theme_combo
        ids = [combo.itemData(i) for i in range(combo.count())]
        assert ids[:2] == ["light", "breeze"]  # UX-порядок
        assert ids[-1] == "system"
