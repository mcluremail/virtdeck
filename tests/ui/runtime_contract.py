"""M0.2: runtime contract "no network calls in the UI thread"
(ROADMAP v3.0). Infrastructure for offline runs of action slots:
- guard provider replaces PluginRegistry.create_provider: any call
  or attribute access on the provider from the main thread is recorded
  as a violation (background threads get a silent stub);
- fake QThreadPool never runs workers — slots freely create workers,
  nobody touches the network;
- autofire patches of static dialog factories (QMessageBox/QInputDialog/
  QFileDialog) return default answers;
- modal-closer closes any popup/modal opened by instance-exec
  (QDialog.exec, QMenu.exec — PySide6 does not let you intercept those
  with a class patch): a timer in exec's own event loop closes the window.

Violations accumulate in the list returned by install_guard():
after walking the slots the test asserts it is empty and prints a report.
"""

import threading

from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QMessageBox,
)


class RuntimeContractViolation(BaseException):
    """Sync-client call in the main thread.

    Inherits BaseException on purpose: slots with ``except Exception``
    must not swallow the violation (raise mode)."""


def _in_main_thread():
    return threading.current_thread() is threading.main_thread()


class _SyncTrap:
    """Trap on the DataProvider path.

    Any call or attribute access from the main thread is a violation
    (appended to collect and/or RuntimeContractViolation); from a
    background thread — a silent stub (the worker gets nothing and
    degrades via the regular error_occurred)."""

    __slots__ = ("_path", "_collect", "_raise_in_main")

    def __init__(self, path="provider", collect=None, raise_in_main=False):
        self._path = path
        self._collect = collect
        self._raise_in_main = raise_in_main

    def _violation(self, what):
        message = f"{self._path}: {what} in the UI thread"
        if self._collect is not None:
            if isinstance(self._collect, list):
                self._collect.append(message)
            else:
                self._collect(message)
        if self._raise_in_main:
            raise RuntimeContractViolation(message)

    def __call__(self, *args, **kwargs):
        if _in_main_thread():
            self._violation("call")
            return None
        return None

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if _in_main_thread():
            self._violation(f"access to .{name}")
        return _SyncTrap(f"{self._path}.{name}", self._collect, self._raise_in_main)

    def __repr__(self):  # pragma: no cover — debugging aid
        return f"<SyncTrap {self._path}>"


def install_guard(monkeypatch, collect=None, raise_in_main=False):
    """Patches PluginRegistry.create_provider with the guard provider.

    Single choke point: every import of create_provider (backend/*,
    ui/api/*) reaches the registry. Returns the violation list (if
    collect is not passed explicitly)."""
    import virtdeck.plugins as plugins_mod

    if collect is None:
        collect = []
    plugin_cls = plugins_mod.PluginRegistry

    def _fake_create_provider(self, cfg, timeout=15):
        return _SyncTrap(f"provider[{cfg.get('name', '?')}]", collect, raise_in_main)

    monkeypatch.setattr(plugin_cls, "create_provider", _fake_create_provider)
    return collect


class _RecordingPool:
    """QThreadPool stub: workers are collected but never run."""

    def __init__(self):
        self.started = []

    def start(self, runnable, priority=0):
        self.started.append(runnable)

    def clear(self):
        self.started.clear()

    def waitForDone(self, msecs=-1):
        return True

    def activeThreadCount(self):
        return 0

    def tryStart(self, runnable):
        self.start(runnable)
        return True

    def reserveThread(self):
        pass

    def releaseThread(self):
        pass


def install_fake_pool(monkeypatch):
    """Swaps QThreadPool.globalInstance for the collecting stub —
    pattern of tests/ui/test_worker_manager.py; one patch covers every
    worker start site (mainwindow, WorkerManager, ui/api)."""
    pool = _RecordingPool()
    monkeypatch.setattr(QThreadPool, "globalInstance", staticmethod(lambda: pool))
    return pool


def install_modal_closer(interval_ms=20):
    """QTimer closing popup/modal windows opened by an action trigger.

    PySide6 does not let you intercept instance-exec (QDialog.exec,
    QMenu.exec) with a class patch — the real exec blocks the UI
    thread. The timer spins in exec's own event loop and closes the
    active window, so exec returns immediately (Rejected/None). Stop
    after the run: stop()."""
    timer = QTimer()
    timer.setInterval(interval_ms)

    def _close_active():
        popup = QApplication.activePopupWidget()
        if popup is not None:
            popup.close()
        modal = QApplication.activeModalWidget()
        if modal is not None:
            modal.close()

    timer.timeout.connect(_close_active)
    return timer


def install_pyqtgraph_shims(monkeypatch):
    """pyqtgraph export is unstable under offscreen: showExportDialog
    raises AttributeError (contextMenuItem is assigned only by a real
    mouse event). Chart export is outside the network contract; the
    shim mutes only that side path."""
    try:
        from pyqtgraph.GraphicsScene.GraphicsScene import GraphicsScene
    except ImportError:  # pragma: no cover — pyqtgraph is a project dep
        return
    monkeypatch.setattr(
        GraphicsScene,
        "showExportDialog",
        lambda self, item=None: None,
        raising=False,
    )


def install_autofire_dialogs(monkeypatch):
    """Static dialog factories answer "cancelled": QMessageBox →
    Yes/Ok, QInputDialog → ("", False), QFileDialog → ("", ""). Modal
    exec of custom dialogs is closed by install_modal_closer. Anything
    that reached the network is caught by the guard provider."""
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: QMessageBox.Ok))
    monkeypatch.setattr(
        QInputDialog,
        "getText",
        staticmethod(lambda *a, **k: ("", False)),
    )
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("", False)))
    monkeypatch.setattr(
        QInputDialog,
        "getMultiLineText",
        staticmethod(lambda *a, **k: ("", False)),
    )
    monkeypatch.setattr(QInputDialog, "getDouble", staticmethod(lambda *a, **k: (0.0, False)))
    monkeypatch.setattr(
        QInputDialog,
        "getItem",
        staticmethod(lambda *a, **k: ("", False)),
    )
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *a, **k: ("", "")),
    )
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: ("", "")),
    )
