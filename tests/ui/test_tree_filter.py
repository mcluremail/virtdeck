"""GAP-7 (product part): the live tree filter — "find a VM in a big park".

Matching: display name, VMID, node/host names (from the item roles) and
the info line, case-insensitive; parents of matches stay visible as
containers. Esc clears, Ctrl+F focuses, rebuilds honor an active filter,
and reveal_key() clears it so the jump target is actually visible.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence

from virtdeck.domain.enums import NodeStatus, VmStatus, VmType
from virtdeck.domain.node import Node
from virtdeck.domain.repositories import NodeRepository, VmRepository
from virtdeck.domain.vm import Vm
from virtdeck.ui.tree_panel import TreePanel

G = 1024 ** 3


def _node(name):
    return Node(host_name=name, node=name, cluster="",
                status=NodeStatus.ONLINE,
                error="", cpu_fraction=0.3, cpu_sockets=2, mem_bytes=2 * G,
                maxmem_bytes=8 * G, disk_bytes=10 * G, maxdisk_bytes=100 * G,
                uptime_seconds=1, pve_version_raw="8.0", kernel_version="k",
                qemu_version="q", lxc_version="l", is_cluster=False,
                conn_id=name)


def _vm(vmid, name, node):
    return Vm(vmid=vmid, name=name, vm_type=VmType.QEMU, node=node,
              host_name=node, pool="", status=VmStatus.RUNNING,
              hastate="", tags="", template=False, cpu_fraction=0.1,
              mem_bytes=G, maxmem_bytes=2 * G, disk_bytes=0,
              maxdisk_bytes=0, uptime_seconds=1, netin_bytes=0,
              netout_bytes=0, diskread_bytes=0, diskwrite_bytes=0,
              conn_id=node)


@pytest.fixture
def panel(qtbot):
    cfg = [{"name": "n1", "cluster": "", "skip": False},
           {"name": "n2", "cluster": "", "skip": False}]
    p = TreePanel(cfg)
    qtbot.addWidget(p)
    nr, vr = NodeRepository(), VmRepository()
    nr.add(_node("n1"))
    nr.add(_node("n2"))
    # n1: web-1..web-5 (vmid 100..104); n2: db-1..db-5 (vmid 200..204)
    vmid = 100
    for node, prefix in (("n1", "web"), ("n2", "db")):
        for i in range(1, 6):
            vr.add(_vm(vmid, f"{prefix}-{i}", node))
            vmid += 1
    p.update_data(nr.all(), vr.all(), [], final=True, node_repo=nr,
                  vm_repo=vr)
    return p


def _visible_texts(panel):
    texts = []

    def walk(item):
        if not item.isHidden():
            texts.append(item.text(0))
        for i in range(item.childCount()):
            walk(item.child(i))

    for i in range(panel.tree.topLevelItemCount()):
        walk(panel.tree.topLevelItem(i))
    return texts


def test_filter_hides_non_matching_guests(panel):
    panel._filter_edit.setText("web-3")
    texts = _visible_texts(panel)
    assert "web-3" in texts
    assert not any(t.startswith("db-") for t in texts)
    assert not any(t == "web-2" for t in texts)
    # containers of the match stay visible
    assert any(t.startswith("n1") for t in texts)


def test_filter_matches_vmid(panel):
    panel._filter_edit.setText("104")       # web-5's VMID
    texts = _visible_texts(panel)
    assert "web-5" in texts
    assert "db-5" not in texts              # vmid 204 does not contain 104


def test_filter_matches_node_name_via_guests(panel):
    panel._filter_edit.setText("n2")
    texts = _visible_texts(panel)
    assert any(t.startswith("n2") for t in texts)
    assert "db-1" in texts                  # guests match through their node
    assert "web-1" not in texts
    assert not any(t.startswith("n1") for t in texts)  # no match on this branch


def test_filter_is_case_insensitive(panel):
    panel._filter_edit.setText("WEB-3")
    assert "web-3" in _visible_texts(panel)


def test_empty_filter_shows_everything(panel):
    panel._filter_edit.setText("web-3")
    panel._filter_edit.clear()
    texts = _visible_texts(panel)
    assert "web-3" in texts and "db-5" in texts
    assert any(t.startswith("n1") for t in texts)


def test_clear_restores_expansion(panel):
    """The expandAll() used while filtering must not leak into the
    pre-filter expansion state."""
    panel.tree.collapseAll()
    panel.tree.topLevelItem(0).setExpanded(True)   # only n1 expanded
    panel._filter_edit.setText("web-3")
    assert panel.tree.topLevelItem(1).isExpanded()  # expandAll while filtering
    panel._filter_edit.clear()
    assert panel.tree.topLevelItem(0).isExpanded()
    assert not panel.tree.topLevelItem(1).isExpanded()


def test_no_matches_hides_everything(panel):
    panel._filter_edit.setText("no-such-vm")
    assert _visible_texts(panel) == []


def test_rebuild_honors_active_filter(panel, qtbot):
    panel._filter_edit.setText("db-2")
    nr, vr = NodeRepository(), VmRepository()
    nr.add(_node("n1"))
    nr.add(_node("n2"))
    vmid = 100
    for node, prefix in (("n1", "web"), ("n2", "db")):
        for i in range(1, 6):
            vr.add(_vm(vmid, f"{prefix}-{i}", node))
            vmid += 1
    panel.update_data(nr.all(), vr.all(), [], final=True, node_repo=nr,
                      vm_repo=vr)
    assert panel._filter_edit.text() == "db-2"
    texts = _visible_texts(panel)
    assert "db-2" in texts
    assert "web-2" not in texts


def test_esc_clears_and_returns_to_tree(panel, qtbot):
    panel.show()
    panel._filter_edit.setText("web-3")
    panel._filter_edit.setFocus()
    qtbot.keyPress(panel._filter_edit, Qt.Key_Escape)
    assert panel._filter_edit.text() == ""
    assert "db-5" in _visible_texts(panel)


def test_ctrl_f_shortcut_focuses_filter(panel, qtbot, monkeypatch):
    """Ctrl+F (QKeySequence.Find) is wired to the filter focus; the
    offscreen platform cannot activate windows, so the wiring — not the
    platform focus — is what's asserted here."""
    calls = []
    monkeypatch.setattr(panel, "_focus_filter", lambda: calls.append(1))
    assert panel._filter_shortcut.key() == QKeySequence.Find
    assert panel._filter_shortcut.context() == Qt.ShortcutContext.WidgetWithChildrenShortcut
    panel._filter_shortcut.activated.emit()
    assert calls == [1]


def test_reveal_key_clears_the_filter(panel):
    panel._filter_edit.setText("web-3")
    panel.reveal_key(("host", "n1", "n1"))
    assert panel._filter_edit.text() == ""
    assert "db-5" in _visible_texts(panel)


def test_filter_is_fast_at_park_scale(panel):
    """200+ items: the per-keystroke walk stays trivially cheap."""
    import time

    nr, vr = NodeRepository(), VmRepository()
    nr.add(_node("n1"))
    nr.add(_node("n2"))
    vmid = 100
    for node in ("n1", "n2"):
        for i in range(100):
            vr.add(_vm(vmid, f"{node}-web-{i}", node))
            vmid += 1
    panel.update_data(nr.all(), vr.all(), [], final=True, node_repo=nr,
                      vm_repo=vr)
    start = time.perf_counter()
    panel._filter_edit.setText("n1-web-9")
    elapsed = time.perf_counter() - start
    assert elapsed < 0.1, f"filter took {elapsed * 1000:.0f} ms"
    visible = _visible_texts(panel)
    assert sum(t.startswith("n1-web-9") for t in visible) == 11  # 9, 90..99
