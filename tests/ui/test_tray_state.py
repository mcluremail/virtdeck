"""Tray state icon regressions (brand.tray_icon + _update_tray_state)."""

import pytest

from tests.ui.runtime_contract import (
    install_autofire_dialogs,
    install_fake_pool,
    install_guard,
    install_pyqtgraph_shims,
)


@pytest.fixture()
def offline(monkeypatch):
    violations = install_guard(monkeypatch)
    pool = install_fake_pool(monkeypatch)
    install_autofire_dialogs(monkeypatch)
    install_pyqtgraph_shims(monkeypatch)
    return violations, pool


@pytest.fixture()
def tray_window(qtbot, monkeypatch, tmp_path, offline):
    """MainWindow with the system tray forced "available".

    Regression #6: in __init__ _init_tray() runs before _soft_had_errors
    is initialized — AttributeError on a machine with a real tray.
    In offscreen tests isSystemTrayAvailable() is always False, so the
    path went uncovered; here it is forced on.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from PySide6.QtWidgets import QSystemTrayIcon

    monkeypatch.setattr(
        QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    from virtdeck.ui.mainwindow import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    yield mw
    mw.close()


def test_init_tray_with_tray_available_does_not_crash(tray_window):
    assert tray_window._tray is not None
    assert tray_window._tray_state in {"ok", "offline", "error"}


def test_update_tray_state_reflects_soft_errors(tray_window):
    # empty config → offline even with soft-cycle errors
    tray_window._soft_had_errors = True
    tray_window._update_tray_state()
    assert tray_window._tray_state == "offline"
    # hosts present → error shown
    tray_window.nodes_cfg = [{"name": "pve01", "host": "h",
                              "user": "u", "token_value": "t"}]
    tray_window._update_tray_state()
    assert tray_window._tray_state == "error"
    tray_window._soft_had_errors = False
    tray_window._update_tray_state()
    assert tray_window._tray_state == "ok"
