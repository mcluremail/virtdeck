"""GAP-7 / DELIGHT-8 / R11: the 200-VM park profile.

- _build_tree stays fast at fleet scale (acceptance: ≤ 200 ms on the
  reference machine — CI is not it, so the budget here is generous but
  still catches accidental O(n²));
- identical guest names are distinguishable without opening the detail
  panel (duplicate names get the VMID in the tree row);
- selection by key still works at scale.
"""
from __future__ import annotations

import time

import pytest

from virtdeck.domain.enums import NodeStatus, VmStatus, VmType
from virtdeck.domain.node import Node
from virtdeck.domain.repositories import NodeRepository, VmRepository
from virtdeck.domain.vm import Vm
from virtdeck.ui.tree_panel import TreePanel

G = 1024 ** 3
N_VMS = 200


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


def _park():
    """2 nodes × 100 VMs; 10 names duplicated across the nodes."""
    nr, vr = NodeRepository(), VmRepository()
    nr.add(_node("n1"))
    nr.add(_node("n2"))
    vmid = 100
    for node in ("n1", "n2"):
        for i in range(N_VMS // 2):
            name = f"dup-{i}" if i < 10 else f"{node}-web-{i}"
            vr.add(_vm(vmid, name, node))
            vmid += 1
    return nr, vr


@pytest.fixture
def panel(qtbot):
    cfg = [{"name": "n1", "cluster": "", "skip": False},
           {"name": "n2", "cluster": "", "skip": False}]
    p = TreePanel(cfg)
    qtbot.addWidget(p)
    return p


def test_build_tree_200_vms_within_budget(panel):
    nr, vr = _park()
    start = time.perf_counter()
    panel.update_data(nr.all(), vr.all(), [], final=True, node_repo=nr,
                      vm_repo=vr)
    elapsed = time.perf_counter() - start
    assert panel.tree.topLevelItemCount() >= 2
    # acceptance R11: ≤ 200 ms on the reference machine
    assert elapsed < 0.2, f"_build_tree took {elapsed * 1000:.0f} ms"


def test_duplicate_names_distinguishable(panel):
    nr, vr = _park()
    panel.update_data(nr.all(), vr.all(), [], final=True, node_repo=nr,
                      vm_repo=vr)
    texts = []

    def walk(item):
        texts.append(item.text(0))
        for i in range(item.childCount()):
            walk(item.child(i))

    for i in range(panel.tree.topLevelItemCount()):
        walk(panel.tree.topLevelItem(i))
    # duplicated names carry the VMID
    assert "dup-0 (100)" in texts and "dup-0 (200)" in texts
    # unique names stay clean
    assert "n1-web-50" in texts
    assert not any(t.startswith("n1-web-50 (") for t in texts)


def test_selection_by_key_works_at_scale(panel):
    nr, vr = _park()
    panel.update_data(nr.all(), vr.all(), [], final=True, node_repo=nr,
                      vm_repo=vr)
    key = ("n2", 250, "n2")
    item = panel.find_item_by_key(key)
    assert item is not None
    panel.tree.setCurrentItem(item)
    assert panel.get_current_item_key() == key
