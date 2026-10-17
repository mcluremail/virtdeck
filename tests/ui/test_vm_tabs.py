"""Tests for VMTabs snapshot tree population with domain Snapshot objects."""
from datetime import datetime
from types import SimpleNamespace

from PySide6.QtWidgets import QLabel, QPushButton, QStackedWidget, QTreeWidget, QTreeWidgetItem

from virtdeck.domain.snapshot import Snapshot
from virtdeck.ui.detail_panel._vm_tabs import VMTabs
from virtdeck.ui.utils import parse_pve_error


def _panel():
    tree = QTreeWidget()
    tree.setColumnCount(6)
    loading = QLabel()
    stack = QStackedWidget()
    stack.addWidget(loading)  # index 0: loading/empty
    stack.addWidget(tree)     # index 1: snapshot list
    return SimpleNamespace(
        vm_snapshots_tree=tree,
        vm_snapshots_loading=loading,
        vm_snapshots_stack=stack,
    )


def _snap(name, parent="", snaptime=0, size=0, desc=""):
    return Snapshot(name=name, description=desc, snaptime=snaptime,
                    parent=parent, vmstate=False, size_bytes=size,
                    vmid=0, vm_name="", host_name="", node="")


class TestPopulateVmSnapshotsTree:
    def test_empty(self, qtbot):
        fake = SimpleNamespace(panel=_panel())
        qtbot.addWidget(fake.panel.vm_snapshots_tree)
        VMTabs.populate_vm_snapshots_tree(fake, [])
        assert fake.panel.vm_snapshots_tree.topLevelItemCount() == 0
        assert fake.panel.vm_snapshots_stack.currentIndex() == 0

    def test_root_snapshots_top_level(self, qtbot):
        fake = SimpleNamespace(panel=_panel())
        qtbot.addWidget(fake.panel.vm_snapshots_tree)
        snaps = [_snap("base", snaptime=1700000000, size=32 * 1024**3, desc="clean")]
        VMTabs.populate_vm_snapshots_tree(fake, snaps)
        tree = fake.panel.vm_snapshots_tree
        assert tree.topLevelItemCount() == 1
        item = tree.topLevelItem(0)
        assert item.text(0) == "base"
        assert item.text(1) == "clean"
        # Д12: the timestamp follows the interface locale
        from virtdeck.ui.i18n import format_datetime
        expected_ts = format_datetime(datetime.fromtimestamp(1700000000))
        assert item.text(2) == expected_ts
        assert item.text(4) == "32.0 GiB"
        assert fake.panel.vm_snapshots_stack.currentIndex() == 1

    def test_nested_children(self, qtbot):
        fake = SimpleNamespace(panel=_panel())
        qtbot.addWidget(fake.panel.vm_snapshots_tree)
        snaps = [
            _snap("work", parent="base"),
            _snap("base"),
            _snap("deep", parent="work"),
        ]
        VMTabs.populate_vm_snapshots_tree(fake, snaps)
        tree = fake.panel.vm_snapshots_tree
        assert tree.topLevelItemCount() == 1
        base_item = tree.topLevelItem(0)
        assert base_item.text(0) == "base"
        assert base_item.childCount() == 1
        work_item = base_item.child(0)
        assert work_item.text(0) == "work"
        assert work_item.childCount() == 1
        assert work_item.child(0).text(0) == "deep"

    def test_orphan_parent_becomes_top_level(self, qtbot):
        """parent references a missing snapshot -> treated as root."""
        fake = SimpleNamespace(panel=_panel())
        qtbot.addWidget(fake.panel.vm_snapshots_tree)
        snaps = [_snap("s1", parent="ghost")]
        VMTabs.populate_vm_snapshots_tree(fake, snaps)
        assert fake.panel.vm_snapshots_tree.topLevelItemCount() == 1


# --- audit 6.3.2a D5/D7: identity gates for stale replies -------------------

class _SignalStub:
    """Minimal Qt-signal double: connect() stores, emit() fires."""

    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, *args):
        for slot in list(self._slots):
            slot(*args)


def _vm_data(vmid=100, host_name="h1", node="pve1", name="web",
             status="running", template=False):
    return SimpleNamespace(
        vmid=vmid, host_name=host_name, node=node, name=name,
        vm_type=SimpleNamespace(value="qemu"), status_value=status,
        template=template)


def _snap_panel(last_vm):
    tree = QTreeWidget()
    tree.setColumnCount(6)
    loading = QLabel()
    stack = QStackedWidget()
    stack.addWidget(loading)  # index 0: loading/empty
    stack.addWidget(tree)     # index 1: snapshot list
    workers = []
    mgr = SimpleNamespace(
        run_worker=lambda w: workers.append(w),
        discard_worker=lambda w: None,
    )
    return SimpleNamespace(
        vm_snapshots_tree=tree, vm_snapshots_loading=loading,
        vm_snapshots_stack=stack, vm_snapshots_cache={},
        _last_vm_data=last_vm, _cfg_by_name={"h1": {"name": "h1"}},
        _generation=1, _workers_mgr=mgr,
    ), workers


class TestReloadSnapshotsIdentity:
    def test_stale_vm_leaves_current_tab_alone(self, qtbot, monkeypatch):
        """Snapshot op finished for VM A while the panel shows VM B:
        B's tab must not be repainted as Loading and no request for A
        may be built from B's node/vm_type; A's cache is dropped so the
        next visit to A refetches."""
        panel, workers = _snap_panel(_vm_data(vmid=200, host_name="h2",
                                              node="pve2"))
        panel.vm_snapshots_cache[("h1", 100)] = [_snap("s1")]
        panel.vm_snapshots_tree.addTopLevelItem(QTreeWidgetItem(["old"]))
        created = []
        monkeypatch.setattr(
            "virtdeck.backend.VmSnapshotsWorker",
            lambda *a, **kw: created.append(a) or SimpleNamespace(
                signals=SimpleNamespace(snapshots_ready=_SignalStub(),
                                        snapshots_error=_SignalStub())))
        VMTabs.reload_snapshots(SimpleNamespace(panel=panel), 100, "h1")
        assert ("h1", 100) not in panel.vm_snapshots_cache
        assert panel.vm_snapshots_tree.topLevelItemCount() == 1
        assert panel.vm_snapshots_loading.text() == ""
        assert created == [] and workers == []

    def test_no_current_vm_is_a_no_op(self, qtbot):
        """Panel closed / cleared: no repaint, no request."""
        panel, workers = _snap_panel(None)
        VMTabs.reload_snapshots(SimpleNamespace(panel=panel), 100, "h1")
        assert ("h1", 100) not in panel.vm_snapshots_cache
        assert panel.vm_snapshots_tree.topLevelItemCount() == 0
        assert workers == []

    def test_current_vm_still_reloads(self, qtbot, monkeypatch):
        panel, workers = _snap_panel(_vm_data())
        created = []

        def fake_worker(cfg, node, vmid, vm_type):
            created.append((cfg, node, vmid, vm_type))
            return SimpleNamespace(signals=SimpleNamespace(
                snapshots_ready=_SignalStub(), snapshots_error=_SignalStub()))

        monkeypatch.setattr("virtdeck.backend.VmSnapshotsWorker", fake_worker)
        VMTabs.reload_snapshots(SimpleNamespace(panel=panel), 100, "h1")
        assert created == [({"name": "h1"}, "pve1", 100, "qemu")]
        assert len(workers) == 1
        assert panel.vm_snapshots_loading.text() == "Loading..."
        assert panel.vm_snapshots_stack.currentIndex() == 0


class TestSnapshotsResultRouting:
    def test_stale_result_updates_cache_only(self, qtbot):
        panel, _ = _snap_panel(_vm_data(vmid=200, host_name="h2"))
        panel._generation = 3
        populated = []
        tabs = SimpleNamespace(panel=panel, populate_vm_snapshots_tree=(
            lambda snaps: populated.append(snaps)))
        VMTabs.on_snapshots_loaded(tabs, 100, ["s1"], 3, "h1")
        assert panel.vm_snapshots_cache[("h1", 100)] == ["s1"]
        assert populated == []
        # the reply for the currently shown VM still paints:
        VMTabs.on_snapshots_loaded(tabs, 200, ["s2"], 3, "h2")
        assert populated == [["s2"]]

    def test_stale_error_leaves_current_view(self, qtbot):
        panel, _ = _snap_panel(_vm_data(vmid=200, host_name="h2"))
        panel._generation = 3
        VMTabs.on_snapshots_error(SimpleNamespace(panel=panel),
                                  100, "boom", 3, "h1")
        assert panel.vm_snapshots_loading.text() == ""


class TestVmActionReplyIdentity:
    def _fake_tabs(self, panel, calls):
        fake = SimpleNamespace(
            panel=panel,
            update_action_buttons=lambda vm: calls.append(("btn", vm)),
            refresh_after_action=lambda: calls.append("refresh"))
        fake._is_current_vm = lambda v, h: VMTabs._is_current_vm(fake, v, h)
        return fake

    def _fake_err_tabs(self, panel):
        fake = SimpleNamespace(panel=panel,
                               update_action_buttons=lambda vm: None)
        fake._is_current_vm = lambda v, h: VMTabs._is_current_vm(fake, v, h)
        return fake

    def test_stale_reply_ignored(self, qtbot):
        panel = SimpleNamespace(detail_label=QLabel(),
                                _last_vm_data=_vm_data(vmid=200,
                                                       host_name="h2"))
        calls = []
        VMTabs.on_action_finished(self._fake_tabs(panel, calls),
                                  "Started", 100, "h1")
        assert panel.detail_label.text() == ""
        assert calls == []

    def test_current_reply_applies(self, qtbot):
        panel = SimpleNamespace(detail_label=QLabel(),
                                _last_vm_data=_vm_data())
        calls = []
        VMTabs.on_action_finished(self._fake_tabs(panel, calls),
                                  "Started", 100, "h1")
        assert panel.detail_label.text() == "VM/CT: web — Started"
        assert calls == [("btn", panel._last_vm_data), "refresh"]

    def test_stale_error_ignored(self, qtbot):
        panel = SimpleNamespace(detail_label=QLabel(),
                                _last_vm_data=_vm_data(vmid=200,
                                                       host_name="h2"))
        VMTabs.on_action_error(self._fake_err_tabs(panel), "boom", 100, "h1")
        assert panel.detail_label.text() == ""

    def test_current_error_shown(self, qtbot):
        panel = SimpleNamespace(detail_label=QLabel(),
                                _last_vm_data=_vm_data())
        VMTabs.on_action_error(self._fake_err_tabs(panel), "boom", 100, "h1")
        assert panel.detail_label.text() == parse_pve_error("boom")

    def test_host_change_breaks_identity(self, qtbot):
        """Same vmid on a different host (or a removed host): no repaint."""
        panel = SimpleNamespace(detail_label=QLabel(),
                                _last_vm_data=_vm_data(host_name="h9"))
        calls = []
        VMTabs.on_action_finished(self._fake_tabs(panel, calls),
                                  "Started", 100, "h1")
        assert calls == []


class TestActionStartRejected:
    def test_rejected_start_restores_buttons_and_header(self, qtbot,
                                                        monkeypatch):
        import virtdeck.ui.detail_panel._vm_tabs as vm_tabs_mod

        btn = QPushButton()
        panel = SimpleNamespace(
            _last_vm_data=_vm_data(),
            _cfg_by_name={"h1": {"name": "h1"}},
            detail_label=QLabel(),
            _action_buttons={"start": btn},
            _workers_mgr=SimpleNamespace(
                run_worker=lambda w: False, discard_worker=lambda w: None),
        )
        monkeypatch.setattr(vm_tabs_mod, "confirm_vm_action",
                            lambda *a, **kw: True)
        fake_worker = SimpleNamespace(signals=SimpleNamespace(
            action_result=_SignalStub(), action_error=_SignalStub()))
        monkeypatch.setattr("virtdeck.backend.VmActionWorker",
                            lambda *a, **kw: fake_worker)
        VMTabs.on_vm_action(SimpleNamespace(
            panel=panel,
            update_action_buttons=lambda vm: btn.setEnabled(True)), "start")
        assert btn.isEnabled()  # re-enabled after the refusal
        assert panel.detail_label.text() == "VM/CT: web"
