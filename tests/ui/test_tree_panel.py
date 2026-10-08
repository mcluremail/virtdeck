"""Tests for TreePanel with domain objects."""
import json

import pytest
from PySide6.QtCore import QMimeData, QPointF
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from virtdeck.domain.enums import VmStatus
from virtdeck.domain.repositories import NodeRepository, VmRepository
from virtdeck.ui.tree_panel import (
    GROUP_MIME,
    INFO_ROLE,
    ITEM_KEY_ROLE,
    VM_KEY_ROLE,
    GroupTreeWidget,
    TreePanel,
)


@pytest.fixture(autouse=True)
def _isolated_tree_state(monkeypatch):
    """B20: keep treeMode ui_state out of the real config DB."""
    import virtdeck.ui.tree_panel as tp_mod

    state = {}
    monkeypatch.setattr(tp_mod, "load_ui_state", lambda key: state.get(key))
    monkeypatch.setattr(
        tp_mod, "save_ui_state", lambda key, value: state.__setitem__(key, value)
    )


def _make_nodes_cfg(standalone_names=None, clusters=None):
    """Build a minimal nodes_cfg list for TreePanel."""
    cfgs = []
    standalone_names = standalone_names or []
    clusters = clusters or {}
    for name in standalone_names:
        cfgs.append({"name": name, "cluster": "", "skip": False})
    for cluster_name, rep_name in clusters.items():
        cfgs.append({"name": rep_name, "cluster": cluster_name, "cluster_rep": True, "skip": False})
    return cfgs


def _collect_items(tp):
    """Return {key_tuple: item} for all tree items."""
    result = {}

    def walk(item):
        key = item.data(0, ITEM_KEY_ROLE)
        if key is not None:
            result[key] = item
        for i in range(item.childCount()):
            walk(item.child(i))

    for i in range(tp.tree.topLevelItemCount()):
        walk(tp.tree.topLevelItem(i))
    return result


class TestTreePanelBuild:
    """TreePanel._build_tree with domain objects via update_data."""

    def test_standalone_node(self, qtbot, make_node):
        cfg = [{"name": "h1", "cluster": "", "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)

        node = make_node(host_name="h1", node="pve01")
        node_repo = NodeRepository()
        node_repo.add(node)
        vm_repo = VmRepository()

        tp.update_data(node_repo.all(), vm_repo.all(), final=True,
                       node_repo=node_repo, vm_repo=vm_repo)
        tp._build_tree()

        # B20: no sections — the standalone host sits flat at top level
        items = _collect_items(tp)
        assert not any(k[0] in ("section", "storage_section") for k in items)
        host_key = ("host", "pve01", "h1")
        assert host_key in items
        assert "pve01" in items[host_key].text(0)
        assert items[host_key].parent() is None

    def test_node_with_vms(self, qtbot, make_node, make_vm):
        cfg = [{"name": "h1", "cluster": "", "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)

        node = make_node(host_name="h1", node="pve01")
        vm1 = make_vm(vmid=100, name="alpha", host_name="h1", node="pve01", status=VmStatus.RUNNING)
        vm2 = make_vm(vmid=101, name="beta", host_name="h1", node="pve01", status=VmStatus.STOPPED)

        node_repo = NodeRepository()
        node_repo.add(node)
        vm_repo = VmRepository()
        vm_repo.add(vm1)
        vm_repo.add(vm2)

        tp.update_data(node_repo.all(), vm_repo.all(), final=True,
                       node_repo=node_repo, vm_repo=vm_repo)
        tp._build_tree()

        items = _collect_items(tp)
        host = items[("host", "pve01", "h1")]
        # [running/total] = [1/2] — name suffix (user's choice)
        assert "[1/2]" in host.text(0)
        # Should have 2 vm children
        assert host.childCount() == 2

    def test_cluster_nodes(self, qtbot, make_node):
        cfg = [{"name": "rep1", "cluster": "mycluster", "cluster_rep": True, "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)

        n1 = make_node(host_name="rep1", node="n1", cluster="mycluster", is_cluster=True)
        n2 = make_node(host_name="rep1", node="n2", cluster="mycluster", is_cluster=True)
        node_repo = NodeRepository()
        node_repo.add(n1)
        node_repo.add(n2)
        vm_repo = VmRepository()

        tp.update_data(node_repo.all(), vm_repo.all(), final=True,
                       node_repo=node_repo, vm_repo=vm_repo)
        tp._build_tree()

        # B20: cluster item lives flat at top level
        items = _collect_items(tp)
        assert not any(k[0] in ("section", "storage_section") for k in items)
        cl = items[("cluster", "mycluster")]
        assert "mycluster" in cl.text(0)
        assert cl.childCount() == 2  # two nodes
        assert cl.parent() is None

    def test_empty_tree(self, qtbot):
        cfg = []
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)

        node_repo = NodeRepository()
        vm_repo = VmRepository()
        tp.update_data(node_repo.all(), vm_repo.all(), final=True,
                       node_repo=node_repo, vm_repo=vm_repo)
        tp._build_tree()
        # B20: no section headers — the tree is simply empty
        assert tp.tree.topLevelItemCount() == 0

    def test_error_node(self, qtbot):
        cfg = [{"name": "h1", "cluster": "", "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)

        err_node_dict = {
            "node": "h1",
            "status": "error",
            "error": "Connection refused",
            "host_name": "h1",
            "_display_name": "h1",
            "_is_cluster": False,
        }
        from virtdeck.domain.node import Node
        node = Node.from_pve(err_node_dict, "h1", "", False)
        node_repo = NodeRepository()
        node_repo.add(node)
        vm_repo = VmRepository()

        tp.update_data(node_repo.all(), vm_repo.all(), final=True,
                       node_repo=node_repo, vm_repo=vm_repo)
        tp._build_tree()

        items = _collect_items(tp)
        host = items[("host", "h1", "h1")]
        assert "h1" in host.text(0)


class TestTreePanelVmCountStr:
    def test_empty(self):
        from virtdeck.ui.tree_panel import _vm_count_str
        assert _vm_count_str([]) == "[0/0]"

    def test_mixed(self, make_vm):
        from virtdeck.ui.tree_panel import _vm_count_str
        vms = [
            make_vm(vmid=1, status=VmStatus.RUNNING),
            make_vm(vmid=2, status=VmStatus.STOPPED),
            make_vm(vmid=3, status=VmStatus.RUNNING),
        ]
        assert _vm_count_str(vms) == "[2/3]"

    def test_with_domain_objects(self, make_vm):
        from virtdeck.ui.tree_panel import _vm_count_str
        vms = [
            make_vm(vmid=1, status=VmStatus.RUNNING),
            make_vm(vmid=2, status=VmStatus.RUNNING),
        ]
        # Domain Vm uses DictCompat.get("status") which returns the string value
        assert _vm_count_str(vms) == "[2/2]"


class TestSelectedVmKeys:
    """TreePanel.selected_vm_keys for bulk actions (B3)."""

    def _build_tree_with_vms(self, qtbot, make_node, make_vm):
        cfg = [{"name": "h1", "cluster": "", "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)

        node = make_node(host_name="h1", node="pve01")
        vm1 = make_vm(vmid=100, name="alpha", host_name="h1", node="pve01",
                      status=VmStatus.RUNNING)
        vm2 = make_vm(vmid=101, name="beta", host_name="h1", node="pve01",
                      status=VmStatus.STOPPED)

        node_repo = NodeRepository()
        node_repo.add(node)
        vm_repo = VmRepository()
        vm_repo.add(vm1)
        vm_repo.add(vm2)

        tp.update_data(node_repo.all(), vm_repo.all(), final=True,
                       node_repo=node_repo, vm_repo=vm_repo)
        tp._build_tree()

        # Collect VM items (items carrying a VM key) — B20: hosts sit
        # directly at top level, VMs are their children
        vm_items = []
        for i in range(tp.tree.topLevelItemCount()):
            host = tp.tree.topLevelItem(i)
            for k in range(host.childCount()):
                vm = host.child(k)
                if vm.data(0, VM_KEY_ROLE) is not None:
                    vm_items.append(vm)
        assert len(vm_items) == 2
        return tp, vm_items

    def test_empty_selection(self, qtbot, make_node, make_vm):
        tp, _vm_items = self._build_tree_with_vms(qtbot, make_node, make_vm)
        assert tp.selected_vm_keys() == []

    def test_single_selection(self, qtbot, make_node, make_vm):
        tp, vm_items = self._build_tree_with_vms(qtbot, make_node, make_vm)
        vm_items[0].setSelected(True)
        keys = tp.selected_vm_keys()
        assert len(keys) == 1
        assert keys[0] == ("h1", 100, "pve01")

    def test_multi_selection(self, qtbot, make_node, make_vm):
        tp, vm_items = self._build_tree_with_vms(qtbot, make_node, make_vm)
        vm_items[0].setSelected(True)
        vm_items[1].setSelected(True)
        keys = tp.selected_vm_keys()
        assert len(keys) == 2
        assert ("h1", 100, "pve01") in keys
        assert ("h1", 101, "pve01") in keys

    def test_extended_selection_mode(self, qtbot, make_node, make_vm):
        tp, _vm_items = self._build_tree_with_vms(qtbot, make_node, make_vm)
        assert tp.tree.selectionMode() == QTreeWidget.SelectionMode.ExtendedSelection


class TestHostGroups:
    """B16: user-defined host groups in the tree."""

    def test_grouped_standalone_host(self, qtbot, make_node, make_vm):
        cfg = [{"name": "h1", "cluster": "", "skip": False, "group": "Site A"}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)

        node = make_node(host_name="h1", node="pve01")
        node_repo = NodeRepository()
        node_repo.add(node)
        vm_repo = VmRepository()
        vm_repo.add(make_vm(vmid=100, name="alpha", host_name="h1",
                            node="pve01", status=VmStatus.RUNNING))

        tp.update_data(node_repo.all(), vm_repo.all(), final=True,
                       node_repo=node_repo, vm_repo=vm_repo)
        tp._build_tree()

        items = _collect_items(tp)
        group_key = next((k for k in items if k[0] == "group"), None)
        assert group_key is not None
        assert group_key[1] == "Site A"
        # Group shows aggregated VM count (name suffix)
        assert "[1/1]" in items[group_key].text(0)
        # Host is under the group, not at top level (B20: no sections)
        host_key = next((k for k in items if k[0] == "host"), None)
        assert host_key == ("host", "pve01", "h1")
        assert items[host_key].parent() is items[group_key]
        assert not any(k[0] in ("section", "storage_section") for k in items)

    def test_grouped_cluster(self, qtbot, make_node, make_vm):
        cfg = [
            {"name": "h1", "cluster": "cl1", "cluster_rep": True, "skip": False,
             "group": "DC West"},
            {"name": "h2", "cluster": "cl1", "cluster_rep": False, "skip": False,
             "group": "DC West"},
        ]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)

        node_repo = NodeRepository()
        node_repo.add(make_node(host_name="h1", node="pve01"))
        vm_repo = VmRepository()
        vm_repo.add(make_vm(vmid=100, name="alpha", host_name="h1",
                            node="pve01", status=VmStatus.RUNNING))

        tp.update_data(node_repo.all(), vm_repo.all(), final=True,
                       node_repo=node_repo, vm_repo=vm_repo)
        tp._build_tree()

        items = _collect_items(tp)
        group_key = next((k for k in items if k[0] == "group"), None)
        assert group_key is not None
        assert group_key[1] == "DC West"
        # Cluster item lives inside the group (B20: no sections)
        cluster_key = next((k for k in items if k[0] == "cluster"), None)
        assert cluster_key == ("cluster", "cl1")
        assert items[cluster_key].parent() is items[group_key]
        assert not any(k[0] in ("section", "storage_section") for k in items)

    def test_ungrouped_hosts_flat(self, qtbot, make_node):
        cfg = [
            {"name": "h1", "cluster": "", "skip": False, "group": "Site A"},
            {"name": "h2", "cluster": "", "skip": False},
        ]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)

        node_repo = NodeRepository()
        node_repo.add(make_node(host_name="h1", node="n1"))
        node_repo.add(make_node(host_name="h2", node="n2"))

        tp.update_data(node_repo.all(), [], final=True,
                       node_repo=node_repo, vm_repo=None)
        tp._build_tree()

        items = _collect_items(tp)
        group_key = next((k for k in items if k[0] == "group"), None)
        assert group_key == ("group", "Site A")
        hosts = [k for k in items if k[0] == "host"]
        host_parents = {k: items[k].parent() for k in hosts}
        h1_key = next(k for k in hosts if k[2] == "h1")
        h2_key = next(k for k in hosts if k[2] == "h2")
        assert host_parents[h1_key] is items[group_key]
        # B20: no sections — ungrouped host sits flat at top level
        assert host_parents[h2_key] is None

    def test_group_of_cluster_applies_to_all_members(self, qtbot, make_node):
        """Partial cfg grouping: group on rep cfg only still pulls the cluster."""
        cfg = [
            {"name": "h1", "cluster": "cl1", "cluster_rep": True, "skip": False,
             "group": "DC"},
            {"name": "h2", "cluster": "cl1", "cluster_rep": False, "skip": False},
        ]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)

        node_repo = NodeRepository()
        node_repo.add(make_node(host_name="h1", node="pve01"))
        node_repo.add(make_node(host_name="h2", node="pve02"))

        tp.update_data(node_repo.all(), [], final=True,
                       node_repo=node_repo, vm_repo=None)
        tp._build_tree()

        items = _collect_items(tp)
        cluster_key = next((k for k in items if k[0] == "cluster"), None)
        assert cluster_key == ("cluster", "cl1")
        group_key = next(k for k in items if k[0] == "group")
        assert items[cluster_key].parent() is items[group_key]


class _FakeDropEvent:
    """Mimics QDropEvent for GroupTreeWidget._decode/_drop_group tests."""

    def __init__(self, mime):
        self._mime = mime
        self.accepted = False
        self.ignored = False

    def mimeData(self):
        return self._mime

    def position(self):
        return QPointF(0, 0)

    def acceptProposedAction(self):
        self.accepted = True

    def ignore(self):
        self.ignored = True


class TestGroupDragDrop:
    """B16: drag&drop hosts/clusters into groups."""

    def _make_widget(self, qtbot):
        cfg = [
            {"name": "h1", "cluster": "", "skip": False, "group": "G"},
            {"name": "h2", "cluster": "", "skip": False},
        ]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)
        gt = tp.tree
        assert isinstance(gt, GroupTreeWidget)

        group = QTreeWidgetItem(["G"])
        group.setData(0, ITEM_KEY_ROLE, ("group", "G"))
        gt.addTopLevelItem(group)
        host_in_group = QTreeWidgetItem(["h1"])
        host_in_group.setData(0, ITEM_KEY_ROLE, ("host", "n1", "h1"))
        group.addChild(host_in_group)
        cluster_in_group = QTreeWidgetItem(["cl1"])
        cluster_in_group.setData(0, ITEM_KEY_ROLE, ("cluster", "cl1"))
        group.addChild(cluster_in_group)

        host_flat = QTreeWidgetItem(["h2"])
        host_flat.setData(0, ITEM_KEY_ROLE, ("host", "n2", "h2"))
        gt.addTopLevelItem(host_flat)

        items = {
            "group": group,
            "host_in_group": host_in_group,
            "cluster_in_group": cluster_in_group,
            "host_flat": host_flat,
        }
        return tp, gt, items

    def test_drag_payload(self, qtbot):
        _tp, gt, items = self._make_widget(qtbot)
        assert gt._drag_payload(items["host_in_group"]) == {"kind": "host", "name": "h1"}
        assert gt._drag_payload(items["cluster_in_group"]) == {"kind": "cluster", "name": "cl1"}
        assert gt._drag_payload(items["host_flat"]) == {"kind": "host", "name": "h2"}
        # Non-draggable: group and plain items
        assert gt._drag_payload(items["group"]) is None
        assert gt._drag_payload(QTreeWidgetItem(["vm"])) is None
        assert gt._drag_payload(None) is None

    def test_decode_valid_and_invalid(self, qtbot):
        _tp, gt, _items = self._make_widget(qtbot)
        mime = QMimeData()
        mime.setData(GROUP_MIME, json.dumps({"kind": "host", "name": "h1"}).encode())
        assert gt._decode(_FakeDropEvent(mime)) == {"kind": "host", "name": "h1"}

        wrong_mime = QMimeData()
        wrong_mime.setData("text/plain", b"x")
        assert gt._decode(_FakeDropEvent(wrong_mime)) is None

        bad_json = QMimeData()
        bad_json.setData(GROUP_MIME, b"{not json")
        assert gt._decode(_FakeDropEvent(bad_json)) is None

        bad_kind = QMimeData()
        bad_kind.setData(GROUP_MIME, json.dumps({"kind": "vm", "name": "x"}).encode())
        assert gt._decode(_FakeDropEvent(bad_kind)) is None

    def test_drop_group_resolution(self, qtbot):
        _tp, gt, items = self._make_widget(qtbot)
        assert gt._drop_group(items["group"]) == "G"
        assert gt._drop_group(items["host_in_group"]) == "G"
        assert gt._drop_group(items["cluster_in_group"]) == "G"
        # B20: no sections — a host outside any group is not a target
        assert gt._drop_group(items["host_flat"]) is None
        assert gt._drop_group(None) is None

    def test_drop_event_emits_group_move(self, qtbot):
        tp, gt, items = self._make_widget(qtbot)
        gt.itemAt = lambda _p: items["host_in_group"]
        emitted = []
        tp.group_move_requested.connect(lambda k, n, g: emitted.append((k, n, g)))

        mime = QMimeData()
        mime.setData(GROUP_MIME, json.dumps({"kind": "host", "name": "h9"}).encode())
        event = _FakeDropEvent(mime)
        gt.dropEvent(event)

        assert event.accepted and not event.ignored
        assert emitted == [("host", "h9", "G")]

    def test_drop_event_ignored_on_invalid_target(self, qtbot):
        tp, gt, items = self._make_widget(qtbot)
        gt.itemAt = lambda _p: items["host_flat"]
        emitted = []
        tp.group_move_requested.connect(lambda k, n, g: emitted.append((k, n, g)))

        mime = QMimeData()
        mime.setData(GROUP_MIME, json.dumps({"kind": "host", "name": "h9"}).encode())
        event = _FakeDropEvent(mime)
        gt.dropEvent(event)

        assert event.ignored and not event.accepted
        assert emitted == []


def _find_item(tp, text_part):
    """Depth-first search for an item whose column-0 text contains text_part."""
    def walk(item):
        if text_part in item.text(0):
            return item
        for i in range(item.childCount()):
            found = walk(item.child(i))
            if found:
                return found
        return None
    for i in range(tp.tree.topLevelItemCount()):
        found = walk(tp.tree.topLevelItem(i))
        if found:
            return found
    return None


class TestTreePanelNotes:
    """B19: per-item notes — now an info line under the name (INFO_ROLE)."""

    def test_host_default_note_is_fqdn(self, qtbot, make_node):
        cfg = [{"name": "h1", "host": "pve01.example.com", "cluster": "", "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)
        node = make_node(host_name="h1", node="pve01")
        tp.update_data([node], [], final=True)

        host_item = _find_item(tp, "pve01")
        assert host_item is not None
        assert host_item.data(0, INFO_ROLE) == "pve01.example.com"

    def test_host_user_note_overrides_fqdn(self, qtbot, make_node):
        cfg = [{"name": "h1", "host": "pve01.example.com", "cluster": "", "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)
        tp._tree_notes["host:h1"] = "Main node"
        node = make_node(host_name="h1", node="pve01")
        tp.update_data([node], [], final=True)

        host_item = _find_item(tp, "pve01")
        assert host_item is not None
        assert host_item.data(0, INFO_ROLE) == "Main node"

    def test_cluster_and_vm_notes(self, qtbot, make_node, make_vm):
        cfg = [{"name": "h1", "cluster": "c1", "cluster_rep": True, "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)
        tp._tree_notes["cluster:c1"] = "Prod cluster"
        tp._tree_notes["vm:h1:100"] = "web server"
        node = make_node(host_name="h1", node="pve01", cluster="c1")
        vm = make_vm(host_name="h1", node="pve01", vmid=100)
        tp.update_data([node], [vm], final=True)

        cl_item = _find_item(tp, "c1")
        assert cl_item is not None
        assert cl_item.data(0, INFO_ROLE) == "Prod cluster"
        vm_item = _find_item(tp, "test-vm")
        assert vm_item is not None
        assert vm_item.data(0, INFO_ROLE) == "web server"

    def test_no_note_without_cfg_host(self, qtbot, make_node):
        cfg = [{"name": "h1", "cluster": "", "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)
        node = make_node(host_name="h1", node="pve01")
        tp.update_data([node], [], final=True)

        host_item = _find_item(tp, "pve01")
        assert host_item is not None
        assert not host_item.data(0, INFO_ROLE)

    def test_long_note_truncated_with_tooltip(self, qtbot, make_node):
        cfg = [{"name": "h1", "host": "pve01.example.com", "cluster": "", "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)
        tp._tree_notes["host:h1"] = "x" * 80
        node = make_node(host_name="h1", node="pve01")
        tp.update_data([node], [], final=True)

        host_item = _find_item(tp, "pve01")
        assert host_item.data(0, INFO_ROLE) == "x" * 59 + "…"
        assert "x" * 80 in host_item.toolTip(0)


class TestTreeModes:
    """B20: Hosts / Storages view modes."""

    def test_default_mode_is_hosts(self, qtbot):
        cfg = [{"name": "h1", "cluster": "", "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)
        assert tp._tree_mode == "hosts"
        assert tp._mode_combo.currentData() == "hosts"
        assert tp._mode_combo.count() == 3

    def test_flat_top_level_mix(self, qtbot, make_node):
        """B20: clusters and standalone hosts share one flat top level."""
        cfg = [
            {"name": "bhost", "cluster": "", "skip": False},
            {"name": "rep", "cluster": "acl", "cluster_rep": True, "skip": False},
        ]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)

        node_repo = NodeRepository()
        node_repo.add(make_node(host_name="rep", node="n1", cluster="acl", is_cluster=True))
        node_repo.add(make_node(host_name="bhost", node="n2"))
        tp.update_data(node_repo.all(), [], final=True,
                       node_repo=node_repo, vm_repo=None)

        top_keys = [
            tp.tree.topLevelItem(i).data(0, ITEM_KEY_ROLE)
            for i in range(tp.tree.topLevelItemCount())
        ]
        # Sorted together: cluster "acl" before host "bhost"
        assert top_keys == [("cluster", "acl"), ("host", "n2", "bhost")]

    def test_storages_mode_layout(self, qtbot, make_node, make_storage):
        cfg = [
            {"name": "h1", "cluster": "cl1", "cluster_rep": True, "skip": False},
            {"name": "h2", "cluster": "", "skip": False},
        ]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)

        node_repo = NodeRepository()
        n1 = make_node(host_name="h1", node="n1", cluster="cl1", is_cluster=True)
        n2 = make_node(host_name="h2", node="n2")
        node_repo.add(n1)
        node_repo.add(n2)
        storages = [
            make_storage(host_name="h1", node="n1", cluster="cl1",
                         storage="ceph", shared=True),
            make_storage(host_name="h1", node="n1", cluster="cl1",
                         storage="local", shared=False),
            make_storage(host_name="h2", node="n2", storage="local2"),
        ]
        tp.update_data(node_repo.all(), [], storages, final=True,
                       node_repo=node_repo, vm_repo=None)
        tp.set_mode("storages")

        items = _collect_items(tp)
        # Shared storage hangs off the cluster item, labelled "@cluster"
        shared = items[("storage", "ceph", "cluster", "cl1")]
        assert "@cl1" in shared.text(0)
        assert shared.parent() is items[("cluster", "cl1")]
        # Local cluster-node storage hangs off the host inside the cluster
        local = items[("storage", "local", "host", "h1")]
        assert local.parent() is items[("host", "n1", "h1")]
        assert items[("host", "n1", "h1")].parent() is items[("cluster", "cl1")]
        # Standalone host keeps its own storages
        s2 = items[("storage", "local2", "host", "h2")]
        assert s2.parent() is items[("host", "n2", "h2")]
        assert not any(k[0] in ("section", "storage_section") for k in items)

    def test_storages_mode_false_cluster_cfg(self, qtbot, make_node):
        """Real-world regression: standalone host configs store
        "cluster": false (JSON bool). The worker used to pass it through
        raw, so Storage.cluster was False and the storages view dropped
        all local storages (False == "" is False)."""
        from virtdeck.domain.storage import Storage as DomainStorage

        cfg = [{"name": "h1", "cluster": False, "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)

        node_repo = NodeRepository()
        node_repo.add(make_node(host_name="h1", node="n1"))
        # Same path as mainwindow.on_worker_finished: cluster arg comes
        # from node_cfg["cluster"] == False and must normalize to "".
        st = DomainStorage.from_pve(
            {"storage": "local", "node": "n1", "type": "dir",
             "content": "images", "plugintype": "dir",
             "disk": 1, "maxdisk": 10},
            "h1", False,  # type: ignore[arg-type]
        )
        assert st.cluster == ""
        tp.update_data(node_repo.all(), [], [st], final=True,
                       node_repo=node_repo, vm_repo=None)
        tp.set_mode("storages")

        items = _collect_items(tp)
        assert ("storage", "local", "host", "h1") in items

    def test_shared_storage_dedup(self, qtbot, make_node, make_storage):
        """The same shared storage reported by several nodes appears once."""
        cfg = [{"name": "h1", "cluster": "cl1", "cluster_rep": True, "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)

        node_repo = NodeRepository()
        node_repo.add(make_node(host_name="h1", node="n1", cluster="cl1", is_cluster=True))
        node_repo.add(make_node(host_name="h1", node="n2", cluster="cl1", is_cluster=True))
        storages = [
            make_storage(host_name="h1", node="n1", cluster="cl1",
                         storage="ceph", shared=True),
            make_storage(host_name="h1", node="n2", cluster="cl1",
                         storage="ceph", shared=True),
        ]
        tp.update_data(node_repo.all(), [], storages, final=True,
                       node_repo=node_repo, vm_repo=None)
        tp.set_mode("storages")

        items = _collect_items(tp)
        # Top-level @cluster item appears once (dedup across nodes)
        top = items[("storage", "ceph", "cluster", "cl1")]
        assert "@cl1" in top.text(0)
        assert top.parent() is items[("cluster", "cl1")]
        # 1 shared storage + 2 member hosts (n1, n2), nothing else
        assert items[("cluster", "cl1")].childCount() == 3

    def test_shared_storage_per_node_children(self, qtbot, make_node, make_storage):
        """Shared @cluster storage expands into per-node rows with
        per-node usage (B12a prep: 'local cluster storages shown
        correctly')."""
        cfg = [{"name": "h1", "cluster": "cl1", "cluster_rep": True, "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)

        node_repo = NodeRepository()
        node_repo.add(make_node(host_name="h1", node="n1", cluster="cl1", is_cluster=True))
        node_repo.add(make_node(host_name="h1", node="n2", cluster="cl1", is_cluster=True))
        storages = [
            make_storage(host_name="h1", node="n1", cluster="cl1",
                         storage="ceph", shared=True),
            make_storage(host_name="h1", node="n2", cluster="cl1",
                         storage="ceph", shared=True,
                         used_bytes=50 * 1024**3),
        ]
        tp.update_data(node_repo.all(), [], storages, final=True,
                       node_repo=node_repo, vm_repo=None)
        tp.set_mode("storages")

        items = _collect_items(tp)
        parent = items[("storage", "ceph", "cluster", "cl1")]
        assert parent.childCount() == 2
        n1 = items[("storage", "ceph", "host", "h1", "n1")]
        n2 = items[("storage", "ceph", "host", "h1", "n2")]
        assert n1.parent() is parent
        assert n1.text(0) == "ceph (n1@cl1)"
        assert n1.data(0, INFO_ROLE) == "10%"
        assert n2.text(0) == "ceph (n2@cl1)"
        assert n2.data(0, INFO_ROLE) == "50%"

    def test_mode_persisted_and_restored(self, qtbot, make_node, monkeypatch):
        import virtdeck.ui.tree_panel as tp_mod

        saved = {}
        monkeypatch.setattr(tp_mod, "save_ui_state", lambda k, v: saved.__setitem__(k, v))
        monkeypatch.setattr(tp_mod, "load_ui_state", lambda k: saved.get(k))

        cfg = [{"name": "h1", "cluster": "", "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)
        assert tp._tree_mode == "hosts"

        tp.set_mode("storages")
        assert tp._tree_mode == "storages"
        assert saved == {"treeMode": "storages"}
        assert tp._mode_combo.currentData() == "storages"

        tp2 = TreePanel(cfg)
        qtbot.addWidget(tp2)
        assert tp2._tree_mode == "storages"

    def test_set_mode_same_value_noop(self, qtbot, monkeypatch):
        import virtdeck.ui.tree_panel as tp_mod

        calls = []
        monkeypatch.setattr(tp_mod, "save_ui_state", lambda k, v: calls.append((k, v)))
        cfg = [{"name": "h1", "cluster": "", "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)
        tp.set_mode("hosts")
        assert calls == []

    def test_reveal_key_switches_mode(self, qtbot, make_node, make_storage):
        cfg = [{"name": "h1", "cluster": "cl1", "cluster_rep": True, "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)

        node_repo = NodeRepository()
        node_repo.add(make_node(host_name="h1", node="n1", cluster="cl1", is_cluster=True))
        storages = [make_storage(host_name="h1", node="n1", cluster="cl1",
                                 storage="ceph", shared=True)]
        tp.update_data(node_repo.all(), [], storages, final=True,
                       node_repo=node_repo, vm_repo=None)
        assert tp._tree_mode == "hosts"

        tp.reveal_key(("storage", "ceph", "cluster", "cl1"))
        assert tp._tree_mode == "storages"
        current = tp.tree.currentItem()
        assert current is not None
        assert current.data(0, ITEM_KEY_ROLE) == ("storage", "ceph", "cluster", "cl1")

        # Host keys do not switch the mode
        tp.set_mode("hosts")
        tp.reveal_key(("host", "n1", "h1"))
        assert tp._tree_mode == "hosts"
        assert tp.tree.currentItem().data(0, ITEM_KEY_ROLE) == ("host", "n1", "h1")


class TestPbsView:
    """'Backup servers view' (pbs) tree mode."""

    @staticmethod
    def _cfg():
        return [
            {"name": "h1", "cluster": "", "skip": False},
            {"name": "pbs1", "type": "pbs", "host": "pbs.example", "skip": False},
        ]

    def test_pbs_mode_in_combo(self, qtbot):
        tp = TreePanel(self._cfg())
        qtbot.addWidget(tp)
        data = [tp._mode_combo.itemData(i) for i in range(tp._mode_combo.count())]
        assert data == ["hosts", "storages", "pbs"]

    def test_pbs_view_lists_servers_not_hosts(self, qtbot, make_node):
        tp = TreePanel(self._cfg())
        qtbot.addWidget(tp)

        node_repo = NodeRepository()
        node_repo.add(make_node(host_name="h1", node="n1"))
        tp.update_data(node_repo.all(), [], [], final=True,
                       node_repo=node_repo, vm_repo=None)
        tp.set_mode("pbs")

        keys = [tp.tree.topLevelItem(i).data(0, ITEM_KEY_ROLE)
                for i in range(tp.tree.topLevelItemCount())]
        assert keys == [("pbs", "pbs1")]
        assert tp.tree.topLevelItem(0).text(0) == "pbs1"

    def test_hosts_view_has_no_pbs(self, qtbot, make_node):
        tp = TreePanel(self._cfg())
        qtbot.addWidget(tp)

        node_repo = NodeRepository()
        node_repo.add(make_node(host_name="h1", node="n1"))
        tp.update_data(node_repo.all(), [], [], final=True,
                       node_repo=node_repo, vm_repo=None)

        keys = [tp.tree.topLevelItem(i).data(0, ITEM_KEY_ROLE)
                for i in range(tp.tree.topLevelItemCount())]
        assert keys == [("host", "n1", "h1")]

    def test_loading_stubs_only_in_pbs_mode(self, qtbot):
        tp = TreePanel(self._cfg())
        qtbot.addWidget(tp)

        tp.start_loading()
        keys = [tp.tree.topLevelItem(i).data(0, ITEM_KEY_ROLE)
                for i in range(tp.tree.topLevelItemCount())]
        assert ("pbs", "pbs1") not in keys

        tp.set_mode("pbs")
        tp.start_loading()
        keys = [tp.tree.topLevelItem(i).data(0, ITEM_KEY_ROLE)
                for i in range(tp.tree.topLevelItemCount())]
        assert keys == [("pbs", "pbs1")]

    def test_pbs_datastore_children(self, qtbot):
        from virtdeck.domain.pbs import PbsDatastore

        tp = TreePanel(self._cfg())
        qtbot.addWidget(tp)
        tp.set_mode("pbs")
        tp.update_data(NodeRepository().all(), [], [], final=True,
                       node_repo=NodeRepository(), vm_repo=None)
        tp.set_pbs_datastores("pbs1", [PbsDatastore(
            name="store1", usage=0.25)])

        items = _collect_items(tp)
        ds = items[("pbs_datastore", "pbs1", "store1")]
        assert ds.parent().data(0, ITEM_KEY_ROLE) == ("pbs", "pbs1")
        assert ds.data(0, INFO_ROLE) == "25%"

    def test_pbs_mode_persisted_and_restored(self, qtbot, monkeypatch):
        import virtdeck.ui.tree_panel as tp_mod

        saved = {}
        monkeypatch.setattr(tp_mod, "save_ui_state",
                            lambda k, v: saved.__setitem__(k, v))
        monkeypatch.setattr(tp_mod, "load_ui_state", lambda k: saved.get(k))

        tp = TreePanel(self._cfg())
        qtbot.addWidget(tp)
        tp.set_mode("pbs")
        assert saved == {"treeMode": "pbs"}

        tp2 = TreePanel(self._cfg())
        qtbot.addWidget(tp2)
        assert tp2._tree_mode == "pbs"

    def test_invalid_saved_mode_falls_back(self, qtbot, monkeypatch):
        import virtdeck.ui.tree_panel as tp_mod

        monkeypatch.setattr(tp_mod, "load_ui_state", lambda k: "bogus")
        tp = TreePanel(self._cfg())
        qtbot.addWidget(tp)
        assert tp._tree_mode == "hosts"

    def test_reveal_key_pbs_switches_mode(self, qtbot):
        tp = TreePanel(self._cfg())
        qtbot.addWidget(tp)
        tp.update_data(NodeRepository().all(), [], [], final=True,
                       node_repo=NodeRepository(), vm_repo=None)
        assert tp._tree_mode == "hosts"

        tp.reveal_key(("pbs", "pbs1"))
        assert tp._tree_mode == "pbs"
        assert tp.tree.currentItem().data(0, ITEM_KEY_ROLE) == ("pbs", "pbs1")


class _FakeMenu:
    """Stands in for QMenu (Shiboken forbids patching QMenu.exec)."""

    def __init__(self, *a, **k):
        self._actions = []

    def addAction(self, action):
        if isinstance(action, str):
            from PySide6.QtGui import QAction
            action = QAction(action, None)
        self._actions.append(action)
        return action

    def addMenu(self, *a, **k):
        sub = _FakeMenu()
        self._actions.append(sub)
        return sub

    def addSeparator(self):
        pass

    def actions(self):
        return self._actions

    def setStyleSheet(self, *a, **k):
        pass

    def exec(self, *a, **k):
        pass


def _open_menu(qtbot, tp, item, monkeypatch):
    """Open the context menu for an item (QMenu swapped for a fake)."""
    import virtdeck.ui.tree_panel as tp_mod

    created = []

    class _RecordingMenu(_FakeMenu):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            created.append(self)

    monkeypatch.setattr(tp_mod, "QMenu", _RecordingMenu)
    monkeypatch.setattr(tp.tree, "itemAt", lambda *a, **k: item)
    tp._on_context_menu(QPointF(0, 0))
    return created[0] if created else None


def _menu_actions(menu):
    from PySide6.QtGui import QAction
    return [a.text() for a in menu.actions()
            if isinstance(a, QAction) and a.text()]


class TestStorageContextMenu:
    """B4: storage config actions in the tree context menu."""

    def test_host_storage_item_edit_delete(self, qtbot, make_node, make_storage,
                                           monkeypatch):
        cfg = [{"name": "h1", "cluster": "", "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)
        node_repo = NodeRepository()
        node_repo.add(make_node(host_name="h1", node="n1"))
        storages = [make_storage(host_name="h1", node="n1", storage="local")]
        tp.update_data(node_repo.all(), [], storages, final=True,
                       node_repo=node_repo, vm_repo=None)
        tp.set_mode("storages")

        item = _collect_items(tp)[("storage", "local", "host", "h1")]
        menu = _open_menu(qtbot, tp, item, monkeypatch)
        texts = _menu_actions(menu)
        assert "Edit storage…" in texts
        assert "Delete storage" in texts

        edits, deletes = [], []
        tp.storage_edit_requested.connect(lambda h, s: edits.append((h, s)))
        tp.storage_delete_requested.connect(lambda h, s: deletes.append((h, s)))
        from PySide6.QtGui import QAction as _QA
        for act in menu.actions():
            if not isinstance(act, _QA):
                continue
            if act.text() == "Edit storage…":
                act.trigger()
            if act.text() == "Delete storage":
                act.trigger()
        assert edits == [("h1", "local")]
        assert deletes == [("h1", "local")]

    def test_per_node_storage_item_resolves_host(self, qtbot, make_node,
                                                 make_storage, monkeypatch):
        cfg = [{"name": "h1", "cluster": "cl1", "cluster_rep": True, "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)
        node_repo = NodeRepository()
        node_repo.add(make_node(host_name="h1", node="n1", cluster="cl1",
                                is_cluster=True))
        node_repo.add(make_node(host_name="h1", node="n2", cluster="cl1",
                                is_cluster=True))
        storages = [
            make_storage(host_name="h1", node="n1", cluster="cl1",
                         storage="ceph", shared=True),
            make_storage(host_name="h1", node="n2", cluster="cl1",
                         storage="ceph", shared=True),
        ]
        tp.update_data(node_repo.all(), [], storages, final=True,
                       node_repo=node_repo, vm_repo=None)
        tp.set_mode("storages")

        item = _collect_items(tp)[("storage", "ceph", "host", "h1", "n2")]
        menu = _open_menu(qtbot, tp, item, monkeypatch)
        edits = []
        tp.storage_edit_requested.connect(lambda h, s: edits.append((h, s)))
        from PySide6.QtGui import QAction as _QA
        for act in menu.actions():
            if not isinstance(act, _QA):
                continue
            if act.text() == "Edit storage…":
                act.trigger()
        assert edits == [("h1", "ceph")]

    def test_cluster_storage_item_resolves_first_member(self, qtbot, make_node,
                                                        make_storage, monkeypatch):
        cfg = [{"name": "h1", "cluster": "cl1", "cluster_rep": True, "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)
        node_repo = NodeRepository()
        node_repo.add(make_node(host_name="h1", node="n1", cluster="cl1",
                                is_cluster=True))
        storages = [make_storage(host_name="h1", node="n1", cluster="cl1",
                                 storage="ceph", shared=True)]
        tp.update_data(node_repo.all(), [], storages, final=True,
                       node_repo=node_repo, vm_repo=None)
        tp.set_mode("storages")

        item = _collect_items(tp)[("storage", "ceph", "cluster", "cl1")]
        menu = _open_menu(qtbot, tp, item, monkeypatch)
        deletes = []
        tp.storage_delete_requested.connect(lambda h, s: deletes.append((h, s)))
        from PySide6.QtGui import QAction as _QA
        for act in menu.actions():
            if not isinstance(act, _QA):
                continue
            if act.text() == "Delete storage":
                act.trigger()
        assert deletes == [("h1", "ceph")]

    def test_no_actions_without_api_host(self, qtbot, make_node, monkeypatch):
        """Cluster-scope storage with no matching cluster cfg → no CRUD actions."""
        cfg = []
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)

        # Fabricated item not present in the tree — the menu code only
        # reads its key, and clX has no member configs.
        from PySide6.QtWidgets import QTreeWidgetItem
        item = QTreeWidgetItem()
        item.setData(0, ITEM_KEY_ROLE, ("storage", "ceph", "cluster", "clX"))
        menu = _open_menu(qtbot, tp, item, monkeypatch)
        texts = _menu_actions(menu)
        assert "Edit storage…" not in texts
        assert "Delete storage" not in texts

    def test_create_storage_on_host(self, qtbot, make_node, monkeypatch):
        cfg = [{"name": "h1", "cluster": "", "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)
        node_repo = NodeRepository()
        node_repo.add(make_node(host_name="h1", node="n1"))
        tp.update_data(node_repo.all(), [], [], final=True,
                       node_repo=node_repo, vm_repo=None)
        tp.set_mode("storages")

        item = _collect_items(tp)[("host", "n1", "h1")]
        menu = _open_menu(qtbot, tp, item, monkeypatch)
        assert "Create storage…" in _menu_actions(menu)
        created = []
        tp.storage_create_requested.connect(lambda h: created.append(h))
        from PySide6.QtGui import QAction as _QA
        for act in menu.actions():
            if not isinstance(act, _QA):
                continue
            if act.text() == "Create storage…":
                act.trigger()
        assert created == ["h1"]

    def test_no_create_storage_on_host_in_hosts_mode(self, qtbot, make_node,
                                                     monkeypatch):
        cfg = [{"name": "h1", "cluster": "", "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)
        node_repo = NodeRepository()
        node_repo.add(make_node(host_name="h1", node="n1"))
        tp.update_data(node_repo.all(), [], [], final=True,
                       node_repo=node_repo, vm_repo=None)

        item = _collect_items(tp)[("host", "n1", "h1")]
        menu = _open_menu(qtbot, tp, item, monkeypatch)
        assert "Create storage…" not in _menu_actions(menu)

    def test_create_storage_on_cluster(self, qtbot, make_node, monkeypatch):
        cfg = [{"name": "h1", "cluster": "cl1", "cluster_rep": True, "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)
        node_repo = NodeRepository()
        node_repo.add(make_node(host_name="h1", node="n1", cluster="cl1",
                                is_cluster=True))
        tp.update_data(node_repo.all(), [], [], final=True,
                       node_repo=node_repo, vm_repo=None)
        tp.set_mode("storages")

        item = _collect_items(tp)[("cluster", "cl1")]
        menu = _open_menu(qtbot, tp, item, monkeypatch)
        created = []
        tp.storage_create_requested.connect(lambda h: created.append(h))
        from PySide6.QtGui import QAction as _QA
        for act in menu.actions():
            if not isinstance(act, _QA):
                continue
            if act.text() == "Create storage…":
                act.trigger()
        assert created == ["h1"]


class TestClusterJoinContextMenu:
    """B12a: "Add node to cluster…" in the cluster context menu."""

    @staticmethod
    def _make_panel(qtbot, make_node):
        cfg = [
            {"name": "rep1", "cluster": "mycluster",
             "cluster_rep": True, "skip": False},
            {"name": "solo", "cluster": "", "skip": False},
        ]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)
        node_repo = NodeRepository()
        node_repo.add(make_node(host_name="rep1", node="n1",
                                cluster="mycluster", is_cluster=True))
        tp.update_data(node_repo.all(), [], final=True,
                       node_repo=node_repo, vm_repo=None)
        return tp

    def test_hosts_mode_has_join_action(self, qtbot, make_node, monkeypatch):
        tp = self._make_panel(qtbot, make_node)
        item = _collect_items(tp)[("cluster", "mycluster")]
        menu = _open_menu(qtbot, tp, item, monkeypatch)
        texts = _menu_actions(menu)
        assert "Add node to cluster…" in texts

        fired = []
        tp.cluster_join_requested.connect(fired.append)
        from PySide6.QtGui import QAction as _QA
        for act in menu.actions():
            if isinstance(act, _QA) and act.text() == "Add node to cluster…":
                act.trigger()
        assert fired == ["mycluster"]

    def test_storages_mode_has_no_join_action(self, qtbot, make_node,
                                              monkeypatch):
        tp = self._make_panel(qtbot, make_node)
        tp.set_mode("storages")
        item = _collect_items(tp)[("cluster", "mycluster")]
        menu = _open_menu(qtbot, tp, item, monkeypatch)
        assert "Add node to cluster…" not in _menu_actions(menu)


class TestClusterCreateContextMenu:
    """B12b: "Create cluster…" on standalone PVE hosts."""

    @staticmethod
    def _make_panel(qtbot, make_node, cfg):
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)
        node_repo = NodeRepository()
        node_repo.add(make_node(host_name="h1", node="n1"))
        tp.update_data(node_repo.all(), [], final=True,
                       node_repo=node_repo, vm_repo=None)
        return tp

    def test_standalone_pve_host_has_create_action(self, qtbot, make_node,
                                                   monkeypatch):
        cfg = [{"name": "h1", "cluster": "", "skip": False}]
        tp = self._make_panel(qtbot, make_node, cfg)
        item = _collect_items(tp)[("host", "n1", "h1")]
        menu = _open_menu(qtbot, tp, item, monkeypatch)
        texts = _menu_actions(menu)
        assert "Create cluster…" in texts

        fired = []
        tp.cluster_create_requested.connect(fired.append)
        from PySide6.QtGui import QAction as _QA
        for act in menu.actions():
            if isinstance(act, _QA) and act.text() == "Create cluster…":
                act.trigger()
        assert fired == ["h1"]

    def test_cluster_member_has_no_create_action(self, qtbot, make_node,
                                                 monkeypatch):
        cfg = [{"name": "h1", "cluster": "cl1", "cluster_rep": True,
                "skip": False}]
        tp = self._make_panel(qtbot, make_node, cfg)
        item = _collect_items(tp)[("host", "n1", "h1")]
        menu = _open_menu(qtbot, tp, item, monkeypatch)
        assert "Create cluster…" not in _menu_actions(menu)

    def test_pbs_host_has_no_create_action(self, qtbot, make_node,
                                           monkeypatch):
        cfg = [{"name": "h1", "cluster": "", "skip": False, "type": "pbs"}]
        tp = self._make_panel(qtbot, make_node, cfg)
        item = _collect_items(tp)[("host", "n1", "h1")]
        menu = _open_menu(qtbot, tp, item, monkeypatch)
        assert "Create cluster…" not in _menu_actions(menu)


class TestCurrentSelection:
    """M2: Selection descriptor of the current item for the action palette."""

    def _make(self, qtbot, make_node, make_vm, vms):
        cfg = [{"name": "h1", "cluster": "", "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)
        node_repo = NodeRepository()
        node_repo.add(make_node(host_name="h1", node="pve01"))
        vm_repo = VmRepository()
        for vm in vms:
            vm_repo.add(vm)
        tp.update_data(node_repo.all(), vm_repo.all(), final=True,
                       node_repo=node_repo, vm_repo=vm_repo)
        tp._build_tree()
        return tp

    def _select(self, tp, key):
        """Select an item by key: VM items carry VM_KEY_ROLE,
        the rest — ITEM_KEY_ROLE."""

        def walk(item):
            for role in (ITEM_KEY_ROLE, VM_KEY_ROLE):
                if item.data(0, role) == key:
                    return item
            for i in range(item.childCount()):
                found = walk(item.child(i))
                if found is not None:
                    return found
            return None

        for i in range(tp.tree.topLevelItemCount()):
            found = walk(tp.tree.topLevelItem(i))
            if found is not None:
                tp.tree.setCurrentItem(found)
                return
        raise AssertionError(f"tree item not found: {key!r}")

    def test_empty_when_nothing_selected(self, qtbot, make_node):

        cfg = [{"name": "h1", "cluster": "", "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)
        assert tp.current_selection().is_empty

    def test_skeleton_host_key_yields_empty_selection(
            self, qtbot, make_node, make_vm):
        """E1 (2026-10-06 audit): the 2-element host key of the initial-load
        skeleton yields no Selection — the palette must not offer host actions
        with an empty host_name (parity with the context menu, which is not
        built on the skeleton)."""
        from virtdeck.ui.tree_panel import ITEM_KEY_ROLE

        vm = make_vm(vmid=100, name="alpha", host_name="h1", node="pve01")
        tp = self._make(qtbot, make_node, make_vm, [vm])
        from PySide6.QtWidgets import QTreeWidgetItem

        skeleton = QTreeWidgetItem(tp.tree)
        skeleton.setText(0, "hv02")
        skeleton.setData(0, ITEM_KEY_ROLE, ("host", "hv02"))
        sel = tp.selection_for_item(skeleton)
        assert sel.is_empty
        # A full 3-element key still resolves.
        real = QTreeWidgetItem(tp.tree)
        real.setText(0, "pve01")
        real.setData(0, ITEM_KEY_ROLE, ("host", "pve01", "h1"))
        sel2 = tp.selection_for_item(real)
        assert not sel2.is_empty
        assert sel2.kind == "host"
        assert sel2.host_name == "h1"
        assert sel2.node == "pve01"

    def test_qemu_vm(self, qtbot, make_node, make_vm):
        from virtdeck.domain.enums import VmType

        vm = make_vm(vmid=100, name="alpha", host_name="h1", node="pve01",
                     vm_type=VmType.QEMU)
        tp = self._make(qtbot, make_node, make_vm, [vm])
        self._select(tp, ("h1", 100, "pve01"))
        sel = tp.current_selection()
        assert sel.kind == "vm"
        assert sel.vmid == 100
        assert sel.host_name == "h1"
        assert sel.node == "pve01"
        assert sel.vm is vm
        assert sel.key == ("h1", 100, "pve01")

    def test_lxc_vm_kind_is_ct(self, qtbot, make_node, make_vm):
        from virtdeck.domain.enums import VmType

        vm = make_vm(vmid=200, name="ct1", host_name="h1", node="pve01",
                     vm_type=VmType.LXC)
        tp = self._make(qtbot, make_node, make_vm, [vm])
        self._select(tp, ("h1", 200, "pve01"))
        assert tp.current_selection().kind == "ct"

    def test_template_kind(self, qtbot, make_node, make_vm):
        vm = make_vm(vmid=300, name="tmpl", host_name="h1", node="pve01",
                     template=True)
        tp = self._make(qtbot, make_node, make_vm, [vm])
        self._select(tp, ("h1", 300, "pve01"))
        assert tp.current_selection().kind == "template"

    def test_host_item(self, qtbot, make_node, make_vm):
        tp = self._make(qtbot, make_node, make_vm, [])
        self._select(tp, ("host", "pve01", "h1"))
        sel = tp.current_selection()
        assert sel.kind == "host"
        assert sel.node == "pve01"
        assert sel.host_name == "h1"

    def test_storage_item_host_owner(self, qtbot, make_node, make_storage):
        cfg = [{"name": "h1", "cluster": "", "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)
        node_repo = NodeRepository()
        node_repo.add(make_node(host_name="h1", node="pve01"))
        storages = [make_storage(host_name="h1", node="pve01", storage="local")]
        tp.update_data(node_repo.all(), [], storages, final=True,
                       node_repo=node_repo, vm_repo=None)
        tp.set_mode("storages")
        self._select(tp, ("storage", "local", "host", "h1"))
        sel = tp.current_selection()
        assert sel.kind == "storage"
        assert sel.host_name == "h1"


class TestVMContextMenuRegistry:
    """M2: the VM context-menu block is built from the action registry."""

    def _make_panel(self, qtbot, make_node, make_vm, vms):
        cfg = [{"name": "h1", "cluster": "", "skip": False}]
        tp = TreePanel(cfg)
        qtbot.addWidget(tp)
        node_repo = NodeRepository()
        node_repo.add(make_node(host_name="h1", node="pve01"))
        vm_repo = VmRepository()
        for vm in vms:
            vm_repo.add(vm)
        tp.update_data(node_repo.all(), vm_repo.all(), final=True,
                       node_repo=node_repo, vm_repo=vm_repo)
        tp._build_tree()
        return tp

    def _menu_for(self, qtbot, tp, item, monkeypatch):
        return _open_menu(qtbot, tp, item, monkeypatch)

    def _vm_item(self, tp, key):
        """VM item via VM_KEY_ROLE (VMs carry no ITEM_KEY_ROLE)."""

        def walk(item):
            if item.data(0, VM_KEY_ROLE) == key:
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
        raise AssertionError(f"vm item not found: {key!r}")

    def _by_text(self, menu):
        from PySide6.QtGui import QAction
        return {a.text(): a for a in menu.actions()
                if isinstance(a, QAction) and a.text()}

    def test_stopped_vm_order_and_enabled(
            self, qtbot, make_node, make_vm, monkeypatch):
        vm = make_vm(vmid=100, name="alpha", host_name="h1", node="pve01",
                     status=VmStatus.STOPPED)
        tp = self._make_panel(qtbot, make_node, make_vm, [vm])
        menu = self._menu_for(qtbot, tp, self._vm_item(tp, ("h1", 100, "pve01")),
                              monkeypatch)
        texts = _menu_actions(menu)
        assert texts[:7] == ["Start", "Shutdown", "Reboot", "Stop",
                             "Reset", "Resume", "Console"]
        by_text = self._by_text(menu)
        assert by_text["Start"].isEnabled()
        for name in ("Shutdown", "Reboot", "Stop", "Reset", "Resume",
                     "Console"):
            assert not by_text[name].isEnabled(), name

    def test_running_vm_enabled_block(
            self, qtbot, make_node, make_vm, monkeypatch):
        vm = make_vm(vmid=100, name="alpha", host_name="h1", node="pve01",
                     status=VmStatus.RUNNING)
        tp = self._make_panel(qtbot, make_node, make_vm, [vm])
        menu = self._menu_for(qtbot, tp, self._vm_item(tp, ("h1", 100, "pve01")),
                              monkeypatch)
        by_text = self._by_text(menu)
        assert not by_text["Start"].isEnabled()
        for name in ("Shutdown", "Reboot", "Stop", "Reset", "Console"):
            assert by_text[name].isEnabled(), name

    def test_template_all_disabled(
            self, qtbot, make_node, make_vm, monkeypatch):
        vm = make_vm(vmid=100, name="tmpl", host_name="h1", node="pve01",
                     template=True)
        tp = self._make_panel(qtbot, make_node, make_vm, [vm])
        menu = self._menu_for(qtbot, tp, self._vm_item(tp, ("h1", 100, "pve01")),
                              monkeypatch)
        by_text = self._by_text(menu)
        for name in ("Start", "Shutdown", "Reboot", "Stop", "Reset",
                     "Resume", "Console"):
            assert not by_text[name].isEnabled(), name

    def test_single_action_triggers_signal(
            self, qtbot, make_node, make_vm, monkeypatch):
        vm = make_vm(vmid=100, name="alpha", host_name="h1", node="pve01",
                     status=VmStatus.STOPPED)
        tp = self._make_panel(qtbot, make_node, make_vm, [vm])
        menu = self._menu_for(qtbot, tp, self._vm_item(tp, ("h1", 100, "pve01")),
                              monkeypatch)
        got = []
        tp.vm_action_requested.connect(
            lambda hn, nd, vid, a: got.append((hn, nd, vid, a)))
        self._by_text(menu)["Start"].trigger()
        assert got == [("h1", "pve01", 100, "start")]

    def test_multi_selection_bulk_block_and_signal(
            self, qtbot, make_node, make_vm, monkeypatch):
        vm1 = make_vm(vmid=100, name="alpha", host_name="h1", node="pve01",
                      status=VmStatus.STOPPED)
        vm2 = make_vm(vmid=101, name="beta", host_name="h1", node="pve01",
                      status=VmStatus.RUNNING)
        tp = self._make_panel(qtbot, make_node, make_vm, [vm1, vm2])
        item100 = self._vm_item(tp, ("h1", 100, "pve01"))
        item101 = self._vm_item(tp, ("h1", 101, "pve01"))
        tp.tree.setCurrentItem(item100)
        item101.setSelected(True)
        menu = self._menu_for(qtbot, tp, item100, monkeypatch)
        texts = _menu_actions(menu)
        assert texts[:4] == ["Start all", "Shutdown all", "Reboot all",
                             "Stop all"]
        got = []
        tp.bulk_vm_action_requested.connect(
            lambda keys, a: got.append((list(keys), a)))
        self._by_text(menu)["Stop all"].trigger()
        assert got == [([("h1", 100, "pve01"), ("h1", 101, "pve01")], "stop")]

    def test_host_menu_from_registry(
            self, qtbot, make_node, make_vm, monkeypatch):
        """M2: host block — Create VM/Delete/Refresh token/Create cluster…"""
        tp = self._make_panel(qtbot, make_node, make_vm, [])
        menu = self._menu_for(qtbot, tp,
                              _collect_items(tp)[("host", "pve01", "h1")],
                              monkeypatch)
        texts = _menu_actions(menu)
        assert texts[0] == "Create VM"
        assert "Delete host" in texts
        assert "Refresh token" in texts
        # standalone non-pbs host → Create cluster… present
        assert "Create cluster…" in texts
        got = []
        tp.vm_create_requested.connect(lambda nn, hn: got.append((nn, hn)))
        self._by_text(menu)["Create VM"].trigger()
        assert got == [("pve01", "h1")]

    def test_vm_menu_includes_tools(
            self, qtbot, make_node, make_vm, monkeypatch):
        """M2: noVNC/Migrate/Clone/HA/Delete VM in the menu, from the registry."""
        vm = make_vm(vmid=100, name="alpha", host_name="h1", node="pve01",
                     status=VmStatus.RUNNING)
        tp = self._make_panel(qtbot, make_node, make_vm, [vm])
        menu = self._menu_for(qtbot, tp,
                              self._vm_item(tp, ("h1", 100, "pve01")),
                              monkeypatch)
        by_text = self._by_text(menu)
        for name in ("noVNC console", "Migrate", "Clone", "Add to HA",
                     "Remove from HA", "Delete VM"):
            assert name in by_text, name
        assert by_text["Migrate"].isEnabled()
        assert not by_text["Start"].isEnabled()
        got = []
        tp.vm_delete_requested.connect(
            lambda hn, nd, vid: got.append((hn, nd, vid)))
        by_text["Delete VM"].trigger()
        assert got == [("h1", "pve01", 100)]
