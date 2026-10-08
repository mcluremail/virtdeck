"""VirtDeck brand: the designer brand kit (V+D monogram, 2026-09-15).

Assets are vector SVGs from `virtdeck/ui/brand_assets/`: app icons
(light/dark tiles), brand lockups, marks (including monochrome) and a
tray set with ok/error/offline/update states. Brand colors are fixed;
the theme only picks the light/dark variant (by Color.BG luminance).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from .icons import base_size

ASSETS = Path(__file__).parent / "brand_assets"
TRAY_STATES = ("ok", "error", "offline", "update")
MARK_VARIANTS = ("light", "dark", "mono", "mono-white")

# Icon cache: the tray redraws on every refresh cycle, no need to re-render SVG
_ICON_CACHE: dict[tuple, QIcon] = {}

_LOCKUP_ASPECT = 1240 / 320  # designer lockup viewBox


def _svg_bytes(name: str) -> QByteArray:
    return QByteArray((ASSETS / f"{name}.svg").read_bytes())


def _render(name: str, width: int, height: int) -> QPixmap:
    renderer = QSvgRenderer(_svg_bytes(name))
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


def is_dark() -> bool:
    """Is the current theme dark? Heuristic based on Color.BG luminance."""
    from .theme import Color

    hexval = Color.BG.lstrip("#")
    try:
        r, g, b = (int(hexval[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return False
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0 < 0.5


def _variant(variant: str | None) -> str:
    """Resolve the variant: 'light'|'dark' (None -> by theme)."""
    v = variant or ("dark" if is_dark() else "light")
    if v not in ("light", "dark"):
        raise ValueError(f"unknown brand variant: {variant!r}")
    return v


def render_pixmap(size: int, variant: str = "light") -> QPixmap:
    """Mark (monogram without the tile) as a QPixmap of the given size.

    Mark variants: light/dark (colored) and mono/mono-white (monochrome).
    """
    if variant not in MARK_VARIANTS:
        raise ValueError(f"unknown mark variant: {variant!r}")
    return _render(f"mark-{variant}", size, size)


def lockup_pixmap(height: int = 22, variant: str | None = None) -> QPixmap:
    """Lockup "mark + VirtDeck" preserving the designer's aspect ratio."""
    width = max(1, round(height * _LOCKUP_ASPECT))
    return _render(f"lockup-{_variant(variant)}", width, height)


def make_logo_icon(size: int = 256, variant: str | None = None) -> QIcon:
    """App icon (designer tile: window, taskbar)."""
    v = _variant(variant)
    key = ("logo", v, size)
    icon = _ICON_CACHE.get(key)
    if icon is None:
        icon = QIcon(_render(f"icon-{v}", size, size))
        _ICON_CACHE[key] = icon
    return icon


def tray_icon(state: str = "ok", variant: str | None = None,
              compact: bool = False) -> QIcon:
    """Tray icon for a state: ok | error | offline | update."""
    if state not in TRAY_STATES:
        raise ValueError(f"unknown tray state: {state!r}")
    v = _variant(variant)
    name = f"tray-{state}-{v}" + ("-compact" if compact else "")
    key = ("tray", name)
    icon = _ICON_CACHE.get(key)
    if icon is None:
        icon = QIcon(_render(name, 64, 64))
        _ICON_CACHE[key] = icon
    return icon


class BrandWidget(QWidget):
    """Brand lockup in the toolbar: the designer's vector lockup, themed variant."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(0)
        self._label = QLabel(self)
        self._variant: str | None = None
        layout.addWidget(self._label)
        self.restyle()

    def restyle(self):
        """Switch the lockup variant to the active theme (theme engine)."""
        v = _variant(None)
        if v == self._variant and not self._label.pixmap().isNull():
            return
        self._variant = v
        # The lockup scales from the theme's base icon size (24px -> 42px,
        # 1.75 factor per user request): mark and wordmark read well large.
        height = max(22, round(base_size() * 1.75))
        self._label.setPixmap(lockup_pixmap(height, v))
        self._label.setFixedSize(self._label.pixmap().size())


def make_brand_widget(parent=None) -> BrandWidget:
    return BrandWidget(parent)
