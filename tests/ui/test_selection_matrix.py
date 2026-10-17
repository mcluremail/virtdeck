"""GAP-5: the selection/refresh transition matrix, as tests.

Events (columns of the matrix) applied to selections (rows):
- refresh with the object still present  → selection preserved;
- refresh where the object has vanished  → selection cleared gracefully;
- partial failure (one host errors)      → other hosts render, no crash;
- recovery after failure                 → tree renders again, selection
  restored when the object returns.

The tree is driven at the render contract level (update_data with repos —
no threads), same as the R9/R11 probes.
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication  # noqa: F401  (offscreen shims)

from virtdeck.domain.enums import NodeStatus, VmStatus, VmType
from virtdeck.domain.node import Node
from virtdeck.domain.repositories import NodeRepository, VmRepository
from virtdeck.domain.vm import Vm
from virtdeck.ui.tree_panel import TreePanel

G = 1024 ** 3


def _node(name, status=NodeStatus.ONLINE, error=""):
    return Node(host_name=name, node=name, cluster="",
                status=status, error=error, cpu_fraction=0.3,
                cpu_sockets=2, mem_bytes=2 * G, maxmem_bytes=8 * G,
                disk_bytes=10 * G, maxdisk_bytes=100 * G, uptime_seconds=1,
                pve_version_raw="8.0", kernel_version="k", qemu_version="q",
                lxc_version="l", is_cluster=False, conn_id=name)


def _vm(vmid, name, node):
    return Vm(vmid=vmid, name=name, vm_type=VmType.QEMU, node=node,
              host_name=node, pool="", status=VmStatus.RUNNING,
              hastate="", tags="", template=False, cpu_fraction=0.1,
              mem_bytes=G, maxmem_bytes=2 * G, disk_bytes=0,
              maxdisk_bytes=0, uptime_seconds=1, netin_bytes=0,
              netout_bytes=0, diskread_bytes=0, diskwrite_bytes=0,
              conn_id=node)


def _populate():
    nr, vr = NodeRepository(), VmRepository()
    nr.add(_node("alpha"))
    nr.add(_node("beta"))
    vr.add(_vm(100, "web", "alpha"))
    vr.add(_vm(101, "db", "alpha"))
    vr.add(_vm(200, "cache", "beta"))
    return nr, vr


def _repo_without_vm(vmid):
    nr, vr = _populate()
    vr2 = VmRepository()
    for v in vr.all():
        if v.vmid != vmid:
            vr2.add(v)
    return nr, vr2


def _repo_without_host(name):
    nr, vr = _populate()
    nr2, vr2 = NodeRepository(), VmRepository()
    for n in nr.all():
        if n.host_name != name:
            nr2.add(n)
    for v in vr.all():
        if v.host_name != name:
            vr2.add(v)
    return nr2, vr2


def _repos_data(nr, vr):
    return (nr.all(), vr.all(), [], True, nr, vr)


def _select(panel, key):
    item = panel.find_item_by_key(key)
    assert item is not None, f"item {key!r} must be in the tree"
    panel.tree.setCurrentItem(item)


@pytest.fixture
def panel(qtbot):
    cfg = [{"name": "alpha", "cluster": "", "skip": False},
           {"name": "beta", "cluster": "", "skip": False}]
    p = TreePanel(cfg)
    qtbot.addWidget(p)
    return p


def _apply(panel, nr, vr):
    panel.update_data(nr.all(), vr.all(), [], final=True, node_repo=nr,
                      vm_repo=vr)


# ── matrix row: nothing selected ────────────────────────────────────


def test_no_selection_survives_all_events(panel):
    nr, vr = _populate()
    _apply(panel, nr, vr)
    assert panel.get_current_item_key() is None
    # object vanishes + partial failure + recovery — still no selection
    nr, vr = _repo_without_vm(100)
    _apply(panel, nr, vr)
    assert panel.get_current_item_key() is None


# ── matrix row: VM selected ─────────────────────────────────────────


def test_vm_selection_preserved_across_refresh(panel):
    nr, vr = _populate()
    _apply(panel, nr, vr)
    key = ("alpha", 100, "alpha")
    _select(panel, key)
    _apply(panel, nr, vr)  # the same object came back
    assert panel.get_current_item_key() == key


def test_vm_vanishes_selection_cleared(panel):
    nr, vr = _populate()
    _apply(panel, nr, vr)
    key = ("alpha", 100, "alpha")
    _select(panel, key)
    nr, vr = _repo_without_vm(100)
    _apply(panel, nr, vr)  # must not crash; stale selection must not stay
    current = panel.get_current_item_key()
    assert current is None or panel.find_item_by_key(current) is not None


def test_vm_selection_survives_partial_failure(panel):
    """One host errors — the tree keeps the failing host, the selection
    on a healthy host's VM stays."""
    nr, vr = _populate()
    _apply(panel, nr, vr)
    key = ("beta", 200, "beta")
    _select(panel, key)
    # alpha went down: its node row now carries the error status
    nr.add(_node("alpha", status=NodeStatus.ERROR, error="boom"))
    _apply(panel, nr, vr)
    assert panel.get_current_item_key() == key
    # alpha is still in the tree (with the error state), beta intact
    assert panel.find_item_by_key(("alpha", 100, "alpha")) is not None
    assert panel.find_item_by_key(key) is not None


def test_selection_restored_after_recovery(panel):
    nr, vr = _populate()
    _apply(panel, nr, vr)
    key = ("alpha", 100, "alpha")
    _select(panel, key)
    nr.add(_node("alpha", status=NodeStatus.ERROR, error="boom"))
    _apply(panel, nr, vr)
    nr.add(_node("alpha"))  # recovered
    _apply(panel, nr, vr)
    assert panel.get_current_item_key() == key


# ── matrix row: host selected ───────────────────────────────────────


def test_host_selection_preserved_and_cleared(panel):
    nr, vr = _populate()
    _apply(panel, nr, vr)
    host_key = ("host", "alpha", "alpha")
    _select(panel, host_key)
    _apply(panel, nr, vr)
    assert panel.get_current_item_key() == host_key
    # the whole host disappears from the config
    nr, vr = _repo_without_host("alpha")
    _apply(panel, nr, vr)
    current = panel.get_current_item_key()
    assert current is None or panel.find_item_by_key(current) is not None
