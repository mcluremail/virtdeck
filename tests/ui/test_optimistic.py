"""M0.3: optimistic UI skeleton — "apply now → confirm/rollback".

Unit tests for the OptimisticVMs manager (repository + pending + token),
tree integration (spinner/icon restore) and the end-to-end MainWindow
flow (apply on action, confirm/rollback on the worker signal).
"""

import pytest
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QAction

from virtdeck.domain.enums import VmStatus
from virtdeck.domain.repositories import NodeRepository, VmRepository
from virtdeck.ui.optimistic import (
    POWER_TARGET_STATUS,
    OptimisticToken,
    OptimisticVMs,
)
from virtdeck.ui.tree_panel import VM_KEY_ROLE, TreePanel


@pytest.fixture()
def changes():
    return []


@pytest.fixture()
def repo(make_vm):
    r = VmRepository()
    r.add(make_vm(vmid=100, name="alpha", host_name="h1", node="pve01", status=VmStatus.RUNNING))
    return r


class TestPowerTargets:
    def test_power_actions_covered(self):
        assert set(POWER_TARGET_STATUS) >= {
            "start",
            "stop",
            "shutdown",
            "reboot",
            "reset",
            "resume",
        }

    def test_targets(self):
        assert POWER_TARGET_STATUS["start"] is VmStatus.RUNNING
        assert POWER_TARGET_STATUS["stop"] is VmStatus.STOPPED
        assert POWER_TARGET_STATUS["shutdown"] is VmStatus.STOPPED


class TestOptimisticVMs:
    def test_apply_patches_repo_to_target(self, repo, changes):
        opt = OptimisticVMs(repo, on_change=lambda: changes.append(1))
        token = opt.apply("h1", 100, "stop")
        assert repo.get("h1", 100).status is VmStatus.STOPPED
        assert opt.pending_keys() == {("h1", 100)}
        assert opt.pending_action("h1", 100) == "stop"
        assert isinstance(token, OptimisticToken)
        assert changes

    def test_confirm_clears_pending_keeps_target(self, repo):
        opt = OptimisticVMs(repo)
        token = opt.apply("h1", 100, "stop")
        token.confirm()
        assert opt.pending_keys() == set()
        assert repo.get("h1", 100).status is VmStatus.STOPPED

    def test_rollback_restores_previous(self, repo):
        opt = OptimisticVMs(repo)
        token = opt.apply("h1", 100, "stop")
        token.rollback()
        assert opt.pending_keys() == set()
        assert repo.get("h1", 100).status is VmStatus.RUNNING

    def test_rollback_after_refresh_overwrite(self, repo, make_vm):
        """Refresh overwrote the repository with real data — rollback restores
        the previous status, not the optimistic intermediate."""
        opt = OptimisticVMs(repo)
        token = opt.apply("h1", 100, "stop")
        repo.add(
            make_vm(vmid=100, name="alpha", host_name="h1", node="pve01", status=VmStatus.RUNNING)
        )
        token.rollback()
        assert repo.get("h1", 100).status is VmStatus.RUNNING

    def test_double_apply_keeps_original_prev(self, repo):
        opt = OptimisticVMs(repo)
        opt.apply("h1", 100, "stop")
        opt.apply("h1", 100, "start")
        assert repo.get("h1", 100).status is VmStatus.RUNNING
        opt.rollback("h1", 100)
        assert repo.get("h1", 100).status is VmStatus.RUNNING
        assert opt.pending_keys() == set()

    def test_non_power_action_is_not_applied(self, repo):
        opt = OptimisticVMs(repo)
        assert opt.apply("h1", 100, "migrate") is None
        assert opt.pending_keys() == set()
        assert repo.get("h1", 100).status is VmStatus.RUNNING

    def test_missing_vm_is_not_applied(self, repo):
        opt = OptimisticVMs(repo)
        assert opt.apply("h1", 999, "stop") is None
        assert opt.pending_keys() == set()

    def test_template_is_not_applied(self, repo, make_vm):
        repo.add(
            make_vm(
                vmid=200,
                name="tmpl",
                host_name="h1",
                node="pve01",
                status=VmStatus.STOPPED,
                template=True,
            )
        )
        opt = OptimisticVMs(repo)
        assert opt.apply("h1", 200, "start") is None
        assert opt.pending_keys() == set()

    def test_confirm_rollback_of_unknown_is_noop(self, repo):
        opt = OptimisticVMs(repo)
        opt.confirm("h1", 100)
        opt.rollback("h1", 100)
        assert repo.get("h1", 100).status is VmStatus.RUNNING


class TestTreePending:
    def _tree(self, qtbot, repo, make_node):
        tp = TreePanel([{"name": "h1", "cluster": "", "skip": False}])
        qtbot.addWidget(tp)
        node_repo = NodeRepository()
        node_repo.add(make_node(host_name="h1", node="pve01"))
        tp.update_data(node_repo.all(), repo.all(), final=True, node_repo=node_repo, vm_repo=repo)
        tp._build_tree()
        return tp

    def _vm_item(self, tp):
        def walk(item):
            key = item.data(0, VM_KEY_ROLE)
            if key and key[:2] == ("h1", 100):
                return item
            for i in range(item.childCount()):
                found = walk(item.child(i))
                if found is not None:
                    return found
            return None

        for i in range(tp.tree.topLevelItemCount()):
            found = walk(tp.tree.topLevelItem(i))
            if found is not None:
                return found
        return None

    def _icon_png(self, item):
        """Pixel content of the icon (cacheKey is unreliable: QIcon is
        recreated on every get_icon/make_loading_icon)."""
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        item.icon(0).pixmap(16, 16).save(buf, "PNG")
        return bytes(buf.data())

    def test_pending_item_spins(self, qtbot, repo, make_node):
        tp = self._tree(qtbot, repo, make_node)
        item = self._vm_item(tp)
        assert item is not None
        normal = self._icon_png(item)

        tp.set_pending_vm_keys({("h1", 100)})
        pending = self._icon_png(item)
        assert pending != normal

        tp._tick_spinner()
        assert self._icon_png(item) != pending

        tp.set_pending_vm_keys(set())
        assert self._icon_png(item) == normal
        assert not tp._spin_timer.isActive()

    def test_pending_survives_rebuild(self, qtbot, repo, make_node):
        tp = self._tree(qtbot, repo, make_node)
        item = self._vm_item(tp)
        normal = self._icon_png(item)
        tp.set_pending_vm_keys({("h1", 100)})
        tp._build_tree()
        item = self._vm_item(tp)
        assert self._icon_png(item) != normal
        tp.set_pending_vm_keys(set())
        assert self._icon_png(item) == normal


def test_mainwindow_optimistic_flow(main_window, offline, make_vm):
    """End-to-end: tree action → optimistic status → worker signal
    confirms/rolls back."""
    violations, pool = offline
    mw = main_window
    mw._cfg_by_name["h1"] = {"name": "h1", "type": "pve"}
    mw._vm_repo.add(
        make_vm(vmid=100, name="alpha", host_name="h1", node="pve01", status=VmStatus.RUNNING)
    )

    # start needs no confirmation (not in _CONFIRM_ACTIONS).
    mw._on_vm_action_from_tree("h1", "pve01", 100, "start")
    assert mw._vm_repo.get("h1", 100).status is VmStatus.RUNNING
    assert mw._optimistic.pending_keys() == {("h1", 100)}
    assert mw.tree_panel._pending_vm_keys == {("h1", 100)}

    worker = pool.started[-1]
    worker.signals.action_error.emit("boom")
    assert mw._optimistic.pending_keys() == set()

    mw._on_vm_action_from_tree("h1", "pve01", 100, "start")
    worker2 = pool.started[-1]
    worker2.signals.action_result.emit("ok")
    assert mw._optimistic.pending_keys() == set()
    assert mw.tree_panel._pending_vm_keys == set()


def test_mainwindow_actions_still_offline(main_window, offline):
    """The M0.2 contract survives optimistic integration: running actions
    on MainWindow makes no network calls."""
    violations, _ = offline
    mw = main_window
    actions = mw.findChildren(QAction)
    assert actions
    from tests.ui.test_runtime_contract import _run_and_report

    report = _run_and_report(actions, violations, "mainwindow-optimistic")
    assert not report, "Synchronous network calls on the UI thread:\n" + "\n".join(
        f"{k}\n  " + "\n  ".join(v) for k, v in report.items()
    )
