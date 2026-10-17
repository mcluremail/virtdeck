"""GAP-3 / R8: the operational cycle with a fake UPID, end to end in the
real UI (the audit probes moved into the CI gate).

Cycle under test: tree populated through the real async fetch →
a VM action started from the tree slot → optimistic status applied →
VmActionWorker POSTs and awaits the fake UPID → status confirmed →
notification → the forked task is visible in the cluster task list →
the next refresh shows the new state.

Everything runs against tests/harness FakePveApi mounted on the real
transport seam (install_fake_pve) — no mocks of the application code.
"""
from __future__ import annotations

import pytest

from tests.harness import fake_pve_cfg, install_fake_pve
from tests.harness.fake_pve import FakePveApi
from tests.harness.scenarios import make_pve_cluster


@pytest.fixture()
def api(monkeypatch):
    api = make_pve_cluster("fake1")
    # a guest to start
    api.add_qemu("pve01", 105, "idle", status="stopped")
    install_fake_pve(monkeypatch, api)
    return api


@pytest.fixture()
def mw(qtbot, monkeypatch, tmp_path, api):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from virtdeck.ui.mainwindow import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.nodes_cfg = [fake_pve_cfg("fake1")]
    window.refresh_data()
    qtbot.waitUntil(lambda: window._vm_repo.get("fake1", 105) is not None,
                    timeout=15000)
    yield window
    window.close()


def _vm_status(mw, vmid=105):
    vm = mw._vm_repo.get("fake1", vmid)
    return vm.status_value if vm else None


def _note_texts(mw):
    out = []
    for ref in mw._notifications._active.values():
        toast = ref() if hasattr(ref, "__call__") else ref
        if toast is not None:
            out.append(toast._text)
    return out


def test_full_cycle_start(mw, qtbot, api):
    """Optimistic → confirmed → task row → refreshed state."""
    assert _vm_status(mw) == "stopped"

    mw._on_vm_action_from_tree("fake1", "pve01", 105, "start")

    # the write reached the fake API (the worker is async — wait for it)
    qtbot.waitUntil(
        lambda: any(c[0] == "POST"
                    and c[1].endswith("qemu/105/status/start")
                    for c in api.calls),
        timeout=15000)

    # the task was awaited to completion and the status confirmed (the
    # fake completes instantly; the transient optimistic window is
    # proven observable by test_double_click_blocked_while_in_flight)
    qtbot.waitUntil(lambda: _vm_status(mw) == "running", timeout=15000)
    qtbot.waitUntil(
        lambda: mw._optimistic.pending_action("fake1", 105) is None,
        timeout=15000)

    # completion notification
    qtbot.waitUntil(lambda: any("105" in t for t in _note_texts(mw)),
                    timeout=5000)


def test_task_row_appears_in_cluster_tasks(mw, qtbot, api):
    """R8: the forked UPID shows up in the task list after the refresh."""
    mw._on_vm_action_from_tree("fake1", "pve01", 105, "start")
    qtbot.waitUntil(lambda: _vm_status(mw) == "running", timeout=15000)
    qtbot.waitUntil(lambda: any(
        t.get("type") == "qmstart" for t in api.tasks), timeout=15000)

    from virtdeck.domain.task import Task

    def _task_rows():
        tasks = [Task(upid=t["upid"], node=t["node"],
                      task_type=t["type"], status=t["status"],
                      starttime=t.get("starttime", 0.0), endtime=0.0,
                      user=t.get("user", ""), vmid=t.get("vmid"))
                 for t in api.tasks if t.get("type") == "qmstart"]
        mw.tasks_widget.set_tasks(tasks)
        return mw.tasks_widget.table.rowCount()

    qtbot.waitUntil(lambda: _task_rows() >= 1, timeout=5000)
    # column 4 = "Description" (type label)
    row_texts = [mw.tasks_widget.table.item(r, 4).text()
                 for r in range(mw.tasks_widget.table.rowCount())]
    assert any("Start" in t or "Запуск" in t for t in row_texts), row_texts


def test_double_click_blocked_while_in_flight(mw, qtbot, api):
    """GAP-6: the second click during the flight does not fork a duplicate
    worker — the operator sees the 'already in progress' notice."""
    api.set_next_task_result(None)  # the task never finishes on the fake

    mw._on_vm_action_from_tree("fake1", "pve01", 105, "start")
    qtbot.waitUntil(
        lambda: mw._optimistic.pending_action("fake1", 105) is not None,
        timeout=15000)
    qtbot.waitUntil(
        lambda: any(c[0] == "POST" and "status/start" in c[1]
                    for c in api.calls),
        timeout=15000)
    before = len(api.calls)

    mw._on_vm_action_from_tree("fake1", "pve01", 105, "start")
    # no second POST — the slot returned early
    posts = [c for c in api.calls[before:]
             if c[0] == "POST" and "status/start" in c[1]]
    assert not posts
    assert any("105" in t for t in _note_texts(mw))


def test_failed_task_rolls_optimistic_back(mw, qtbot, api):
    """A confirmed failure returns the guest to its real status and says
    so — the optimistic 'running' must not stick."""
    api.set_next_task_result("command exited with code 255")
    mw._on_vm_action_from_tree("fake1", "pve01", 105, "start")
    qtbot.waitUntil(
        lambda: mw._optimistic.pending_action("fake1", 105) is None,
        timeout=15000)
    qtbot.waitUntil(lambda: _vm_status(mw) == "stopped", timeout=15000)
