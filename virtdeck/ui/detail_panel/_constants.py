import weakref
from enum import IntEnum
from importlib.util import find_spec

from ..theme import Color

_HEADER_STYLE = (f"QHeaderView::section {{ padding: 6px 8px; border: none;"
                 f" border-bottom: 1px solid {Color.BORDER_LIGHT}; }}")

_MAX_WORKERS_DP = 12

_HAS_PG = find_spec("pyqtgraph") is not None
_pg_module = None

_LIVE_PLOTS: weakref.WeakSet | None = None


def pg_loaded():
    """Return pyqtgraph if already imported, else None (never imports)."""
    return _pg_module


def apply_chart_colors(pg_mod):
    """Re-apply the color theme to charts (load + every theme change)."""
    pg_mod.setConfigOption('background', Color.BG)
    pg_mod.setConfigOption('foreground', Color.TEXT_SEC)


def register_plot(widget):
    """Register a live PlotWidget for recoloring on theme change."""
    global _LIVE_PLOTS
    if _LIVE_PLOTS is None:
        _LIVE_PLOTS = weakref.WeakSet()
    _LIVE_PLOTS.add(widget)


def retheme_plots():
    """Live recoloring of already built charts to the active theme.

    Curves are tagged with a `_vd_token` attribute (a Color token name)
    where they are created; background, axes, title and pens are
    recolored here.
    """
    pg_mod = pg_loaded()
    if pg_mod is None:
        return
    apply_chart_colors(pg_mod)
    if _LIVE_PLOTS is None:
        return
    for w in list(_LIVE_PLOTS):
        try:
            w.setBackground(Color.BG)
            for ax in ("left", "bottom"):
                a = w.getAxis(ax)
                a.setPen(pg_mod.mkPen(Color.TEXT_SEC))
                a.setTextPen(Color.TEXT_SEC)
            title = getattr(w.plotItem.titleLabel, "text", "")
            if title:
                w.setTitle(title)
            for di in w.plotItem.listDataItems():
                token = getattr(di, "_vd_token", None)
                if token:
                    color = getattr(Color, token)
                    di.setPen(pg_mod.mkPen(color, width=2))
                    di.setFillBrush(pg_mod.mkBrush(color + "33"))
        except (RuntimeError, AttributeError):
            _LIVE_PLOTS.discard(w)  # C++ object already destroyed or torn down


def ensure_pg():
    """Import pyqtgraph on first use and apply chart styling.

    Keeps the 0.6s pyqtgraph import out of the startup path: charts are
    only needed once the Monitoring tabs are actually built.
    """
    global _pg_module
    if _pg_module is None and _HAS_PG:
        import pyqtgraph as pg
        apply_chart_colors(pg)
        _pg_module = pg
    return _pg_module


class TabIndex(IntEnum):
    MONITOR = 0
    HARDWARE = 1
    OPTIONS = 2
    HISTORY = 3
    SUMMARY = 4
    HOST_VMS = 5
    POOL_VMS = 6
    STORAGES = 7
    HOST_STORAGE = 8
    STORAGE_DETAIL = 9
    STORAGE_MONITORING = 10
    BACKUPS = 11
    DISKS_VM = 12
    ISO = 13
    TEMPLATES = 14
    NETWORK = 15
    SERVICES = 16
    HOST_DISKS = 17
    SNAPSHOTS = 18
    HEALTH = 19
    VM_SNAPSHOTS = 20
    VM_BACKUP = 21
    BACKUP_JOBS = 22
    ACCESS = 23
    HA = 24


def _fmt_pveversion(val):
    val = str(val)
    return val.split("/")[1] if "/" in val else val


def _progress_style(value, max_val=100):
    pct = int((value / max_val) * 100) if max_val else 0
    if pct < 0:
        pct = 0
    elif pct > 100:
        pct = 100
    if pct < 50:
        color = Color.STATUS_OK
    elif pct < 80:
        color = Color.STATUS_WARN
    else:
        color = Color.STATUS_ERR
    return (
        f"QProgressBar::chunk {{ background: {color}; border-radius: 3px; }}"
        f"QProgressBar {{ border: none; border-radius: 3px;"
        f" text-align: center; font-size: 11px; background: {Color.TRACK}; }}"
    )
