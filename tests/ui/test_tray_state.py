"""Регрессии трей-иконки состояния (brand.tray_icon + _update_tray_state)."""

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
    """MainWindow с принудительно «доступным» системным треем.

    Regression #6: в __init__ _init_tray() вызывается до инициализации
    _soft_had_errors — на машине с реальным треем падал AttributeError.
    В offscreen-тестах isSystemTrayAvailable() всегда False, поэтому
    путь не покрывался; здесь он включается принудительно.
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
    # пустой конфиг → offline даже при ошибках soft-цикла
    tray_window._soft_had_errors = True
    tray_window._update_tray_state()
    assert tray_window._tray_state == "offline"
    # есть хосты → error виден
    tray_window.nodes_cfg = [{"name": "pve01", "host": "h",
                              "user": "u", "token_value": "t"}]
    tray_window._update_tray_state()
    assert tray_window._tray_state == "error"
    tray_window._soft_had_errors = False
    tray_window._update_tray_state()
    assert tray_window._tray_state == "ok"
