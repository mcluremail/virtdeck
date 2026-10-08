from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .theme import Color

ICON_SIZE = 24
_BASE_SIZE = ICON_SIZE  # base size; the theme engine changes it via set_base_size()


def set_base_size(size):
    """Base icon size (the theme engine applies theme.icon_size)."""
    global _BASE_SIZE
    _BASE_SIZE = int(size)


def base_size():
    """Current base icon size (24 px in all themes)."""
    return _BASE_SIZE


def reset_icons():
    """Reset the icon cache — after a theme change (redraw with new colors)."""
    global _icons
    _icons = None


_THEME_ICONS: dict = {}


def set_theme_icons(overrides):
    """SVG overrides of the active theme (partial; fallback to built-ins)."""
    global _THEME_ICONS
    _THEME_ICONS = overrides or {}


# Relative sizes of small/large icons vs the base size.
_SCALES = {
    "app": 1.5,  # brand mark — the only exception
}


def _sized(scale):
    return max(10, round(_BASE_SIZE * scale))


def _fmt(tmpl):
    """Format the template with tokens; a foreign SVG without placeholders — as-is."""
    try:
        return tmpl.format(c=Color.ICON_FG, c2=Color.ICON_FG_DIM,
                           ok=Color.STATUS_OK, err=Color.STATUS_ERR,
                           b=Color.BORDER)
    except (KeyError, IndexError):
        return tmpl


def _status_color(status):
    if status in ("online", "running", "OK"):
        return Color.STATUS_OK
    elif status in ("offline", "stopped", "error"):
        return Color.STATUS_ERR
    elif status in ("paused", "warning"):
        return Color.STATUS_WARN
    return None

def _make_icon(svg, size=None):
    if size is None:
        size = _BASE_SIZE
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)

_CLUSTER = """<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<circle cx="8" cy="8" r="2" fill="{c2}" stroke="{c}" stroke-width="1.2"/>
<circle cx="3" cy="3.5" r="1.5" fill="none" stroke="{c}" stroke-width="1.2"/>
<circle cx="13" cy="3.5" r="1.5" fill="none" stroke="{c}" stroke-width="1.2"/>
<circle cx="3" cy="12.5" r="1.5" fill="none" stroke="{c}" stroke-width="1.2"/>
<circle cx="13" cy="12.5" r="1.5" fill="none" stroke="{c}" stroke-width="1.2"/>
<line x1="8" y1="6" x2="4.1" y2="4.6" stroke="{c}" stroke-width="1"/>
<line x1="8" y1="6" x2="11.9" y2="4.6" stroke="{c}" stroke-width="1"/>
<line x1="8" y1="10" x2="4.1" y2="11.4" stroke="{c}" stroke-width="1"/>
<line x1="8" y1="10" x2="11.9" y2="11.4" stroke="{c}" stroke-width="1"/>
</svg>"""

_HOST = """<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<rect x="2" y="2" width="12" height="12" rx="1" fill="none" stroke="{c}" stroke-width="1.4"/>
<rect x="4" y="4" width="5" height="1.5" rx="0.5" fill="{c}"/>
<rect x="4" y="7" width="8" height="1.5" rx="0.5" fill="{c}"/>
<rect x="4" y="10" width="3" height="1.5" rx="0.5" fill="{c2}"/>
<circle cx="12.5" cy="4.75" r="1.2" fill="{ok}"/>
</svg>"""

_VM = """<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<rect x="1" y="2" width="14" height="9" rx="1" fill="none" stroke="{c}" stroke-width="1.4"/>
<polyline points="3,8 5,6.5 3,5" fill="none" stroke="{c}" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
<line x1="6.5" y1="8" x2="9" y2="8" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
<rect x="5.5" y="11" width="5" height="1" rx="0" fill="{c}"/>
<line x1="4" y1="13" x2="12" y2="13" stroke="{c}" stroke-width="1.4" stroke-linecap="round"/>
</svg>"""

_POOL = """<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<path d="M1 5 L4.5 5 L6 3 L15 3 L15 13 L1 13 Z" fill="none" stroke="{c}" stroke-width="1.3" stroke-linejoin="round"/>
<rect x="5" y="7" width="6" height="4" rx="0.5" fill="none" stroke="{c}" stroke-width="1"/>
<line x1="7" y1="11" x2="9" y2="11" stroke="{c}" stroke-width="1"/>
</svg>"""

_STORAGE = """<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<ellipse cx="8" cy="4" rx="6" ry="2" fill="none" stroke="{c}" stroke-width="1.3"/>
<line x1="2" y1="4" x2="2" y2="12" stroke="{c}" stroke-width="1.3"/>
<line x1="14" y1="4" x2="14" y2="12" stroke="{c}" stroke-width="1.3"/>
<ellipse cx="8" cy="12" rx="6" ry="2" fill="none" stroke="{c}" stroke-width="1.3"/>
<circle cx="11" cy="12" r="1" fill="{c2}"/>
</svg>"""

_FOLDER = """<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<path d="M1 4 L5.5 4 L7 2.5 L15 2.5 L15 13 L1 13 Z" fill="none" stroke="{c}" stroke-width="1.3" stroke-linejoin="round"/>
<line x1="1" y1="6" x2="15" y2="6" stroke="{c}" stroke-width="1"/>
</svg>"""

_APP = """<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<rect x="2" y="2" width="20" height="20" rx="0" fill="none" stroke="{c}" stroke-width="1.5"/>
<rect x="5" y="5" width="14" height="3" rx="0" fill="{c}"/>
<rect x="5" y="10" width="14" height="1" rx="0" fill="{c}"/>
<rect x="5" y="13" width="14" height="1" rx="0" fill="{c}"/>
<rect x="5" y="16" width="14" height="1" rx="0" fill="{c}"/>
<rect x="8" y="22" width="8" height="1" rx="0" fill="{c}"/>
<rect x="11" y="20" width="2" height="2" rx="0" fill="{c}"/>
</svg>"""

_REFRESH = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<path d="M2 7 A5 5 0 0 1 11.5 4" fill="none" stroke="{c}" stroke-width="1.5" stroke-linecap="round"/>
<polyline points="11.5,2 11.5,4.5 9,4.5" fill="none" stroke="{c}" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M12 7 A5 5 0 0 1 2.5 10" fill="none" stroke="{c}" stroke-width="1.5" stroke-linecap="round"/>
<polyline points="2.5,12 2.5,9.5 5,9.5" fill="none" stroke="{c}" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

_MONITOR = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<rect x="1" y="1.5" width="12" height="8" rx="1" fill="none" stroke="{c}" stroke-width="1.3"/>
<rect x="3" y="3.5" width="5" height="1" rx="0.5" fill="{c}"/>
<rect x="3" y="5.5" width="8" height="1" rx="0.5" fill="{c2}"/>
<rect x="3" y="7" width="6" height="1" rx="0.5" fill="{c2}"/>
<line x1="5" y1="9.5" x2="9" y2="9.5" stroke="{c}" stroke-width="1"/>
<line x1="7" y1="9.5" x2="7" y2="11.5" stroke="{c}" stroke-width="1"/>
<line x1="4" y1="13" x2="10" y2="13" stroke="{c}" stroke-width="1.3" stroke-linecap="round"/>
</svg>"""

_HARDWARE = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<rect x="4" y="4" width="6" height="6" rx="0.5" fill="none" stroke="{c}" stroke-width="1.3"/>
<line x1="5" y1="4" x2="5" y2="2" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
<line x1="7" y1="4" x2="7" y2="2" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
<line x1="9" y1="4" x2="9" y2="2" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
<line x1="5" y1="10" x2="5" y2="12" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
<line x1="7" y1="10" x2="7" y2="12" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
<line x1="9" y1="10" x2="9" y2="12" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
<line x1="4" y1="6" x2="2" y2="6" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
<line x1="4" y1="8" x2="2" y2="8" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
<line x1="10" y1="6" x2="12" y2="6" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
<line x1="10" y1="8" x2="12" y2="8" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
<circle cx="7" cy="7" r="1" fill="{c2}"/>
</svg>"""

_OPTIONS = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<line x1="1" y1="3" x2="13" y2="3" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
<line x1="1" y1="7" x2="13" y2="7" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
<line x1="1" y1="11" x2="13" y2="11" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
<circle cx="9" cy="3" r="1.8" fill="{c2}" stroke="{c}" stroke-width="1.3"/>
<circle cx="4" cy="7" r="1.8" fill="{c2}" stroke="{c}" stroke-width="1.3"/>
<circle cx="10" cy="11" r="1.8" fill="{c2}" stroke="{c}" stroke-width="1.3"/>
</svg>"""

_HISTORY = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<circle cx="7" cy="7" r="5.5" fill="none" stroke="{c}" stroke-width="1.3"/>
<polyline points="7,3.5 7,7 9.5,8.5" fill="none" stroke="{c}" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

_DISK = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<rect x="2" y="3" width="10" height="8" rx="1" fill="none" stroke="{c}" stroke-width="1.3"/>
<rect x="4" y="5" width="4" height="1.5" rx="0.5" fill="{c2}"/>
<circle cx="10.5" cy="9" r="1" fill="{c2}"/>
</svg>"""

_NETWORK = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<circle cx="7" cy="7" r="1.5" fill="{c2}" stroke="{c}" stroke-width="1"/>
<circle cx="2.5" cy="3" r="1.5" fill="none" stroke="{c}" stroke-width="1.2"/>
<circle cx="11.5" cy="3" r="1.5" fill="none" stroke="{c}" stroke-width="1.2"/>
<circle cx="7" cy="12" r="1.5" fill="none" stroke="{c}" stroke-width="1.2"/>
<line x1="7" y1="5.5" x2="3.7" y2="4.2" stroke="{c}" stroke-width="1"/>
<line x1="7" y1="5.5" x2="10.3" y2="4.2" stroke="{c}" stroke-width="1"/>
<line x1="7" y1="8.5" x2="7" y2="10.5" stroke="{c}" stroke-width="1"/>
</svg>"""

_SERVICES = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<line x1="5" y1="3" x2="12" y2="3" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
<line x1="5" y1="7" x2="12" y2="7" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
<line x1="5" y1="11" x2="12" y2="11" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
<circle cx="2.5" cy="3" r="1.2" fill="{ok}"/>
<circle cx="2.5" cy="7" r="1.2" fill="{ok}"/>
<circle cx="2.5" cy="11" r="1.2" fill="{err}"/>
</svg>"""

_SNAPSHOT = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<rect x="1" y="4" width="12" height="9" rx="1" fill="none" stroke="{c}" stroke-width="1.3"/>
<path d="M4 4 L5 2 L9 2 L10 4" fill="none" stroke="{c}" stroke-width="1.2" stroke-linejoin="round"/>
<circle cx="7" cy="8.5" r="2.5" fill="none" stroke="{c}" stroke-width="1.2"/>
<circle cx="7" cy="8.5" r="1" fill="{c2}"/>
</svg>"""

_BACKUP = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<rect x="2" y="1" width="10" height="12" rx="1" fill="none" stroke="{c}" stroke-width="1.3"/>
<line x1="4.5" y1="4" x2="9.5" y2="4" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
<line x1="4.5" y1="6.5" x2="9.5" y2="6.5" stroke="{c2}" stroke-width="1" stroke-linecap="round"/>
<polyline points="7,8.5 7,11 5.5,9.5" fill="none" stroke="{c}" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
<line x1="7" y1="11" x2="8.5" y2="9.5" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
</svg>"""

_RESTORE = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<rect x="2" y="1" width="10" height="12" rx="1" fill="none" stroke="{c}" stroke-width="1.3"/>
<line x1="4.5" y1="4" x2="9.5" y2="4" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
<line x1="4.5" y1="6.5" x2="9.5" y2="6.5" stroke="{c2}" stroke-width="1" stroke-linecap="round"/>
<polyline points="7,11 7,8.5 5.5,10" fill="none" stroke="{c}" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
<line x1="7" y1="8.5" x2="8.5" y2="10" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
</svg>"""

_ISO = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<circle cx="7" cy="7" r="5.5" fill="none" stroke="{c}" stroke-width="1.3"/>
<circle cx="7" cy="7" r="1.8" fill="{c2}" stroke="{c}" stroke-width="1"/>
<circle cx="7" cy="7" r="0.7" fill="{c2}"/>
<line x1="7" y1="1.5" x2="7" y2="4" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
</svg>"""

_TEMPLATE = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<rect x="2" y="1" width="10" height="12" rx="1" fill="none" stroke="{c}" stroke-width="1.3"/>
<line x1="4" y1="4" x2="10" y2="4" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
<line x1="4" y1="6.5" x2="10" y2="6.5" stroke="{c2}" stroke-width="1" stroke-linecap="round"/>
<rect x="4" y="8.5" width="6" height="3" rx="0.5" fill="{c2}" stroke="{c}" stroke-width="0.8"/>
</svg>"""

_TPM = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<rect x="2" y="3" width="10" height="8" rx="1" fill="none" stroke="{c}" stroke-width="1.3"/>
<rect x="4" y="5" width="2" height="2" fill="{c2}"/>
<rect x="7" y="5" width="2" height="2" fill="{c2}"/>
<rect x="4" y="8" width="2" height="2" fill="{c2}"/>
<rect x="7" y="8" width="2" height="2" fill="{c2}"/>
<line x1="10" y1="6" x2="12" y2="6" stroke="{c}" stroke-width="1" stroke-linecap="round"/>
</svg>"""

_EXPAND = """<svg viewBox="0 0 12 12" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<polyline points="1,4 1,1 4,1" fill="none" stroke="{c}" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
<polyline points="8,1 11,1 11,4" fill="none" stroke="{c}" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
<polyline points="1,8 1,11 4,11" fill="none" stroke="{c}" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
<polyline points="11,8 11,11 8,11" fill="none" stroke="{c}" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

_COLLAPSE = """<svg viewBox="0 0 12 12" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<polyline points="4,1 1,4 4,4" fill="none" stroke="{c}" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
<polyline points="11,4 8,4 8,1" fill="none" stroke="{c}" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
<polyline points="4,11 4,8 1,8" fill="none" stroke="{c}" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
<polyline points="8,8 11,8 8,11" fill="none" stroke="{c}" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

_ADD = """<svg viewBox="0 0 12 12" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<circle cx="6" cy="6" r="5" fill="none" stroke="{c}" stroke-width="1.3"/>
<line x1="6" y1="3.5" x2="6" y2="8.5" stroke="{c}" stroke-width="1.3" stroke-linecap="round"/>
<line x1="3.5" y1="6" x2="8.5" y2="6" stroke="{c}" stroke-width="1.3" stroke-linecap="round"/>
</svg>"""

_START = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<polygon points="3,2 12,7 3,12" fill="{c}" stroke="{c}" stroke-width="1.3" stroke-linejoin="round"/>
</svg>"""

_SHUTDOWN = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<path d="M4.5 3.5 A5 5 0 1 0 9.5 3.5" fill="none" stroke="{c}" stroke-width="1.5" stroke-linecap="round"/>
<line x1="7" y1="1.5" x2="7" y2="6.5" stroke="{c}" stroke-width="1.5" stroke-linecap="round"/>
</svg>"""

_REBOOT = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<path d="M2 7 A5 5 0 1 1 7 12" fill="none" stroke="{c}" stroke-width="1.5" stroke-linecap="round"/>
<polyline points="7,12 7,9.5 9.5,12" fill="none" stroke="{c}" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

_RESET = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<polyline points="8.5,1.5 4,7.5 7.5,7.5 5.5,12.5 10,6.5 6.5,6.5 8.5,1.5" fill="none" stroke="{c}" stroke-width="1.3" stroke-linejoin="round" stroke-linecap="round"/>
</svg>"""

_STOP = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<rect x="3" y="3" width="8" height="8" rx="1" fill="{c}"/>
</svg>"""

_CONSOLE = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<rect x="1" y="2" width="12" height="8" rx="1" fill="none" stroke="{c}" stroke-width="1.3"/>
<polyline points="3,7.5 4.5,6 3,4.5" fill="none" stroke="{c}" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
<line x1="6" y1="7.5" x2="8.5" y2="7.5" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
<line x1="5" y1="10" x2="9" y2="10" stroke="{c}" stroke-width="1" stroke-linecap="round"/>
<line x1="7" y1="10" x2="7" y2="12" stroke="{c}" stroke-width="1" stroke-linecap="round"/>
<line x1="4" y1="13" x2="10" y2="13" stroke="{c}" stroke-width="1.3" stroke-linecap="round"/>
</svg>"""

_RESUME = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<polygon points="1.5,3 6,7 1.5,11" fill="{c}"/>
<polygon points="7,3 11.5,7 7,11" fill="{c}"/>
</svg>"""

_LOADING = """<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<circle cx="8" cy="8" r="5" fill="none" stroke="{b}" stroke-width="2"/>
<path d="M8 3 A5 5 0 0 1 13 8" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/>
</svg>"""


def _dot_geometry(tmpl):
    """Status-dot geometry from the template viewBox (16 -> r3.5 @ 12.5)."""
    import re as _re

    m = _re.search(r'viewBox="0 0 (\d+)[\d. ]*"', tmpl)
    vb = float(m.group(1)) if m else 16.0
    k = vb / 16.0
    return vb - 3.5 * k, 3.5 * k


def _make_icon_with_dot(template, status):
    dot_color = _status_color(status)
    fmt = _fmt(template)
    if dot_color is None:
        return _make_icon(fmt)
    cx, r = _dot_geometry(template)
    svg = fmt.replace(
        "</svg>",
        f'<circle cx="{cx:.1f}" cy="{cx:.1f}" r="{r:.1f}" fill="{dot_color}" '
        f'stroke="{Color.ON_ACCENT}" stroke-width="{1.5 * r / 3.5:.2f}" '
        f'stroke-opacity="0.9"/></svg>'
    )
    return _make_icon(svg)


def _make_loading_icon(angle):
    svg = _LOADING.format(c=Color.ICON_FG, c2=Color.ICON_FG_DIM, b=Color.BORDER).replace(
        '<path d="M8 3',
        f'<path transform="rotate({angle} 8 8)" d="M8 3'
    )
    return _make_icon(svg)

make_loading_icon = _make_loading_icon

_SVG_TEMPLATES = {
    "host": _HOST,
    "vm": _VM,
    "cluster": _CLUSTER,
    "pool": _POOL,
}

_icons = None

_EXPORT = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<path d="M7 1.5 L7 9" fill="none" stroke="{c}" stroke-width="1.5" stroke-linecap="round"/>
<polyline points="4.5,4 7,1.5 9.5,4" fill="none" stroke="{c}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M3 9.5 L3 12 L11 12 L11 9.5" fill="none" stroke="{c}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

_IMPORT = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<path d="M7 5 L7 12.5" fill="none" stroke="{c}" stroke-width="1.5" stroke-linecap="round"/>
<polyline points="4.5,10 7,12.5 9.5,10" fill="none" stroke="{c}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M3 2 L3 5 L11 5 L11 2" fill="none" stroke="{c}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

_ABOUT = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<circle cx="7" cy="7" r="5.5" fill="none" stroke="{c}" stroke-width="1.3"/>
<circle cx="7" cy="3.8" r="0.9" fill="{c2}"/>
<rect x="6.3" y="5.5" width="1.4" height="5" rx="0.4" fill="{c2}"/>
</svg>"""

_LOCK = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<rect x="3" y="6.5" width="8" height="6" rx="1" fill="none" stroke="{c}" stroke-width="1.3"/>
<path d="M4.5 6.5 L4.5 4.5 A2.5 2.5 0 0 1 9.5 4.5 L9.5 6.5" fill="none" stroke="{c}" stroke-width="1.3" stroke-linecap="round"/>
<circle cx="7" cy="9.5" r="0.8" fill="{c2}"/>
</svg>"""

_UNLOCK = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<rect x="3" y="6.5" width="8" height="6" rx="1" fill="none" stroke="{c}" stroke-width="1.3"/>
<path d="M4.5 6.5 L4.5 4.5 A2.5 2.5 0 0 1 11 4.5 L11 6" fill="none" stroke="{c}" stroke-width="1.3" stroke-linecap="round"/>
<circle cx="7" cy="9.5" r="0.8" fill="{c2}"/>
</svg>"""

_MIGRATE = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<rect x="1.5" y="5.5" width="4" height="3" rx="0.5" fill="none" stroke="{c}" stroke-width="1.2"/>
<rect x="8.5" y="5.5" width="4" height="3" rx="0.5" fill="none" stroke="{c}" stroke-width="1.2"/>
<path d="M5.5 7 L8.5 7" fill="none" stroke="{c}" stroke-width="1.3" stroke-linecap="round"/>
<polyline points="7.5,6 8.5,7 7.5,8" fill="none" stroke="{c}" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

_CLONE = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<rect x="2" y="2" width="7" height="7" rx="0.8" fill="none" stroke="{c}" stroke-width="1.2"/>
<rect x="5" y="5" width="7" height="7" rx="0.8" fill="none" stroke="{c2}" stroke-width="1.2"/>
</svg>"""

_REMOVE = """<svg viewBox="0 0 12 12" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<circle cx="6" cy="6" r="5" fill="none" stroke="{c}" stroke-width="1.3"/>
<line x1="3.5" y1="6" x2="8.5" y2="6" stroke="{c}" stroke-width="1.3" stroke-linecap="round"/>
</svg>"""

_UPLOAD = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<path d="M7 12.5 L7 5" fill="none" stroke="{c}" stroke-width="1.5" stroke-linecap="round"/>
<polyline points="4.5,8 7,5 9.5,8" fill="none" stroke="{c}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M2.5 11 L2.5 12.5 L11.5 12.5 L11.5 11" fill="none" stroke="{c}" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

_DOWNLOAD = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<path d="M7 1.5 L7 9" fill="none" stroke="{c}" stroke-width="1.5" stroke-linecap="round"/>
<polyline points="4.5,6 7,9 9.5,6" fill="none" stroke="{c}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M2.5 11 L2.5 12.5 L11.5 12.5 L11.5 11" fill="none" stroke="{c}" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

_HA = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<path d="M7 2 L11.5 4.5 L11.5 8 Q11.5 11 7 12.5 Q2.5 11 2.5 8 L2.5 4.5 Z" fill="none" stroke="{c}" stroke-width="1.2" stroke-linejoin="round"/>
<path d="M5 7 L6.3 8.5 L9 5.5" fill="none" stroke="{c2}" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

_USB = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<rect x="5" y="1.5" width="4" height="8" rx="0.8" fill="none" stroke="{c}" stroke-width="1.2"/>
<line x1="6" y1="9.5" x2="6" y2="12" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
<line x1="8" y1="9.5" x2="8" y2="12" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
<circle cx="7" cy="5" r="0.7" fill="{c2}"/>
</svg>"""

_PCI = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<rect x="2.5" y="2" width="9" height="10" rx="0.8" fill="none" stroke="{c}" stroke-width="1.2"/>
<rect x="4.5" y="4" width="5" height="1.5" rx="0.3" fill="{c2}"/>
<line x1="4" y1="7" x2="10" y2="7" stroke="{c}" stroke-width="0.9" stroke-linecap="round"/>
<line x1="4" y1="9" x2="10" y2="9" stroke="{c}" stroke-width="0.9" stroke-linecap="round"/>
<line x1="4" y1="11" x2="10" y2="11" stroke="{c}" stroke-width="0.9" stroke-linecap="round"/>
</svg>"""

_SERIAL = """<svg viewBox="0 0 14 14" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<rect x="2" y="3" width="10" height="8" rx="0.8" fill="none" stroke="{c}" stroke-width="1.2"/>
<circle cx="4" cy="7" r="0.8" fill="{c2}"/>
<circle cx="7" cy="7" r="0.8" fill="{c2}"/>
<circle cx="10" cy="7" r="0.8" fill="{c2}"/>
</svg>"""

_USER = """<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<circle cx="8" cy="5.5" r="2.5" fill="none" stroke="{c}" stroke-width="1.3"/>
<path d="M3 13.5 C3 10.5 5.5 9 8 9 C10.5 9 13 10.5 13 13.5" fill="none" stroke="{c}" stroke-width="1.3" stroke-linecap="round"/>
</svg>"""

_TOKEN = """<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<rect x="3" y="5" width="10" height="7" rx="1" fill="none" stroke="{c}" stroke-width="1.3"/>
<circle cx="6" cy="8.5" r="0.9" fill="{c2}"/>
<line x1="8.5" y1="8.5" x2="11" y2="8.5" stroke="{c}" stroke-width="1" stroke-linecap="round"/>
<line x1="8" y1="3" x2="8" y2="5" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
</svg>"""

_GROUP = """<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<circle cx="5.5" cy="5" r="2" fill="none" stroke="{c}" stroke-width="1.2"/>
<circle cx="10.5" cy="5" r="2" fill="none" stroke="{c}" stroke-width="1.2"/>
<path d="M2.5 13 C2.5 10.5 4 9 5.5 9 C7 9 8.5 10.5 8.5 13" fill="none" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
<path d="M7.5 13 C7.5 10.5 9 9 10.5 9 C12 9 13.5 10.5 13.5 13" fill="none" stroke="{c}" stroke-width="1.2" stroke-linecap="round"/>
</svg>"""

_ROLE = """<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<rect x="3" y="3" width="10" height="10" rx="1" fill="none" stroke="{c}" stroke-width="1.3"/>
<circle cx="6" cy="7" r="0.8" fill="{c2}"/>
<circle cx="10" cy="7" r="0.8" fill="{c2}"/>
<line x1="5" y1="10" x2="11" y2="10" stroke="{c}" stroke-width="1" stroke-linecap="round"/>
</svg>"""

_ACL = """<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<rect x="4" y="7" width="8" height="6" rx="0.8" fill="none" stroke="{c}" stroke-width="1.3"/>
<path d="M5.5 7 L5.5 5 C5.5 3.5 6.5 2.5 8 2.5 C9.5 2.5 10.5 3.5 10.5 5 L10.5 7" fill="none" stroke="{c}" stroke-width="1.3" stroke-linecap="round"/>
<circle cx="8" cy="10" r="1" fill="{c2}"/>
</svg>"""

_SEARCH = """<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<circle cx="7" cy="7" r="4.5" fill="none" stroke="{c}" stroke-width="1.4"/>
<line x1="10.4" y1="10.4" x2="14" y2="14" stroke="{c}" stroke-width="1.4" stroke-linecap="round"/>
<circle cx="7" cy="7" r="1" fill="{c2}"/>
</svg>"""

def get_icon(name, status=None):
    tmpl = _THEME_ICONS.get(name) or _BUILTINS.get(name)
    if status and tmpl is not None:
        return _make_icon_with_dot(tmpl, status)
    if _icons is None:
        init_icons()
    return _icons.get(name)


_BUILTINS = {
    "host": _HOST,
    "vm": _VM,
    "cluster": _CLUSTER,
    "pool": _POOL,
    "folder": _FOLDER,
    "storage": _STORAGE,
    "backup": _BACKUP,
    "restore": _RESTORE,
    "iso": _ISO,
    "template": _TEMPLATE,
    "tpm": _TPM,
    "network": _NETWORK,
    "services": _SERVICES,
    "snapshot": _SNAPSHOT,
    "monitor": _MONITOR,
    "hardware": _HARDWARE,
    "options": _OPTIONS,
    "history": _HISTORY,
    "disk": _DISK,
    "start": _START,
    "shutdown": _SHUTDOWN,
    "reboot": _REBOOT,
    "reset": _RESET,
    "stop": _STOP,
    "console": _CONSOLE,
    "resume": _RESUME,
    "ha": _HA,
    "usb": _USB,
    "pci": _PCI,
    "serial": _SERIAL,
    "user": _USER,
    "token": _TOKEN,
    "group": _GROUP,
    "role": _ROLE,
    "acl": _ACL,
    "search": _SEARCH,
    "refresh": _REFRESH,
    "expand": _EXPAND,
    "collapse": _COLLAPSE,
    "add": _ADD,
    "remove": _REMOVE,
    "upload": _UPLOAD,
    "download": _DOWNLOAD,
    "export": _EXPORT,
    "import": _IMPORT,
    "about": _ABOUT,
    "lock": _LOCK,
    "unlock": _UNLOCK,
    "migrate": _MIGRATE,
    "clone": _CLONE,
    "app": _APP,
}


def init_icons():
    global _icons
    if _icons is not None:
        return
    _icons = {}
    for name, tmpl in _BUILTINS.items():
        svg = _THEME_ICONS.get(name) or tmpl
        _icons[name] = _make_icon(_fmt(svg), _sized(_SCALES.get(name, 1.0)))
