import os

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .theme import Color, active_theme_id

ICON_SIZE = 24
_BASE_SIZE = ICON_SIZE  # base size; the theme engine changes it via set_base_size()

# Fixed icon size for compact controls (QPushButton / QToolButton / the main
# toolbar): does NOT follow the theme's icon base (VIRTDECK_ICON_SIZE scales
# content views — tree, command palette — while all the chrome stays at 24).
CONTROL_ICON_SIZE = 24


def set_base_size(size):
    """Base icon size (the theme engine applies theme.icon_size)."""
    global _BASE_SIZE
    _BASE_SIZE = int(size)


def base_size():
    """Current base icon size (24 px in all themes)."""
    return _BASE_SIZE


def reset_icons():
    """Reset the icon cache — after a theme change (redraw with new colors)."""
    global _icons, _PACK
    _icons = None
    _PACK = _load_pack()


_THEME_ICONS: dict = {}


def set_theme_icons(overrides):
    """SVG overrides of the active theme (partial; fallback to built-ins)."""
    global _THEME_ICONS
    _THEME_ICONS = overrides or {}


# ── Bundled icon pack (v2, on by default) ──
# The pack art is self-contained (128 viewBox, baked gradients) — used as
# is, without token substitution; only the light/dark file variant follows
# the active theme. VIRTDECK_ICON_PACK=<dir> swaps in an external pack for
# trials. Names outside _PACK_MAP keep the builtin glyph (app/loading/
# restore).

# Where the external pack is loaded from when the env var is unset.
_BUNDLED_PACK_ROOT = os.path.join(os.path.dirname(__file__), "icons_pack")

_PACK_MAP = {
    # Objects / states (наши имена → id пака v2)
    "host": "host", "vm": "virtual-machine", "cluster": "cluster",
    "pool": "pool", "folder": "files", "storage": "storage",
    "backup": "backup", "iso": "iso", "template": "template",
    "network": "network", "snapshot": "snapshot", "monitor": "monitoring",
    "console": "console", "ha": "ha", "about": "about",
    "options": "settings", "history": "logs", "token": "key",
    "refresh": "refresh",
    # Actions
    "start": "start", "stop": "stop", "shutdown": "shutdown",
    "reboot": "reboot", "reset": "reset", "resume": "resume",
    "add": "add", "remove": "remove", "upload": "upload",
    "download": "download", "export": "export", "import": "import",
    "expand": "expand", "collapse": "collapse", "clone": "clone",
    "migrate": "migrate", "search": "search",
    # Devices / hardware
    "disk": "disk", "usb": "usb", "pci": "pci", "serial": "serial",
    "tpm": "tpm", "services": "services", "hardware": "hardware",
    # Access
    "user": "user", "group": "group", "role": "role", "acl": "acl",
    "lock": "lock", "unlock": "unlock",
}

_DARK_VARIANT_THEMES = ("breeze_dark", "graphite")

_PACK: dict = {}


def _load_pack():
    """Read pack files for the active theme variant (bundled by default)."""
    root = os.environ.get("VIRTDECK_ICON_PACK") or _BUNDLED_PACK_ROOT
    variant = "dark" if active_theme_id() in _DARK_VARIANT_THEMES else "light"
    out = {}
    for ours, pack_id in _PACK_MAP.items():
        try:
            with open(os.path.join(root, variant, pack_id + ".svg"),
                      encoding="utf-8") as fh:
                out[ours] = fh.read()
        except OSError:
            continue
    return out


# Relative sizes of small/large icons vs the base size.
_SCALES = {
    "app": 1.5,  # brand mark — the only exception
}


def _sized(scale):
    return max(10, round(_BASE_SIZE * scale))


def _status_color(status):
    if status in ("online", "running", "OK"):
        return Color.STATUS_OK
    elif status in ("offline", "stopped", "error"):
        return Color.STATUS_ERR
    elif status in ("paused", "warning"):
        return Color.STATUS_WARN
    return None

def _screen_dpr():
    """Device pixel ratio of the primary screen (1.0 without a app)."""
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance()
    if app is None:
        return 1.0
    screen = app.primaryScreen()
    return screen.devicePixelRatio() if screen is not None else 1.0


def _render_svg_pixmap(svg, size=None, dpr=None):
    """U36: rasterize an SVG template at size * devicePixelRatio and tag
    the bitmap — a 1x bitmap is no longer stretched blurry on HiDPI."""
    if size is None:
        size = _BASE_SIZE
    if dpr is None:
        dpr = _screen_dpr()
    px = max(1, round(size * dpr))
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(px, px)
    pixmap.fill(Qt.transparent)
    pixmap.setDevicePixelRatio(dpr)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


def _make_icon(svg, size=None, dpr=None):
    if size is None:
        size = _BASE_SIZE
    return QIcon(_render_svg_pixmap(svg, size, dpr))

# ── icon color layer (Д5/S2): one shape language for every theme;
# colors come from the ICON_* theme tokens (see _fmt) ──

_HOST = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="5" y="2.5" width="14" height="19" rx="2.5" fill="{deep}"/><path d="M8 7.5h8M8 11.5h8M8 15.5h5" fill="none" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /><circle cx="16" cy="18" r="1.3" fill="{ok}"/></svg>"""

_VM = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="3" y="3.5" width="18" height="13.5" rx="2.8" fill="{brand}"/><rect x="5.4" y="5.9" width="13.2" height="8.7" rx="1.6" fill="#FFFFFF"/><path d="M10.4 8l4.6 2.25L10.4 12.5z" fill="{deep}"/><path d="M12 17v3.5" fill="none" stroke="{brand}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" /><path d="M8 20.5h8" fill="none" stroke="{brand}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_CLUSTER = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M6.5 11v3h11v-3" fill="none" stroke="{deep}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /><path d="M12 14v3.2" fill="none" stroke="{deep}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /><rect x="3" y="3.5" width="7" height="7" rx="2" fill="{brand}"/><rect x="14" y="3.5" width="7" height="7" rx="2" fill="{brand}"/><rect x="8.5" y="13.5" width="7" height="7" rx="2" fill="{deep}"/></svg>"""

_POOL = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M3.5 6.7a2 2 0 012-2h3.9l2 2.3h9.1a2 2 0 012 2v9.5a2 2 0 01-2 2h-15a2 2 0 01-2-2z" fill="{pool}"/><path d="M3.5 9.8h17" fill="none" stroke="{pool}" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" opacity=".55"/></svg>"""

_FOLDER = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M3.5 6.7a2 2 0 012-2h3.9l2 2.3h9.1a2 2 0 012 2v9.5a2 2 0 01-2 2h-15a2 2 0 01-2-2z" fill="{brand}"/><path d="M3.5 9.8h17" fill="none" stroke="{deep}" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" opacity=".55"/><path d="M3.5 6.7v-.9" fill="none" stroke="{brand}" stroke-width="0" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_STORAGE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M5 5.5v13c0 1.55 3.13 2.8 7 2.8s7-1.25 7-2.8v-13z" fill="{deep}"/><ellipse cx="12" cy="5.5" rx="7" ry="2.8" fill="{brand}"/><path d="M5 9.3c1.35 1.05 3.95 1.7 7 1.7s5.65-.65 7-1.7" fill="none" stroke="#FFFFFF" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" opacity=".85"/></svg>"""

_BACKUP = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M5 6v8c0 1.45 2.24 2.6 5 2.6s5-1.15 5-2.6V6z" fill="{deep}"/><ellipse cx="10" cy="6" rx="5" ry="2.1" fill="{brand}"/><circle cx="17.3" cy="16.8" r="4.6" fill="{ok}"/><path d="M17.3 19.2v-4.6M15.5 16.3l1.8-1.8 1.8 1.8" fill="none" stroke="#FFFFFF" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_RESTORE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M4.6 9.8A8.2 8.2 0 117 18.4" fill="none" stroke="{brand}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" /><path d="M3.2 6.2l1.7 4.5 4.1-2.7z" fill="{brand}"/><circle cx="13" cy="13" r="6" fill="{deep}"/><path d="M13 9.8v3.4l2.4 1.5" fill="none" stroke="#FFFFFF" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_ISO = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.4" fill="{brand}"/><circle cx="12" cy="12" r="4.7" fill="none" stroke="#FFFFFF" stroke-width="1.7" opacity=".8"/><circle cx="12" cy="12" r="2.1" fill="#FFFFFF"/><circle cx="12" cy="12" r=".95" fill="{deep}"/><path d="M6.2 8.4a7 7 0 014.2-3" fill="none" stroke="#FFFFFF" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" opacity=".6"/></svg>"""

_TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="3" y="3.5" width="18" height="13.5" rx="2.8" fill="{deep}"/><rect x="5.4" y="5.9" width="13.2" height="8.7" rx="1.6" fill="#FFFFFF"/><path d="M7.6 8.6h5M7.6 11.6h3" fill="none" stroke="{soft}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" /><circle cx="18.5" cy="6.5" r="4" fill="{warn}"/><path d="M18.5 4.9v3.2M16.9 6.5h3.2" fill="none" stroke="#FFFFFF" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" /><path d="M12 17v3.5M8 20.5h8" fill="none" stroke="{deep}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_TPM = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M8 6.8V4.2M12 6.8V4.2M16 6.8V4.2M8 17.2v2.6M12 17.2v2.6M16 17.2v2.6" fill="none" stroke="{c2}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" /><rect x="5" y="6.8" width="14" height="10.4" rx="1.8" fill="{deep}"/><rect x="8.4" y="9.6" width="7.2" height="4.8" rx="1" fill="#FFFFFF"/><path d="M11 12h2" fill="none" stroke="{deep}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_NETWORK = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M2 9.6h2M2 14.4h2" fill="none" stroke="{deep}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /><rect x="4" y="5.8" width="16" height="12.4" rx="2.1" fill="{brand}"/><rect x="7.6" y="9.2" width="8.8" height="5" rx="1.1" fill="#FFFFFF"/><path d="M9.4 14.2v2.4M11.8 14.2v2.4M14.2 14.2v2.4" fill="none" stroke="#FFFFFF" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" /><path d="M9.4 11.7h5.2" fill="none" stroke="{soft}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_SERVICES = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="9" r="5.7" fill="none" stroke="{brand}" stroke-width="2.7" stroke-dasharray="2.55 2.6"/><circle cx="12" cy="9" r="4.4" fill="{brand}"/><circle cx="12" cy="9" r="1.9" fill="#FFFFFF"/><path d="M6.8 17.6h10.4M6.8 20.6h6.4" fill="none" stroke="{deep}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_SNAPSHOT = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M8.2 6.8l1.3-2.3h5l1.3 2.3z" fill="{deep}"/><rect x="3.4" y="6.8" width="17.2" height="12.8" rx="2.6" fill="{brand}"/><circle cx="12" cy="13" r="3.5" fill="#FFFFFF"/><circle cx="12" cy="13" r="1.9" fill="{deep}"/><circle cx="17.6" cy="9.6" r=".95" fill="#FFFFFF" opacity=".85"/></svg>"""

_MONITOR = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="13.4" rx="2.6" fill="{deep}"/><path d="M6.4 13.4l3-3.1 2.3 2.3 3.3-4.3 2.6 2.1" fill="none" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /><circle cx="17.2" cy="7" r="1.1" fill="{warn}"/><path d="M12 17.4v3M8 20.4h8" fill="none" stroke="{deep}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_HARDWARE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M9.6 6.4V2.8M14.4 6.4V2.8M9.6 17.6v3.6M14.4 17.6v3.6M6.4 9.6H2.8M6.4 14.4H2.8M17.6 9.6h3.6M17.6 14.4h3.6" fill="none" stroke="{deep}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /><rect x="6.4" y="6.4" width="11.2" height="11.2" rx="2.1" fill="{brand}"/><rect x="9.4" y="9.4" width="5.2" height="5.2" rx="1.1" fill="#FFFFFF"/></svg>"""

_OPTIONS = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M5 6.6h14M5 12h14M5 17.4h14" fill="none" stroke="{deep}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" /><circle cx="9.2" cy="6.6" r="2.7" fill="{ok}"/><circle cx="15.6" cy="12" r="2.7" fill="{warn}"/><circle cx="10.6" cy="17.4" r="2.7" fill="{pool}"/><circle cx="9.2" cy="6.6" r="1" fill="#FFFFFF"/><circle cx="15.6" cy="12" r="1" fill="#FFFFFF"/><circle cx="10.6" cy="17.4" r="1" fill="#FFFFFF"/></svg>"""

_HISTORY = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M4.4 9.9A8.1 8.1 0 116.6 17.8" fill="none" stroke="{brand}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" /><path d="M3 6.3l1.65 4.4 4-2.6z" fill="{brand}"/><circle cx="12.6" cy="12.4" r="5.7" fill="{deep}"/><path d="M12.6 9.4v3.2l2.3 1.4" fill="none" stroke="#FFFFFF" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_DISK = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="3.4" y="7.3" width="17.2" height="9.6" rx="2.1" fill="{deep}"/><circle cx="10.4" cy="12.1" r="3.1" fill="#FFFFFF"/><circle cx="10.4" cy="12.1" r="1.25" fill="{deep}"/><circle cx="17.5" cy="14.6" r="1.05" fill="{ok}"/></svg>"""

_START = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M8.2 5.1l9.6 6.35c.83.55.83 1.75 0 2.3L8.2 20.1c-.92.6-2.1-.06-2.1-1.17V6.27c0-1.1 1.18-1.77 2.1-1.17z" fill="{ok}"/></svg>"""

_SHUTDOWN = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M7.4 5.9a8.1 8.1 0 109.2 0" fill="none" stroke="{warn}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" /><path d="M12 3v8" fill="none" stroke="{warn}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_REBOOT = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M19.3 8.2A7.9 7.9 0 1112 4.1" fill="none" stroke="{brand}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" /><path d="M21 3.3l-.65 5.1-4.65-1.95z" fill="{brand}"/></svg>"""

_RESET = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M19.3 8.2A7.9 7.9 0 1112 4.1" fill="none" stroke="{err}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" /><path d="M21 3.3l-.65 5.1-4.65-1.95z" fill="{err}"/><path d="M17.3 15.2l.65 1.75 1.75.65-1.75.65-.65 1.75-.65-1.75-1.75-.65 1.75-.65z" fill="{warn}"/></svg>"""

_STOP = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2.6" fill="{err}"/></svg>"""

_CONSOLE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="14.5" rx="2.6" fill="{deep}"/><path d="M7 9.3l3.3 2.7L7 14.7" fill="none" stroke="#FFFFFF" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" /><path d="M12.7 14.7h4.5" fill="none" stroke="#FFFFFF" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" /><path d="M12 18.5v2.5M8 21h8" fill="none" stroke="{brand}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_RESUME = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M6.7 6.3l7.8 4.85c.9.56.9 1.86 0 2.42l-7.8 4.85c-.93.58-2.1-.08-2.1-1.2V7.5c0-1.12 1.17-1.78 2.1-1.2z" fill="{brand}"/><rect x="17.4" y="5.4" width="2.7" height="13.2" rx="1.35" fill="{deep}"/></svg>"""

_HA = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M12 2.4l7.6 3.2v5.7c0 4.6-3.1 8.5-7.6 10.3-4.5-1.8-7.6-5.7-7.6-10.3V5.6z" fill="{deep}"/><path d="M7.4 12h2.7l1.3-2.7 2.1 5.2 1.4-2.5h1.7" fill="none" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_USB = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="9.4" y="2.4" width="5.2" height="5.6" rx="1" fill="{c2}"/><path d="M10.9 4.4h1M13.1 4.4h1" fill="none" stroke="{c2}" stroke-width="1.1" stroke-linecap="round" stroke-linejoin="round" /><rect x="7.9" y="8" width="8.2" height="9.6" rx="2.1" fill="{brand}"/><circle cx="12" cy="10.8" r="1.05" fill="#FFFFFF"/><path d="M12 17.6v3" fill="none" stroke="{deep}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_PCI = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M2.6 8.6h2.2M2.6 12h2.2M2.6 15.4h2.2" fill="none" stroke="{warn}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /><rect x="4.8" y="4.4" width="14.6" height="15.2" rx="2" fill="{deep}"/><path d="M7.6 8.2h9M7.6 12h5.6M7.6 15.8h7" fill="none" stroke="#FFFFFF" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" /><rect x="15.4" y="13.6" width="2" height="4" rx="0.8" fill="{ok}"/></svg>"""

_SERIAL = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="3.8" y="6.8" width="16.4" height="10.4" rx="2.1" fill="{deep}"/><circle cx="7.2" cy="10.2" r=".85" fill="#FFFFFF"/><circle cx="9.9" cy="10.2" r=".85" fill="#FFFFFF"/><circle cx="12.6" cy="10.2" r=".85" fill="#FFFFFF"/><circle cx="15.3" cy="10.2" r=".85" fill="#FFFFFF"/><circle cx="18" cy="10.2" r=".85" fill="#FFFFFF"/><path d="M7.4 14.2h2.4M11 14.2h2.4M14.6 14.2h2.4" fill="none" stroke="#FFFFFF" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_USER = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="7.6" r="3.5" fill="{brand}"/><path d="M4.4 20.2c.6-4.1 3.4-6.2 7.6-6.2s7 2.1 7.6 6.2z" fill="{deep}"/></svg>"""

_TOKEN = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="6.8" y="3.4" width="10.4" height="17.2" rx="2.2" fill="{deep}"/><path d="M9.8 7.8h4.4M9.8 10.8h4.4" fill="none" stroke="{soft}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" /><circle cx="12" cy="15.8" r="2.7" fill="{warn}"/><path d="M12 14.9v1.9M11.1 16.8h1.8" fill="none" stroke="#FFFFFF" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_GROUP = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="6.8" cy="9" r="2.5" fill="{brand}"/><path d="M2.8 18.3c.4-2.6 1.9-4 4-4s3.6 1.4 4 4z" fill="{brand}"/><circle cx="17.2" cy="9" r="2.5" fill="{brand}"/><path d="M13.2 18.3c.4-2.6 1.9-4 4-4s3.6 1.4 4 4z" fill="{brand}"/><circle cx="12" cy="10" r="3" fill="{deep}"/><path d="M7.4 19.6c.5-3.3 2.2-5 4.6-5s4.1 1.7 4.6 5z" fill="{deep}"/></svg>"""

_ROLE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="4.4" y="3.8" width="15.2" height="16.4" rx="2.2" fill="{brand}"/><circle cx="12" cy="9.7" r="2.5" fill="#FFFFFF"/><path d="M8.3 15.8c.4-2.3 1.8-3.5 3.7-3.5s3.3 1.2 3.7 3.5z" fill="#FFFFFF"/></svg>"""

_ACL = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M12 2.4l7.6 3.2v5.7c0 4.6-3.1 8.5-7.6 10.3-4.5-1.8-7.6-5.7-7.6-10.3V5.6z" fill="{deep}"/><circle cx="12" cy="10.6" r="1.8" fill="#FFFFFF"/><path d="M12 12.2v3" fill="none" stroke="#FFFFFF" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_SEARCH = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="10.4" cy="10.4" r="6.2" fill="{soft}"/><circle cx="10.4" cy="10.4" r="6.2" fill="none" stroke="{deep}" stroke-width="2.6"/><path d="M15.3 15.3L20.4 20.4" fill="none" stroke="{deep}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_REFRESH = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M5.6 11.6a6.6 6.6 0 0111-4.4" fill="none" stroke="{brand}" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round" /><path d="M17.2 3.3l-.4 4.2-4-1.2z" fill="{brand}"/><path d="M18.4 12.4a6.6 6.6 0 01-11 4.4" fill="none" stroke="{ok}" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round" /><path d="M6.8 20.7l.4-4.2 4 1.2z" fill="{ok}"/></svg>"""

_EXPAND = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M13.7 10.3L20 4M20 4h-5M20 4v5" fill="none" stroke="{brand}" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round" /><path d="M10.3 13.7L4 20M4 20h5M4 20v-5" fill="none" stroke="{brand}" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_COLLAPSE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M20 4l-6.3 6.3M13.7 10.3h4.6M13.7 10.3V5.7" fill="none" stroke="{brand}" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round" /><path d="M4 20l6.3-6.3M10.3 13.7H5.7M10.3 13.7v4.6" fill="none" stroke="{brand}" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_ADD = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M12 4.6v14.8M4.6 12h14.8" fill="none" stroke="{ok}" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_REMOVE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M4.6 12h14.8" fill="none" stroke="{err}" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_UPLOAD = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M12 14.5V4.2" fill="none" stroke="{deep}" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round" /><path d="M8.2 8L12 4.2 15.8 8" fill="none" stroke="{deep}" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round" /><path d="M5 13.8v3.9a2.3 2.3 0 002.3 2.3h9.4a2.3 2.3 0 002.3-2.3v-3.9" fill="none" stroke="{brand}" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_DOWNLOAD = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M12 4.2v10.3" fill="none" stroke="{ok}" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round" /><path d="M8.2 10.7L12 14.5l3.8-3.8" fill="none" stroke="{ok}" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round" /><path d="M5 13.8v3.9a2.3 2.3 0 002.3 2.3h9.4a2.3 2.3 0 002.3-2.3v-3.9" fill="none" stroke="{brand}" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_EXPORT = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="4.6" y="10.4" width="14.8" height="9.6" rx="2.1" fill="{brand}"/><path d="M12 14.8V3.8" fill="none" stroke="{warn}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" /><path d="M8.7 7.1L12 3.8l3.3 3.3" fill="none" stroke="{warn}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_IMPORT = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="4.6" y="10.4" width="14.8" height="9.6" rx="2.1" fill="{brand}"/><path d="M12 3.8v11" fill="none" stroke="{warn}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" /><path d="M8.7 11.5l3.3 3.3 3.3-3.3" fill="none" stroke="{warn}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_ABOUT = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.6" fill="{brand}"/><circle cx="12" cy="7.7" r="1.35" fill="#FFFFFF"/><path d="M12 10.8v5.6" fill="none" stroke="#FFFFFF" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_LOCK = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M8 10.4V7.8a4 4 0 018 0v2.6" fill="none" stroke="{deep}" stroke-width="2.6"/><rect x="5.4" y="10.4" width="13.2" height="10" rx="2.6" fill="{brand}"/><circle cx="12" cy="14.7" r="1.75" fill="#FFFFFF"/><path d="M12 16.2v2" fill="none" stroke="#FFFFFF" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_UNLOCK = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M8 10.4V7.8a4 4 0 017.8-1.3" fill="none" stroke="{deep}" stroke-width="2.6"/><rect x="5.4" y="10.4" width="13.2" height="10" rx="2.6" fill="{brand}"/><circle cx="12" cy="14.7" r="1.75" fill="#FFFFFF"/><path d="M12 16.2v2" fill="none" stroke="#FFFFFF" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_MIGRATE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="2.8" y="6.2" width="6.9" height="9" rx="1.8" fill="{deep}"/><path d="M4.6 8.8h3.3M4.6 11.3h3.3" fill="none" stroke="#FFFFFF" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" /><rect x="14.3" y="6.2" width="6.9" height="9" rx="1.8" fill="{brand}"/><path d="M16.1 8.8h3.3M16.1 11.3h3.3" fill="none" stroke="#FFFFFF" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" /><path d="M10.3 10.7l3 0" fill="none" stroke="{ok}" stroke-width="0" stroke-linecap="round" stroke-linejoin="round" /><path d="M13.9 10.7l-3-2.1v4.2z" fill="{ok}"/></svg>"""

_CLONE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="8.6" y="3.4" width="11.4" height="11.4" rx="2.2" fill="{soft}"/><rect x="4" y="9.2" width="11.4" height="11.4" rx="2.2" fill="{brand}"/><path d="M9.7 14.9v4M7.7 16.9h4" fill="none" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" /></svg>"""

_APP = """<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<rect x="2" y="2" width="20" height="20" rx="0" fill="none" stroke="{c}" stroke-width="1.5"/>
<rect x="5" y="5" width="14" height="3" rx="0" fill="{c}"/>
<rect x="5" y="10" width="14" height="1" rx="0" fill="{c}"/>
<rect x="5" y="13" width="14" height="1" rx="0" fill="{c}"/>
<rect x="5" y="16" width="14" height="1" rx="0" fill="{c}"/>
<rect x="8" y="22" width="8" height="1" rx="0" fill="{c}"/>
<rect x="11" y="20" width="2" height="2" rx="0" fill="{c}"/>
</svg>"""

_LOADING = """<svg viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">
<circle cx="8" cy="8" r="5" fill="none" stroke="{b}" stroke-width="2"/>
<path d="M8 3 A5 5 0 0 1 13 8" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/>
</svg>"""

def _dot_geometry(tmpl):
    """Status-dot geometry from the template viewBox (16 -> r3.5 @ 12.5).

    The 128px pack grid reserves a bottom-right clearance for a 22%-diameter
    dot (center 110,110; r14 + stroke ≈ 17) — see the pack validation.json.
    """
    import re as _re

    m = _re.search(r'viewBox="0 0 (\d+)[\d. ]*"', tmpl)
    vb = float(m.group(1)) if m else 16.0
    if vb == 128.0:  # pack grid: dot fits the reserved bottom-right zone
        return 110.0, 14.0
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

_icons = None

def _fmt(tmpl):
    """Format the template with tokens; a foreign SVG without placeholders — as-is."""
    try:
        return tmpl.format(
            c=Color.ICON_FG, c2=Color.ICON_FG_DIM,
            brand=Color.ICON_BRAND, deep=Color.ICON_BRAND_DEEP,
            soft=Color.ICON_BRAND_SOFT, pool=Color.ICON_POOL,
            ok=Color.ICON_OK, err=Color.ICON_ERR, warn=Color.ICON_WARN,
            b=Color.BORDER)
    except (KeyError, IndexError):
        return tmpl

def get_icon(name, status=None):
    if _icons is None:
        init_icons()
    tmpl = _PACK.get(name) or _THEME_ICONS.get(name) or _BUILTINS.get(name)
    if status and tmpl is not None:
        return _make_icon_with_dot(tmpl, status)
    return _icons.get(name)


def get_pixmap(name, size):
    """Rasterize a named icon at an explicit pixel size, bypassing the
    base-size icon cache (oversized chrome: EmptyState's 3x illustration
    keeps its fixed size whatever the icon base is)."""
    if _icons is None:
        init_icons()
    tmpl = _PACK.get(name) or _THEME_ICONS.get(name) or _BUILTINS.get(name)
    if tmpl is None:
        return QPixmap()
    return _render_svg_pixmap(tmpl, size)

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
    global _icons, _PACK
    if _icons is not None:
        return
    if not _PACK:
        _PACK = _load_pack()
    _icons = {}
    for name, tmpl in _BUILTINS.items():
        if name in _PACK:
            svg = _PACK[name]  # self-contained art, tokens not applied
        else:
            svg = _fmt(_THEME_ICONS.get(name) or tmpl)
        _icons[name] = _make_icon(svg, _sized(_SCALES.get(name, 1.0)))
