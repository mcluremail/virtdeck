"""M0.2: runtime contract "no network calls in the UI thread".

Offline run of action slots: the guard provider records any sync-client
call from the main thread, the fake pool never runs workers, dialogs
auto-accept. ROADMAP requirement: toolbar, tree context menus, dialogs —
no slot may reach the provider synchronously.
"""

import threading

import pytest
from PySide6.QtGui import QAction

import tests.ui.runtime_contract as rc
from tests.ui.runtime_contract import (
    RuntimeContractViolation,
    _SyncTrap,
    install_guard,
)


class TestGuard:
    """Guard provider: catches the sync client in the main thread, lets
    background threads through."""

    def test_main_thread_call_is_recorded(self, monkeypatch):
        violations = install_guard(monkeypatch)
        import virtdeck.plugins as plugins_mod

        provider = plugins_mod.create_provider({"name": "h1", "type": "pve"})
        provider.cluster.get("nodes")
        assert len(violations) == 3
        assert "provider[h1]: access to .cluster" in violations[0]
        assert "provider[h1].cluster: access to .get" in violations[1]
        assert "provider[h1].cluster.get: call" in violations[2]

    def test_raise_mode_raises_base_exception(self, monkeypatch):
        install_guard(monkeypatch, raise_in_main=True)
        import virtdeck.plugins as plugins_mod

        provider = plugins_mod.create_provider({"name": "h1", "type": "pve"})
        with pytest.raises(RuntimeContractViolation):
            provider.vms.list()

    def test_background_thread_is_not_a_violation(self, monkeypatch):
        violations = install_guard(monkeypatch)
        import virtdeck.plugins as plugins_mod

        provider = plugins_mod.create_provider({"name": "h1", "type": "pve"})

        result = {}

        def worker():
            result["value"] = provider.nodes.get("n1")

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        assert result["value"] is None
        assert violations == []


def _run_and_report(actions, violations, label):
    """Triggers each action in isolation and returns the violation
    report: {"action": [guard messages]} — only for offending actions.
    Modal dialogs opened by a slot are closed by the modal-closer."""
    report = {}
    closer = rc.install_modal_closer()
    closer.start()
    try:
        for act in actions:
            before = len(violations)
            act.trigger()
            new = violations[before:]
            if new:
                name = act.objectName() or act.text() or f"<unnamed @ {id(act):#x}>"
                report[f"{label}: {name}"] = new
    finally:
        closer.stop()
    return report


def test_toolbar_actions_make_no_sync_calls(main_window, offline):
    """All MainWindow QActions (toolbar etc.) make no network calls
    in the UI thread."""
    violations, _ = offline
    mw = main_window
    actions = mw.findChildren(QAction)
    assert actions, "MainWindow must have actions"
    report = _run_and_report(actions, violations, "mainwindow")
    assert not report, "Synchronous network calls in the UI thread:\n" + "\n".join(
        f"{k}\n  " + "\n  ".join(v) for k, v in report.items()
    )


def test_tree_context_menus_make_no_sync_calls(qtbot, offline, make_node, make_vm):
    """Tree context menus (VM and host) — actions do not touch the
    network."""
    violations, _ = offline
    from virtdeck.domain.enums import VmStatus
    from virtdeck.domain.repositories import NodeRepository, VmRepository
    from virtdeck.ui.tree_panel import ITEM_KEY_ROLE, VM_KEY_ROLE, TreePanel

    cfg = [{"name": "h1", "cluster": "", "skip": False}]
    tp = TreePanel(cfg)
    qtbot.addWidget(tp)

    node = make_node(host_name="h1", node="pve01")
    vm = make_vm(vmid=100, name="alpha", host_name="h1", node="pve01", status=VmStatus.RUNNING)
    node_repo = NodeRepository()
    node_repo.add(node)
    vm_repo = VmRepository()
    vm_repo.add(vm)
    tp.update_data(node_repo.all(), vm_repo.all(), final=True, node_repo=node_repo, vm_repo=vm_repo)
    tp._build_tree()

    # The context menu opens via itemAt(pos): feed the position of the
    # VM item (found by VM_KEY_ROLE — the text may carry decorations).
    vm_items = []

    def walk(item):
        if item.data(0, VM_KEY_ROLE) is not None:
            vm_items.append(item)
        for i in range(item.childCount()):
            walk(item.child(i))

    for i in range(tp.tree.topLevelItemCount()):
        walk(tp.tree.topLevelItem(i))
    assert vm_items, "VM item must be in the tree"
    # M0.2 tree_panel refactor: the menu is built by a builder, no exec.
    menus = [tp._build_context_menu(vm_items[0])]
    # Host item: same rules for the host menu.
    host_items = []

    def walk_keys(item):
        key = item.data(0, ITEM_KEY_ROLE)
        if key and isinstance(key, tuple) and key[0] == "host":
            host_items.append(item)
        for i in range(item.childCount()):
            walk_keys(item.child(i))

    for i in range(tp.tree.topLevelItemCount()):
        walk_keys(tp.tree.topLevelItem(i))
    if host_items:
        menus.append(tp._build_context_menu(host_items[0]))
    menus = [m for m in menus if m is not None]
    assert menus, "Context menus must be built"
    report = {}
    while menus:
        menu = menus.pop()
        report.update(
            _run_and_report(
                [a for a in menu.actions() if a.isEnabled() and not a.isSeparator()],
                violations,
                f"menu@{menu.title() or 'tree'}",
            )
        )
    assert not report, "Synchronous network calls in the UI thread:\n" + "\n".join(
        f"{k}\n  " + "\n  ".join(v) for k, v in report.items()
    )


def test_trap_in_worker_thread_returns_stub():
    """_SyncTrap from a background thread is a stub (no violations)."""
    collected = []
    trap = _SyncTrap("provider", collect=collected.append)
    result = {}

    def worker():
        sub = trap.cluster
        result["call"] = sub.get("n1")

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert result["call"] is None
    assert collected == []


def test_main_window_fixture_boots_offline(main_window, offline):
    """Sanity: MainWindow boots offline, guard active, no violations
    during load."""
    violations, _ = offline
    assert main_window is not None
    assert violations == []
