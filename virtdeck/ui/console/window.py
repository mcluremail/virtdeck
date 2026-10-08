"""Window of the built-in noVNC console (QWebEngineView + WsBridge)."""

import json
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow, QToolBar

from ..i18n import tr
from .bridge import WsBridge
from .page import build_console_html, sticky_key_js

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    _WEBENGINE_OK = True
except ImportError:  # pragma: no cover — minimal build without WebEngine
    _WEBENGINE_OK = False

_NOVNC_DIR = Path(__file__).resolve().parent / "novnc"

_XK_CONTROL_L = 0xFFE3
_XK_SHIFT_L = 0xFFE1
_XK_ALT_L = 0xFFE9
_XK_SUPER_L = 0xFFEB

# Sticky modifiers: (label, keysym, XtScancode). Pressing the button sends
# key-down to the guest, pressing again — key-up; the rest of the combo is
# typed by the user in the console (Ctrl+Alt+Del = sticky Ctrl+Alt, then Del).
_MODIFIERS = (
    ("Shift", _XK_SHIFT_L, "ShiftLeft"),
    ("Ctrl", _XK_CONTROL_L, "ControlLeft"),
    ("Alt", _XK_ALT_L, "AltLeft"),
    ("Win", _XK_SUPER_L, "MetaLeft"),
)

_windows = set()


class NoVncWindow(QMainWindow):
    """Standalone window with the guest RFB screen via the built-in websocket bridge."""

    def __init__(self, host_cfg, node, vmid, vm_type, ws_url, ticket,
                 parent=None):
        super().__init__(parent)
        # The window must be destroyed on close: otherwise the C++ object
        # (QMainWindow + QWebEngineView with its render process) remains
        # a hidden child of mainwindow on every console opening.
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._host_cfg = host_cfg
        self._ticket = ticket
        title = host_cfg.get("name", host_cfg.get("host", ""))
        self.setWindowTitle(
            f"noVNC — {title}: {vm_type.upper()} {vmid} ({node})")
        self.resize(1024, 720)

        self.view = QWebEngineView()
        self.setCentralWidget(self.view)

        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self._sticky_actions = []
        for label, keysym, code in _MODIFIERS:
            action = QAction(label, self)
            action.setCheckable(True)
            # Page not loaded yet, rfb does not exist: a sticky press "before
            # load" would be silently lost and desync button state
            action.setEnabled(False)
            action.toggled.connect(
                lambda checked=False, k=keysym, c=code:
                    self._send_sticky(k, c, checked))
            toolbar.addAction(action)
            self._sticky_actions.append(action)

        auth_header = (
            f"PVEAPIToken={host_cfg['user']}!{host_cfg['token_name']}"
            f"={host_cfg['token_value']}"
        )
        self._bridge = WsBridge(
            ws_url,
            auth_header,
            verify_ssl=not bool(host_cfg.get("trust_ssl", False)),
        )
        self._bridge.port_ready.connect(self._load_console)
        self._bridge.error.connect(self._show_error)
        self._bridge.start()

    def _load_console(self, port):
        html = build_console_html(port, self._ticket)
        try:
            self.view.page().loadFinished.connect(self._on_page_loaded)
        except RuntimeError:
            pass
        self.view.setHtml(html, QUrl.fromLocalFile(str(_NOVNC_DIR) + "/"))

    def _on_page_loaded(self, _ok):
        for action in self._sticky_actions:
            action.setEnabled(True)

    def _send_sticky(self, keysym, code, down):
        try:
            self.view.page().runJavaScript(
                sticky_key_js(keysym, code, down))
        except RuntimeError:
            pass

    def _show_error(self, msg):
        self.statusBar().showMessage(msg, 10000)
        # Mirror the error into the page's own status string — always visible
        try:
            self.view.page().runJavaScript(
                "var el = document.getElementById('status');"
                "if (el) el.textContent = " + json.dumps(str(msg)) + ";"
            )
        except RuntimeError:
            pass

    def closeEvent(self, event):
        self._bridge.stop()
        _windows.discard(self)
        super().closeEvent(event)

    @classmethod
    def open_console(cls, host_cfg, node, vmid, vm_type, ws_url, ticket,
                     parent=None):
        """Create the window and keep a reference until it is closed."""
        if not _WEBENGINE_OK:
            raise RuntimeError(
                tr("PySide6 WebEngine is not available (install full PySide6)"))
        win = cls(host_cfg, node, vmid, vm_type, ws_url, ticket, parent)
        _windows.add(win)
        win.show()
        return win
