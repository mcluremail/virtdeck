"""Built-in themes (ThemePlugin v1).

Exact palette values are taken from the KDE schemes: breeze
(colors/BreezeLight.colors, BreezeDark.colors) and oxygen
(color-schemes/Oxygen.colors). Values commented "derived" are absent
from the schemes — derived from their base colors (Breeze renders
disabled via ColorEffects and the schemes have no borders). Graphite
is our own neutral theme.
"""

from __future__ import annotations

from ..ui.theme import LIGHT_TOKENS
from .base import ThemePlugin


class LightTheme:
    """Light theme — built-in plugin over the default palette."""

    _tokens: dict[str, str] | None = None

    @property
    def id(self) -> str:
        return "light"

    @property
    def name(self) -> str:
        return "Light"

    def tokens(self) -> dict[str, str]:
        # The snapshot is taken lazily on the first tokens(): at that
        # point Color still holds the default (light) palette, and
        # re-activations must not inherit values from other themes.
        if LightTheme._tokens is None:
            LightTheme._tokens = dict(LIGHT_TOKENS)
        return dict(LightTheme._tokens)

    def extra_qss(self) -> str:
        return ""

    def icons(self) -> dict[str, str] | None:
        return None

    @property
    def icon_size(self) -> int:
        return 24


# ── Breeze — signature filled-color set (fixed colors, treated as brand) ──

_BREEZE_DENSITY_QSS = """
/* Row density for 24px icons (Breeze) — compact tree rows */
QTreeWidget::item, QTreeView::item { padding: 1px 2px; min-height: 20px; }
QToolBar QToolButton { padding: 3px; margin: 1px; }
"""


class BreezeTheme:
    """Breeze Light — KDE Plasma light theme (24px icons)."""

    _TOKENS: dict[str, str] = {
        "BG": "#eff0f1",            # Window
        "PANEL": "#fcfcfc",         # Button
        "RAISED": "#ffffff",        # View
        "TRACK": "#e3e5e7",         # Window alternate
        "ALT_ROW": "#f7f7f7",       # View alternate
        "BORDER": "#c3c7cb",        # derived
        "BORDER_LIGHT": "#d8dbde",  # derived
        "BORDER_STRONG": "#a7abaf",  # derived
        "TEXT": "#232629",          # Window foreground
        "TEXT_SEC": "#58656f",      # derived, contrast >=4.5 on light backgrounds
        "TEXT_DIM": "#707880",      # derived, contrast >=3.0
        "DISABLED": "#707880",      # derived, contrast >=3.0
        "ON_ACCENT": "#1d2124",     # Selection foreground: dark on light-blue accent
        "ACCENT": "#3daee9",        # DecorationFocus
        "ACCENT_HOVER": "#55b8ec",  # derived
        "ACCENT_LIGHT": "#a3d4fa",  # Button alternate (inactive selection)
        "ACCENT_PRESSED": "#2f96d3",  # derived
        "SUCCESS": "#166534",       # Positive, contrast >=4.5
        "SUCCESS_LIGHT": "#e2f6ea",  # derived
        "WARNING": "#87590a",       # Neutral, contrast >=4.5
        "WARNING_TEXT": "#87590a",  # derived, contrast >=4.5
        "DANGER": "#b02a37",        # Negative, contrast >=4.5
        "DANGER_SOLID": "#da4453",
        "DANGER_SOLID_HOVER": "#e36a76",  # derived
        "DANGER_SOLID_PRESSED": "#b03745",  # Selection negative
        "STATUS_OK": "#166534",     # derived, contrast >=4.5
        "STATUS_WARN": "#87590a",   # derived, contrast >=4.5
        "STATUS_ERR": "#b02a37",    # derived, contrast >=4.5
        "HOVER": "#e3e5e7",         # Window alternate
        "ROW_WARN": "#fdf1e3",      # derived (warning tint)
        "TOAST_BG": "#2a2e32",      # Complementary background
        "SCROLLBAR_BG": "#f0f1f2",  # derived
        "SCROLLBAR_HANDLE": "#b9bec4",  # derived
        "SCROLLBAR_HOVER": "#9fa6ad",  # derived
        "ICON_FG": "#232629",
        "ICON_FG_DIM": "#707d8a",
        # icon color layer (Д5/S2) — brand hues, one language in every theme
        "ICON_BRAND": "#3d8bfd",
        "ICON_BRAND_DEEP": "#2563eb",
        "ICON_BRAND_SOFT": "#93c5fd",
        "ICON_OK": "#22c55e",
        "ICON_ERR": "#ef4444",
        "ICON_WARN": "#f59e0b",
        "ICON_POOL": "#8b5cf6",
    }

    @property
    def id(self) -> str:
        return "breeze"

    @property
    def name(self) -> str:
        return "Breeze"

    def tokens(self) -> dict[str, str]:
        return dict(self._TOKENS)

    def extra_qss(self) -> str:
        return _BREEZE_DENSITY_QSS

    def icons(self) -> dict[str, str] | None:
        # Д5/S2: the color layer moved into the builtin set (token-driven,
        # one shape language for every theme) — no per-theme SVG overrides.
        return None

    @property
    def icon_size(self) -> int:
        return 24


class BreezeDarkTheme(BreezeTheme):
    """Breeze Dark — KDE Plasma dark theme (24px icons)."""

    _TOKENS: dict[str, str] = {
        "BG": "#202326",            # Window
        "PANEL": "#292c30",         # Button
        "RAISED": "#141618",        # View
        "TRACK": "#2c3034",         # derived
        "ALT_ROW": "#1d1f22",       # View alternate
        "BORDER": "#3b4046",        # derived
        "BORDER_LIGHT": "#34383d",  # derived
        "BORDER_STRONG": "#4d5359",  # derived
        "TEXT": "#fcfcfc",          # Window foreground
        "TEXT_SEC": "#a1a9b1",      # Window inactive
        "TEXT_DIM": "#7d868e",      # derived
        "DISABLED": "#757d84",      # derived, contrast >=3.0 on dark backgrounds
        "ON_ACCENT": "#1d2124",     # Selection foreground: dark on light-blue accent
        "ACCENT": "#3daee9",        # DecorationFocus
        "ACCENT_HOVER": "#55b8ec",  # derived
        "ACCENT_LIGHT": "#1e5774",  # Button alternate (inactive selection)
        "ACCENT_PRESSED": "#2f96d3",  # derived
        "SUCCESS": "#27ae60",
        "SUCCESS_LIGHT": "#1c3827",  # derived
        "WARNING": "#f67400",
        "WARNING_TEXT": "#f89b47",  # derived
        "DANGER": "#e97e8a",        # derived, contrast >=4.5 on dark backgrounds
        "DANGER_SOLID": "#da4453",
        "DANGER_SOLID_HOVER": "#e36a76",  # derived
        "DANGER_SOLID_PRESSED": "#b03745",  # Selection negative
        "STATUS_OK": "#27ae60",
        "STATUS_WARN": "#f67400",
        "STATUS_ERR": "#e97e8a",    # derived, contrast >=4.5 on dark backgrounds
        "HOVER": "#34383d",         # derived
        "ROW_WARN": "#44331a",      # derived (warning tint)
        "TOAST_BG": "#17191c",      # derived (darker than BG)
        "SCROLLBAR_BG": "#202326",  # derived
        "SCROLLBAR_HANDLE": "#4a5058",  # derived
        "SCROLLBAR_HOVER": "#5b6269",  # derived
        "ICON_FG": "#fcfcfc",
        "ICON_FG_DIM": "#a1a9b1",
        # icon color layer (Д5/S2) — brand hues, one language in every theme
        "ICON_BRAND": "#3d8bfd",
        "ICON_BRAND_DEEP": "#2563eb",
        "ICON_BRAND_SOFT": "#93c5fd",
        "ICON_OK": "#22c55e",
        "ICON_ERR": "#ef4444",
        "ICON_WARN": "#f59e0b",
        "ICON_POOL": "#8b5cf6",
    }

    @property
    def id(self) -> str:
        return "breeze_dark"

    @property
    def name(self) -> str:
        return "Breeze Dark"


class OxygenTheme:
    """Oxygen — classic KDE 4 theme (16px icons)."""

    _TOKENS: dict[str, str] = {
        "BG": "#d6d2d0",            # Window
        "PANEL": "#dfdcdb",         # Button
        "RAISED": "#ffffff",        # View
        "TRACK": "#cfcbc9",         # derived
        "ALT_ROW": "#f8f7f6",       # View alternate
        "BORDER": "#aaa7a5",        # derived
        "BORDER_LIGHT": "#c0bdbb",  # derived
        "BORDER_STRONG": "#8f8c8a",  # derived
        "TEXT": "#1f1c1b",          # View foreground
        "TEXT_SEC": "#55524f",      # derived, contrast >=4.5 on light backgrounds
        "TEXT_DIM": "#6b6865",      # derived, contrast >=3.0
        "DISABLED": "#6b6865",      # derived, contrast >=3.0
        "ON_ACCENT": "#1d2124",     # Selection foreground: dark on blue accent
        "ACCENT": "#3aa7dd",        # DecorationFocus
        "ACCENT_HOVER": "#6ed6ff",  # DecorationHover
        "ACCENT_LIGHT": "#cbe9f9",  # derived
        "ACCENT_PRESSED": "#3e8acc",  # Selection alternate
        "SUCCESS": "#0f5c2e",       # Positive, contrast >=4.5
        "SUCCESS_LIGHT": "#ddf0e2",  # derived
        "WARNING": "#6e4a08",       # Neutral, contrast >=4.5
        "WARNING_TEXT": "#6e4a08",  # derived, contrast >=4.5
        "DANGER": "#97251b",        # Negative, contrast >=4.5
        "DANGER_SOLID": "#bf0303",
        "DANGER_SOLID_HOVER": "#d63c3c",  # derived
        "DANGER_SOLID_PRESSED": "#9c0e0e",  # Selection negative
        "STATUS_OK": "#0f5c2e",     # derived, contrast >=4.5
        "STATUS_WARN": "#6e4a08",   # derived, contrast >=4.5
        "STATUS_ERR": "#97251b",    # derived, contrast >=4.5
        "HOVER": "#dad9d8",         # Window alternate
        "ROW_WARN": "#f5ecd9",      # derived (warning tint)
        "TOAST_BG": "#181513",      # Tooltip background
        "SCROLLBAR_BG": "#d6d2d0",  # derived
        "SCROLLBAR_HANDLE": "#a3a09d",  # derived
        "SCROLLBAR_HOVER": "#8a8785",  # derived
        "ICON_FG": "#221f1e",       # Window foreground
        "ICON_FG_DIM": "#676563",   # derived
        # icon color layer (Д5/S2) — brand hues, one language in every theme
        "ICON_BRAND": "#3d8bfd",
        "ICON_BRAND_DEEP": "#2563eb",
        "ICON_BRAND_SOFT": "#93c5fd",
        "ICON_OK": "#22c55e",
        "ICON_ERR": "#ef4444",
        "ICON_WARN": "#f59e0b",
        "ICON_POOL": "#8b5cf6",
    }

    @property
    def id(self) -> str:
        return "oxygen"

    @property
    def name(self) -> str:
        return "Oxygen"

    def tokens(self) -> dict[str, str]:
        return dict(self._TOKENS)

    def extra_qss(self) -> str:
        return ""

    def icons(self) -> dict[str, str] | None:
        return None

    @property
    def icon_size(self) -> int:
        return 24


class GraphiteTheme:
    """Graphite — our own neutral dark theme."""

    _TOKENS: dict[str, str] = {
        "BG": "#2b2d2f",
        "PANEL": "#333537",
        "RAISED": "#26282a",
        "TRACK": "#222425",
        "ALT_ROW": "#313335",
        "BORDER": "#3e4144",
        "BORDER_LIGHT": "#36393c",
        "BORDER_STRONG": "#4a4d50",
        "TEXT": "#e8eaec",
        "TEXT_SEC": "#a9adb1",
        "TEXT_DIM": "#7e8286",
        "DISABLED": "#84888c",      # derived, contrast >=3.0 on dark backgrounds
        "ON_ACCENT": "#1d1f21",
        "ACCENT": "#8fa6bb",        # light steel
        "ACCENT_HOVER": "#a1b5c7",
        "ACCENT_LIGHT": "#37424c",
        "ACCENT_PRESSED": "#7d94a9",
        "SUCCESS": "#7fbf8e",
        "SUCCESS_LIGHT": "#2c3a2f",
        "WARNING": "#d9a05b",
        "WARNING_TEXT": "#e0b077",
        "DANGER": "#e9949a",        # derived, contrast >=4.5 on dark backgrounds
        "DANGER_SOLID": "#b8555c",
        "DANGER_SOLID_HOVER": "#c6676e",
        "DANGER_SOLID_PRESSED": "#9c454c",
        "STATUS_OK": "#7fbf8e",
        "STATUS_WARN": "#d9a05b",
        "STATUS_ERR": "#e9949a",    # derived, contrast >=4.5 on dark backgrounds
        "HOVER": "#383b3e",
        "ROW_WARN": "#3d3527",
        "TOAST_BG": "#1e2022",
        "SCROLLBAR_BG": "#2b2d2f",
        "SCROLLBAR_HANDLE": "#45484c",
        "SCROLLBAR_HOVER": "#565a5e",
        "ICON_FG": "#c9cdd1",
        "ICON_FG_DIM": "#8f9397",
        # icon color layer (Д5/S2) — brand hues, one language in every theme
        "ICON_BRAND": "#3d8bfd",
        "ICON_BRAND_DEEP": "#2563eb",
        "ICON_BRAND_SOFT": "#93c5fd",
        "ICON_OK": "#22c55e",
        "ICON_ERR": "#ef4444",
        "ICON_WARN": "#f59e0b",
        "ICON_POOL": "#8b5cf6",
    }

    @property
    def id(self) -> str:
        return "graphite"

    @property
    def name(self) -> str:
        return "Graphite"

    def tokens(self) -> dict[str, str]:
        return dict(self._TOKENS)

    def extra_qss(self) -> str:
        return ""

    def icons(self) -> dict[str, str] | None:
        return None

    @property
    def icon_size(self) -> int:
        return 24


# ── System (follows the OS scheme) ───────────────────────────────────

_scheme_resolver = None


def set_scheme_resolver(fn) -> None:
    """Engine hook: fn() -> "light" | "dark" (current OS scheme)."""
    global _scheme_resolver
    _scheme_resolver = fn


def _resolved_breeze():
    resolver = _scheme_resolver or (lambda: "light")
    return BreezeDarkTheme() if resolver() == "dark" else BreezeTheme()


class SystemTheme:
    """System theme: Breeze Light/Dark based on the environment colorScheme."""

    @property
    def id(self) -> str:
        return "system"

    @property
    def name(self) -> str:
        return "System"

    def tokens(self) -> dict[str, str]:
        return _resolved_breeze().tokens()

    def extra_qss(self) -> str:
        return _resolved_breeze().extra_qss()

    def icons(self) -> dict[str, str] | None:
        return _resolved_breeze().icons()

    @property
    def icon_size(self) -> int:
        return _resolved_breeze().icon_size


# Explicit contract check at module import.
assert isinstance(LightTheme(), ThemePlugin)
for _plugin in (BreezeTheme(), BreezeDarkTheme(), OxygenTheme(),
                GraphiteTheme(), SystemTheme()):
    assert isinstance(_plugin, ThemePlugin)
