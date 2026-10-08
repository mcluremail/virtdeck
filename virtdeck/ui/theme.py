"""
VirtDeck UI theme.
Light. Fonts are resolved from those available on the system (Noto Sans /
Terminus preferred; Windows/macOS get system substitutes).
"""

import logging
import os
import re

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QHeaderView, QProxyStyle, QStyle

logger = logging.getLogger(__name__)


_ICON_METRICS = (
    QStyle.PM_SmallIconSize, QStyle.PM_ListViewIconSize,
    QStyle.PM_IconViewIconSize, QStyle.PM_TabBarIconSize,
)
_BASE_SIZE_FN = None  # cache of icons.base_size: a local import per call is costly


class BaseIconStyle(QProxyStyle):
    """Style whose icon metrics follow the theme's base icon size.

    Without it, widgets that don't call setIconSize explicitly (tabs,
    buttons, detail panel tables, etc.) draw icons at the Qt default
    (PM_SmallIconSize = 16) instead of base_size(). The size is read live
    from icons.base_size(), so theme switches are picked up automatically.
    """

    def pixelMetric(self, metric, option=None, widget=None):
        # Hot path: setStyleSheet restyles thousands of widgets, each one
        # asking for metrics via this Python override — the body must stay
        # minimal (no imports, no class attribute lookups).
        if metric in _ICON_METRICS:
            global _BASE_SIZE_FN
            fn = _BASE_SIZE_FN
            if fn is None:
                from .icons import base_size
                _BASE_SIZE_FN = fn = base_size
            return fn()
        return super().pixelMetric(metric, option, widget)


_BASE_ICON_STYLE: BaseIconStyle | None = None


def install_base_icon_style() -> None:
    """Install BaseIconStyle once for the whole app (idempotent).

    Called from main() right after QApplication is created (load_theme
    does not run at startup for the light theme — otherwise the style
    wouldn't stick) and again from load_theme() as a safety net. The
    reference is kept global: without it GC collects the style's Python
    wrapper and Shiboken restores it as a plain QCommonStyle (the type
    and its virtual pixelMetric lose their Python identity).
    """
    global _BASE_ICON_STYLE
    app = QApplication.instance()
    if app is None or _BASE_ICON_STYLE is not None:
        return
    _BASE_ICON_STYLE = BaseIconStyle(app.style())
    app.setStyle(_BASE_ICON_STYLE)


def _app() -> QApplication:
    """Return the current QApplication instance."""
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("theme.load(): QApplication not created yet")
    return app


# ── Color tokens ───────────────────────────────────────────────────
# Canonical semantic set (ThemePlugin v1 contract, see docs/THEMES.md).
# Color is a facade: the theme engine swaps values via setattr on theme
# activation. Direct references to the tokens across the UI remain valid
# and switch on the fly.

class Color:
    """Active theme — color tokens (light by default)."""

    # Backgrounds
    BG          = "#fafafa"   # window
    PANEL       = "#ffffff"   # panels/cards/controls
    RAISED      = "#f4f5f7"   # raised hover background
    TRACK       = "#f3f4f6"   # sunken background: progress track, segments
    ALT_ROW     = "#f8f9fb"   # table row alternation

    # Borders
    BORDER          = "#e5e7eb"
    BORDER_LIGHT    = "#f0f1f4"
    BORDER_STRONG   = "#cbd5e1"   # emphasized control border

    # Text
    TEXT        = "#181c26"
    TEXT_SEC    = "#5f6774"
    TEXT_DIM    = "#868a8f"
    DISABLED    = "#868a8f"
    ON_ACCENT   = "#ffffff"   # text/stroke on saturated color

    # Accent
    ACCENT          = "#0a6ed1"
    ACCENT_HOVER    = "#005bbf"
    ACCENT_LIGHT    = "#e8f0fe"
    ACCENT_PRESSED  = "#c6dafc"   # pressed control (spin arrows)

    # Status
    SUCCESS     = "#15803d"  # contrast >=4.5 on light backgrounds
    SUCCESS_LIGHT = "#bbf7d0"  # light green on dark surfaces (toast)
    WARNING     = "#92600a"  # contrast >=4.5 on light backgrounds
    WARNING_TEXT = "#92600a"  # dark amber hint text (contrast >=4.5)
    DANGER      = "#b91c1c"   # error accent in text/borders (contrast >=4.5)
    DANGER_SOLID         = "#c0392b"   # saturated red: solid text, button
    DANGER_SOLID_HOVER   = "#e74c3c"
    DANGER_SOLID_PRESSED = "#a93226"

    STATUS_OK    = "#15803d"   # status indicators/text (contrast >=4.5)
    STATUS_WARN  = "#92600a"
    STATUS_ERR   = "#b91c1c"

    # Rows and surfaces
    HOVER       = "#e8edf4"   # row/cell highlight
    ROW_WARN    = "#fff3cd"   # warning row background
    TOAST_BG    = "#1f2937"   # dark toast backdrop

    # Scrollbar
    SCROLLBAR_BG     = "#eef1f5"
    SCROLLBAR_HANDLE = "#c0c6d0"
    SCROLLBAR_HOVER  = "#a4abb8"

    # Icons
    ICON_FG     = "#4b5563"   # primary SVG icon stroke
    ICON_FG_DIM = "#374151"   # secondary stroke

    # Fonts — resolved from the fonts installed on the system (see
    # _resolve_fonts below).
    UI_FONT   = "Noto Sans"
    MONO_FONT = "Noto Sans Mono"


# ── Font resolution by system availability ────────────────────────
# Priority candidates: the first one found via QFontDatabase.hasFamily
# becomes the font name used in QSS and app.setFont. On Windows/macOS
# the Noto families are usually missing and a system substitute is picked.
_UI_CANDIDATES = (
    "Noto Sans", "Cantarell", "Segoe UI", "SF Pro Text", "Helvetica",
)
_MONO_CANDIDATES = (
    "Terminus", "Noto Sans Mono", "Cascadia Code", "Consolas",
    "Menlo", "DejaVu Sans Mono", "Liberation Mono",
)


def enable_column_reorder(header):
    """Allow dragging columns by their header.

    In Qt6 the QHeaderView of a QTableWidget is created with
    sectionsMovable=False, so without this explicit enablement the user
    cannot move columns. Returns the header for call chaining.
    """
    header.setSectionsMovable(True)
    return header


class _AutofitGuard(QObject):
    """Stops autofit for a column once the user drags its header."""

    def __init__(self, header, state):
        super().__init__(header)
        self._header = header
        self._state = state

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            col = self._header.logicalIndexAt(event.position().toPoint())
            if 0 <= col < self._header.count():
                self._state["cols"].discard(col)
        return False


def enable_table_autofit(view, cols, max_width=None):
    """Manual column resize with content-based width autofit.

    In ResizeToContents/Fixed/Stretch modes Qt does not allow changing
    column width with the mouse, so columns from cols are switched to
    Interactive, and their width is auto-fitted to content (debounced)
    until the user drags that column's header themselves.
    max_width caps the autofit (so one long column doesn't eat up the
    whole table).
    """
    header = (view.horizontalHeader() if hasattr(view, "horizontalHeader")
              else view.header())
    state = {"cols": set(cols)}
    view.setProperty("_pve_autofit_cols", state["cols"])
    for col in cols:
        header.setSectionResizeMode(col, QHeaderView.Interactive)
    timer = QTimer(view)
    timer.setSingleShot(True)
    timer.setInterval(60)

    def _fit():
        for col in list(state["cols"]):
            view.resizeColumnToContents(col)
            if max_width is not None and view.columnWidth(col) > max_width:
                view.setColumnWidth(col, max_width)

    timer.timeout.connect(_fit)
    model = view.model()
    if model is not None:
        model.dataChanged.connect(timer.start)
        model.rowsInserted.connect(timer.start)
        model.modelReset.connect(timer.start)
    guard = _AutofitGuard(header, state)
    header.viewport().installEventFilter(guard)
    return header


def _pick_font(candidates):
    """Return the first font name available on the system, else the last candidate."""
    db = QFontDatabase
    for name in candidates:
        try:
            if db.hasFamily(name):
                return name
        except Exception:
            pass
    return candidates[-1]


def _resolve_fonts():
    """Resolve UI/MONO fonts once at load(). Logs the chosen names."""
    Color.UI_FONT = _pick_font(_UI_CANDIDATES)
    Color.MONO_FONT = _pick_font(_MONO_CANDIDATES)
    logger.info("theme fonts: ui=%s, mono=%s", Color.UI_FONT, Color.MONO_FONT)


# ── Checkbox SVG indicator paths ──
_CHECK_DIR = os.path.dirname(os.path.abspath(__file__))
_CHECK_ON  = _CHECK_DIR + "/checkbox-checked.svg"
_CHECK_OFF = _CHECK_DIR + "/checkbox-unchecked.svg"

# ── QSS ────────────────────────────────────────────────────────────
# QSS is assembled by _build_qss() in load(), after _resolve_fonts()
# substitutes the available font names into Color.UI_FONT /
# Color.MONO_FONT. Until load() runs, QSS is an empty string —
# app.setStyleSheet(QSS) must not be used directly.

QSS = ""


def _build_qss() -> str:
    ui = Color.UI_FONT
    mono = Color.MONO_FONT
    return f"""
    * {{
        font-family: "{ui}", "Cantarell", "sans-serif";
        font-size: 14px;
        color: {Color.TEXT};
    }}

    /* ── Base background: without this rule, "bare" QWidget containers
       (central panel, tasks header) glow with the system palette
       in dark themes ── */
    QWidget {{
        background: {Color.BG};
    }}

    /* ── Text widgets on cards/panels: their background must match the
       container's background, not the window-wide one ── */
    QLabel, QCheckBox, QRadioButton, QGroupBox {{
        background: transparent;
    }}

    /* ── Header bar ── */
    QToolBar {{
        background: {Color.PANEL};
        border: none;
        border-bottom: 1px solid {Color.BORDER_LIGHT};
        spacing: 4px;
        padding: 4px 12px;
    }}
    QToolBar::separator {{
        width: 1px;
        background: {Color.BORDER_LIGHT};
        margin: 4px 4px;
    }}
    QToolButton {{
        border: none;
        border-radius: 6px;
        padding: 4px 8px;
        background: transparent;
        color: {Color.TEXT_SEC};
        font-size: 13px;
    }}
    QToolButton:hover {{
        background: {Color.RAISED};
        color: {Color.TEXT};
    }}
    QToolButton:pressed {{
        background: {Color.ALT_ROW};
    }}
    QToolButton:checked {{
        background: {Color.ACCENT_LIGHT};
        color: {Color.ACCENT};
    }}

    /* ── Navigation tree ── */
    QTreeWidget {{
        font-size: 13px;
        alternate-background-color: transparent;
        border: none;
        outline: none;
        background: {Color.PANEL};
    }}
    QTreeWidget::item {{
        padding: 1px 4px;
        min-height: 20px;
        border-left: 2px solid transparent;
    }}
    QTreeWidget::item:hover {{
        background: {Color.RAISED};
    }}
    QTreeWidget::item:selected {{
        background: {Color.ACCENT_LIGHT};
        color: {Color.ACCENT};
        border-left-color: {Color.ACCENT};
        font-weight: 500;
    }}
    QTreeView::branch {{
        background: transparent;
    }}

    /* ── Data tables ── */
    QTableWidget {{
        font-family: "{ui}", "Cantarell", "sans-serif";
        font-size: 13px;
        background: {Color.PANEL};
        alternate-background-color: {Color.ALT_ROW};
        gridline-color: {Color.BORDER_LIGHT};
        border: 1px solid {Color.BORDER};
        border-radius: 8px;
    }}
    QTableWidget::item {{
        padding: 4px 8px;
    }}
    QTableWidget::item:hover {{
        background: {Color.RAISED};
    }}
    QTableWidget::item:selected {{
        background: {Color.ACCENT_LIGHT};
        color: {Color.TEXT};
    }}

    QHeaderView::section {{
        font-family: "{ui}", "Cantarell", "sans-serif";
        font-weight: 600;
        padding: 6px 8px;
        background-color: transparent;
        border: none;
        border-bottom: 1px solid {Color.BORDER_LIGHT};
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: {Color.TEXT_DIM};
    }}
    QHeaderView::section:hover {{
        color: {Color.TEXT_SEC};
    }}
    QTableCornerButton::section {{
        background: transparent;
        border: none;
        border-bottom: 1px solid {Color.BORDER_LIGHT};
    }}

    /* ── Tabs (segmented control) ── */
    QTabWidget::pane {{
        border: none;
        border-top: 1px solid {Color.BORDER};
        background: {Color.BG};
        padding: 20px 24px;
    }}
    QTabBar {{
        margin-left: 0;
        background: transparent;
    }}
    QTabBar::tab {{
        padding: 10px 16px;
        font-size: 13px;
        color: {Color.TEXT_SEC};
        border: none;
        border-bottom: 2px solid transparent;
        margin-right: 0;
        font-weight: 500;
    }}
    QTabBar::tab:hover {{
        color: {Color.TEXT};
    }}
    QTabBar::tab:selected {{
        color: {Color.ACCENT};
        font-weight: 600;
        border-bottom: 2px solid {Color.ACCENT};
    }}

    /* ── Progress bar ── */
    QProgressBar {{
        border: none;
        border-radius: 3px;
        text-align: center;
        height: 6px;
        background: {Color.TRACK};
        font-size: 11px;
        color: transparent;
    }}
    QProgressBar::chunk {{
        background-color: {Color.ACCENT};
        border-radius: 3px;
    }}

    /* ── Buttons ── */
    QPushButton {{
        padding: 7px 14px;
        font-size: 13px;
        border: 1px solid {Color.BORDER};
        border-radius: 6px;
        background: {Color.PANEL};
        color: {Color.TEXT};
        font-weight: 500;
    }}
    QPushButton:hover {{
        background: {Color.RAISED};
        border-color: {Color.TEXT_DIM};
    }}
    QPushButton:pressed {{
        background: {Color.ALT_ROW};
    }}
    QPushButton:disabled {{
        color: {Color.DISABLED};
        background: {Color.ALT_ROW};
        border-color: {Color.BORDER_LIGHT};
    }}

    /* ── Dialogs ── */
    QDialog {{
        background: {Color.PANEL};
    }}

    /* Refresh button */
    QPushButton#refreshBtn {{
        background: transparent;
        border: none;
        padding: 2px;
        min-width: 20px;
        max-width: 20px;
        min-height: 20px;
        max-height: 20px;
    }}
    QPushButton#refreshBtn:hover {{
        background: {Color.HOVER};
        border-radius: 3px;
    }}
    QPushButton#refreshBtn:pressed {{
        background: {Color.ALT_ROW};
        border-radius: 3px;
    }}

    /* Accent buttons (Create VM) */
    QPushButton#accentBtn {{
        background: {Color.ACCENT};
        color: {Color.ON_ACCENT};
        border: 1px solid {Color.ACCENT};
        font-weight: 600;
    }}
    QPushButton#accentBtn:hover {{
        background: {Color.ACCENT_HOVER};
    }}
    QPushButton#accentBtn:pressed {{
        background: {Color.ACCENT_HOVER};
    }}
    QPushButton#accentBtn:disabled {{
        background: {Color.DISABLED};
        border-color: {Color.BORDER};
        color: {Color.ON_ACCENT};
    }}
    QToolButton#neutralBtn {{
        background: {Color.PANEL};
        color: {Color.TEXT};
        border: 1px solid {Color.BORDER};
        border-radius: 6px;
        padding: 5px 12px;
        font-weight: 500;
    }}
    QToolButton#neutralBtn:hover {{
        background: {Color.HOVER};
    }}
    QToolButton#neutralBtn:pressed {{
        background: {Color.ALT_ROW};
    }}
    QToolButton#neutralBtn::menu-button {{
        border: none;
        width: 16px;
        background: transparent;
    }}
    QToolButton#neutralBtn:disabled {{
        background: {Color.DISABLED};
        border-color: {Color.BORDER};
        color: {Color.ON_ACCENT};
    }}

    /* ── Segmented buttons (Clusters/Nodes toggle) ── */
    QPushButton#segBtnLeft, QPushButton#segBtnRight {{
        font-size: 12px;
        padding: 5px 14px;
        color: {Color.TEXT_SEC};
        background: {Color.TRACK};
    }}
    QPushButton#segBtnLeft {{
        border: 1px solid {Color.BORDER_STRONG};
        border-right: none;
        border-top-left-radius: 4px;
        border-bottom-left-radius: 4px;
    }}
    QPushButton#segBtnRight {{
        border: 1px solid {Color.BORDER_STRONG};
        border-top-right-radius: 4px;
        border-bottom-right-radius: 4px;
    }}
    QPushButton#segBtnLeft:checked, QPushButton#segBtnRight:checked {{
        background: {Color.ACCENT};
        color: {Color.ON_ACCENT};
        border-color: {Color.ACCENT};
    }}

    /* Danger buttons (Delete) */
    QPushButton#dangerBtn {{
        background: {Color.DANGER_SOLID};
        color: {Color.ON_ACCENT};
        border: 1px solid {Color.DANGER_SOLID};
        font-weight: 600;
    }}
    QPushButton#dangerBtn:hover {{
        background: {Color.DANGER_SOLID_HOVER};
    }}
    QPushButton#dangerBtn:pressed {{
        background: {Color.DANGER_SOLID_PRESSED};
    }}
    QPushButton#dangerBtn:disabled {{
        background: {Color.DISABLED};
        border-color: {Color.BORDER};
        color: {Color.ON_ACCENT};
    }}

    /* ── Splitter ── */
    QSplitter::handle {{
        width: 6px;
        background: {Color.BORDER};
        margin: 0 1px;
    }}
    QSplitter::handle:hover {{
        background: {Color.SCROLLBAR_HOVER};
    }}

    /* ── Menus ── */
    QMenu {{
        border: 1px solid {Color.BORDER};
        background: {Color.PANEL};
    }}
    QMenu::item {{
        padding: 4px 24px 4px 12px;
    }}
    QMenu::item:selected {{
        background: {Color.ACCENT_LIGHT};
        color: {Color.ACCENT};
    }}
    QMenu::separator {{
        height: 1px;
        background: {Color.BORDER};
        margin: 4px 8px;
    }}

    /* ── Tooltip ── */
    QToolTip {{
        background: {Color.TEXT};
        color: {Color.PANEL};
        border: none;
        padding: 4px 8px;
        font-size: 13px;
    }}

    /* ── Line Edit ── */
    QLineEdit {{
        border: 1px solid {Color.BORDER};
        border-radius: 6px;
        padding: 6px 10px;
        font-size: 13px;
        background: {Color.PANEL};
        min-height: 20px;
    }}
    QLineEdit:focus {{
        border-color: {Color.ACCENT};
    }}

    /* ── ComboBox ── */
    QComboBox {{
        border: 1px solid {Color.BORDER};
        border-radius: 4px;
        padding: 3px 6px;
        font-size: 13px;
        background: {Color.PANEL};
    }}
    QComboBox:focus {{
        border-color: {Color.ACCENT};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    QComboBox::down-arrow {{
        image: url({_CHECK_DIR}/arrow-down.svg);
        width: 10px;
        height: 8px;
    }}

    /* ── Scrollbar (thin, rounded) ── */
    QScrollBar:vertical {{
        width: 10px;
        background: {Color.SCROLLBAR_BG};
        border-radius: 5px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {Color.SCROLLBAR_HANDLE};
        border-radius: 5px;
        min-height: 30px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {Color.SCROLLBAR_HOVER};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
    }}

    QScrollBar:horizontal {{
        height: 10px;
        background: {Color.SCROLLBAR_BG};
        border-radius: 5px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background: {Color.SCROLLBAR_HANDLE};
        border-radius: 5px;
        min-width: 30px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {Color.SCROLLBAR_HOVER};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: none;
    }}

    /* ── Checkboxes ── */
    QCheckBox {{
        font-size: 13px;
        spacing: 6px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border: 1px solid {Color.BORDER};
        border-radius: 3px;
        background: {Color.PANEL};
    }}
    QCheckBox::indicator:hover {{
        border-color: {Color.ACCENT};
    }}
    QCheckBox::indicator:checked {{
        image: url({_CHECK_ON});
    }}
    QCheckBox::indicator:unchecked {{
        image: url({_CHECK_OFF});
    }}
    QCheckBox::indicator:indeterminate {{
        image: url({_CHECK_OFF});
    }}

    /* ── SpinBox ── */
    QSpinBox {{
        border: 1px solid {Color.BORDER};
        border-radius: 4px;
        padding: 3px 6px;
        font-size: 13px;
        background: {Color.PANEL};
        min-height: 22px;
        min-width: 100px;
    }}
    QSpinBox:focus {{
        border-color: {Color.ACCENT};
    }}
    QSpinBox::up-button, QSpinBox::down-button {{
        subcontrol-origin: border;
        width: 22px;
        border: none;
        background: transparent;
    }}
    QSpinBox::up-button {{
        subcontrol-position: top right;
        border-top-right-radius: 3px;
    }}
    QSpinBox::down-button {{
        subcontrol-position: bottom right;
        border-bottom-right-radius: 3px;
    }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
        background: {Color.ACCENT_LIGHT};
    }}
    QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {{
        background: {Color.ACCENT_PRESSED};
    }}
    QSpinBox::up-arrow {{
        image: url({_CHECK_DIR}/arrow-up.svg);
        width: 10px;
        height: 8px;
    }}
    QSpinBox::down-arrow {{
        image: url({_CHECK_DIR}/arrow-down.svg);
        width: 10px;
        height: 8px;
    }}

    /* ── Section headers in dialogs ── */
    QLabel#sectionTitle {{
        font-size: 14px;
        font-weight: 700;
        color: {Color.TEXT};
        letter-spacing: 0.3px;
    }}

    /* ── Form field labels ── */
    QLabel#fieldLabel {{
        color: {Color.TEXT_SEC};
        font-size: 13px;
    }}

    /* ── Section separator ── */
    QFrame#sectionSep {{
        color: {Color.BORDER};
        margin: 4px 0;
    }}

    /* ── "More" toggle button (collapsible) ── */
    QToolButton#extraToggle {{
        border: none;
        background: transparent;
        font-size: 13px;
        font-weight: 600;
        color: {Color.ACCENT};
        padding: 4px 0;
    }}
    QToolButton#extraToggle:hover {{
        color: {Color.ACCENT_HOVER};
    }}

    /* ── ScrollArea (no border) ── */
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QPlainTextEdit {{
        font-family: "{mono}", "Noto Sans Mono", monospace;
        font-size: 13px;
        background: {Color.PANEL};
        border: 1px solid {Color.BORDER};
        border-radius: 6px;
    }}

    /* ── Title block (object heading) ── */
    QLabel#titleMain {{
        font-size: 22px;
        font-weight: 600;
        letter-spacing: -0.02em;
        color: {Color.TEXT};
    }}
    QLabel#titleSub {{
        font-size: 13px;
        color: {Color.TEXT_SEC};
    }}

    /* ── Metric cards ── */
    QFrame#metricCard {{
        background: {Color.PANEL};
        border: 1px solid {Color.BORDER};
        border-radius: 10px;
    }}

    /* ── Card list ── */
    QFrame#cardList {{
        background: {Color.PANEL};
        border: 1px solid {Color.BORDER};
        border-radius: 10px;
    }}
    QFrame#cardRow {{
        border: none;
        border-bottom: 1px solid {Color.BORDER_LIGHT};
    }}
    QFrame#cardRow:last {{
        border-bottom: none;
    }}
    QFrame#cardRow:hover {{
        background: {Color.RAISED};
    }}

    /* ── Key-value sections (Hardware/Options) ── */
    QLabel#kvSectionHead {{
        font-size: 12px;
        font-weight: 600;
        color: {Color.TEXT_DIM};
        letter-spacing: 0.05em;
    }}
    QFrame#kvSeparator {{
        background: {Color.BORDER_LIGHT};
        max-height: 1px;
    }}

    /* ── Status bar ── */
    QStatusBar {{
        background: {Color.PANEL};
        border-top: 1px solid {Color.BORDER_LIGHT};
        font-size: 12px;
        color: {Color.TEXT_SEC};
    }}
"""


# ── Theme engine (ThemePlugin v1) ──────────────────────────────────
# The core only knows the canonical tokens; themes are plugins via
# plugins.ThemePlugin. QSS is built from the active theme's tokens,
# Color is a live facade (values are swapped via setattr).

TOKENS = (
    # Backgrounds
    "BG", "PANEL", "RAISED", "TRACK", "ALT_ROW",
    # Borders
    "BORDER", "BORDER_LIGHT", "BORDER_STRONG",
    # Text
    "TEXT", "TEXT_SEC", "TEXT_DIM", "DISABLED", "ON_ACCENT",
    # Accent
    "ACCENT", "ACCENT_HOVER", "ACCENT_LIGHT", "ACCENT_PRESSED",
    # Status
    "SUCCESS", "SUCCESS_LIGHT", "WARNING", "WARNING_TEXT",
    "DANGER", "DANGER_SOLID", "DANGER_SOLID_HOVER", "DANGER_SOLID_PRESSED",
    "STATUS_OK", "STATUS_WARN", "STATUS_ERR",
    # Rows and surfaces
    "HOVER", "ROW_WARN", "TOAST_BG",
    # Scrollbar
    "SCROLLBAR_BG", "SCROLLBAR_HANDLE", "SCROLLBAR_HOVER",
    # Icons
    "ICON_FG", "ICON_FG_DIM",
)

FONT_TOKENS = ("UI_FONT", "MONO_FONT")   # not part of the themes v1 contract

# Legacy names (scales) → canonical tokens. Accepted only as input from
# third-party themes; not used in the core or the built-in themes.
ALIASES = {
    "GRAY_400": "TEXT_DIM", "GRAY_500": "TEXT_SEC",
    "GRAY_200": "BORDER", "GRAY_100": "TRACK",
    "SLATE_100": "TRACK", "SLATE_200": "HOVER", "SLATE_300": "BORDER_STRONG",
    "SLATE_400": "BORDER_STRONG", "SLATE_500": "TEXT_SEC",
    "SLATE_700": "TEXT", "SLATE_800": "TOAST_BG", "SLATE_900": "ICON_FG_DIM",
    "D1_D5_DB": "BORDER_STRONG", "ERROR_RED": "DANGER_SOLID",
    "ACCENT_GREEN": "SUCCESS", "OK_ROW_BG": "SUCCESS_LIGHT",
    "WARN_BG": "ROW_WARN", "WARN_ROW_BG": "ROW_WARN", "WARN_BORDER": "WARNING",
    "SELECTED": "HOVER",
}

# Snapshot of the light palette taken at module import — before any
# facade swaps.
LIGHT_TOKENS = {name: getattr(Color, name) for name in TOKENS}

_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\Z")

_theme_listeners: list = []
_EXTRA_QSS = ""


def subscribe_theme_changed(fn):
    """Callback fn(theme_id) after a theme is applied (UI repaint)."""
    _theme_listeners.append(fn)


def unsubscribe_theme_changed(fn):
    """Unsubscribe (closed windows must unsubscribe)."""
    while fn in _theme_listeners:
        _theme_listeners.remove(fn)


def validate_tokens(tokens) -> dict:
    """Validate a theme token set: aliases → canonical, full coverage, hex."""
    from ..plugins import PluginError

    if not isinstance(tokens, dict):
        raise PluginError("theme tokens() must return a dict")
    mapped: dict[str, str] = {}
    for key, value in tokens.items():
        name = ALIASES.get(key, key)
        if name not in TOKENS:
            raise PluginError(f"unknown theme token: {key!r}")
        if not isinstance(value, str) or not _HEX_RE.fullmatch(value):
            raise PluginError(f"token {name}: invalid color {value!r}")
        mapped[name] = value
    missing = [t for t in TOKENS if t not in mapped]
    if missing:
        raise PluginError(f"theme is missing tokens: {', '.join(missing)}")
    return mapped


def apply_tokens(tokens: dict) -> None:
    """Swap the Color facade values to the theme's tokens."""
    for name, value in tokens.items():
        setattr(Color, name, value)


def _apply_qss() -> None:
    global QSS
    QSS = _build_qss() + _EXTRA_QSS
    _app().setStyleSheet(QSS)


_ACTIVE_THEME_ID = "light"


def active_theme_id() -> str:
    """id of the last activated theme ('system' for the system theme)."""
    return _ACTIVE_THEME_ID


_THEME_ORDER = ("light", "breeze", "breeze_dark", "oxygen", "graphite", "system")


def ordered_theme_ids(registry) -> list[str]:
    """Theme ids in UX order; third-party ones sorted alphabetically last."""
    ids = set(registry.theme_ids())
    known = [t for t in _THEME_ORDER if t in ids]
    return known + sorted(t for t in ids if t not in _THEME_ORDER)


def _qt_scheme_name() -> str:
    """OS color scheme: 'dark' | 'light' (error/unknown → light)."""
    try:
        from PySide6.QtGui import QGuiApplication

        scheme = QGuiApplication.styleHints().colorScheme()
        name = getattr(scheme, "name", None) or str(scheme)
        if "Dark" in name:
            return "dark"
    except Exception:
        pass
    return "light"


_scheme_listener_installed = False


def _on_scheme_changed(_scheme) -> None:
    if _ACTIVE_THEME_ID == "system":
        load_theme("system", persist=False)


def _install_scheme_listener() -> None:
    global _scheme_listener_installed
    if _scheme_listener_installed:
        return
    try:
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.styleHints().colorSchemeChanged.connect(
            _on_scheme_changed)
        _scheme_listener_installed = True
    except Exception:
        logger.debug("colorScheme listener unavailable", exc_info=True)


def load_theme(theme_id: str, registry=None, persist: bool = True) -> str:
    """Activate a theme plugin: tokens → QSS → icons → plots.

    Returns the actual theme id. Python-level QColor caches (cell brushes)
    refresh on the next widget rebuild — subscribe_theme_changed()
    listeners are responsible for repainting.
    """
    global _ACTIVE_THEME_ID, _EXTRA_QSS

    from ..config import save_ui_state
    from ..plugins import _themes as _builtin_themes
    from ..plugins import get_registry
    from .detail_panel._constants import retheme_plots
    from .icons import reset_icons, set_base_size, set_theme_icons

    reg = registry if registry is not None else get_registry()
    plugin = reg.get_theme(theme_id)
    apply_tokens(validate_tokens(plugin.tokens()))

    _builtin_themes.set_scheme_resolver(_qt_scheme_name)
    _ACTIVE_THEME_ID = getattr(plugin, "id", theme_id)

    try:
        overrides = plugin.icons()
    except Exception:
        logger.warning("theme %r: icons() failed", theme_id, exc_info=True)
        overrides = None
    set_theme_icons(overrides or None)

    try:
        _EXTRA_QSS = plugin.extra_qss() or ""
    except Exception:
        logger.warning("theme %r: extra_qss() failed", theme_id, exc_info=True)
        _EXTRA_QSS = ""
    _apply_qss()
    install_base_icon_style()
    set_base_size(getattr(plugin, "icon_size", 24))
    reset_icons()
    retheme_plots()
    from .widgets.metric_card import retheme_metric_cards
    retheme_metric_cards()
    _install_scheme_listener()
    if persist:
        save_ui_state("theme", theme_id)
    for fn in list(_theme_listeners):
        try:
            fn(theme_id)
        except Exception:
            logger.exception("theme listener failed after %r", theme_id)
    return theme_id


# ── Public API ─────────────────────────────────────────────────────

def load():
    """Startup init: fonts + theme (light by default)."""
    app = _app()
    _resolve_fonts()
    try:
        load_theme("light", persist=False)
    except Exception:
        apply_tokens(dict(LIGHT_TOKENS))
        _apply_qss()

    ui_font = QFont(Color.UI_FONT, 14)
    ui_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(ui_font)
