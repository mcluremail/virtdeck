"""Shared fixtures for UI tests.

offline/main_window were introduced in M0.2 (the runtime contract) and
are used by several files (test_runtime_contract, test_optimistic).
"""

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from tests.ui.runtime_contract import (
    install_autofire_dialogs,
    install_fake_pool,
    install_guard,
    install_pyqtgraph_shims,
)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item):
    """Drain Qt's deferred-delete queue after every UI test teardown.

    pytest-qt closes tracked widgets in its own ``pytest_runtest_teardown``
    hook (``close()`` + ``deleteLater()``), but DeferredDelete events are
    only delivered by a NESTED event loop — at loop level 0 they stay
    queued forever.  Widgets then accumulate across the whole UI suite
    (each MainWindow contributes hundreds) and every
    ``QApplication.setStyleSheet`` (theme load/retheme) re-polishes all of
    them, degrading the suite quadratically (a full run went from minutes
    to 30+).

    This wrapper runs OUTSIDE pytest-qt's (which is registered
    ``trylast``): after it has queued the deletes, we spin a short nested
    event loop, which delivers them through Qt's normal machinery — small
    batches, in a real loop, never via ``sendPostedEvents(DeferredDelete)``
    outside a loop (that segfaults in PySide6: GC re-entrancy while large
    widget trees are destroyed).  Must be a hook, not a fixture: fixtures
    are torn down before the pytest-qt hook runs.

    Known upstream limitation: PySide6/shiboken 6.12.0 corrupts python
    refcounts when this drain destroys pytest-qt-tracked widget trees
    (flaky fatal ``bool_dealloc`` at interpreter shutdown; confirmed by
    bisection on 2026-10-12, unfixable from our side).  6.8.x (the apt
    repo) and 6.11.x (uv.lock) are clean.  The CI pytest job installs
    floating deps and is red on this until a 6.12.x patch — do not
    re-diagnose, check the PySide changelog first.
    """
    result = yield
    if QCoreApplication.instance() is None:
        return result
    loop = QEventLoop()
    QTimer.singleShot(0, loop.quit)
    loop.exec()
    return result


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
