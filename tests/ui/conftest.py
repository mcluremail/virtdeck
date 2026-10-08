"""Shared fixtures for UI tests.

offline/main_window were introduced in M0.2 (the runtime contract) and
are used by several files (test_runtime_contract, test_optimistic).
"""

import pytest

from tests.ui.runtime_contract import (
    install_autofire_dialogs,
    install_fake_pool,
    install_guard,
    install_pyqtgraph_shims,
)


@pytest.fixture()
def offline(monkeypatch):
    """Full offline mode: guard + fake pool + autofire dialogs."""
    violations = install_guard(monkeypatch)
    pool = install_fake_pool(monkeypatch)
    install_autofire_dialogs(monkeypatch)
    install_pyqtgraph_shims(monkeypatch)
    return violations, pool


@pytest.fixture()
def main_window(qtbot, monkeypatch, tmp_path, offline):
    """MainWindow as in tests/ui/test_refresh_tracking.py + offline."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from virtdeck.ui.mainwindow import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    yield mw
    mw.close()
