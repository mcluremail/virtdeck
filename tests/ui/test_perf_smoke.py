"""M0.4: perf-smoke — coarse thresholds, catching order-of-magnitude regressions.

Absolute thresholds are deliberately generous (offscreen CI runner with
no fixed hardware): see docs/PERF_BASELINE.md for local baselines
(scripts/perf_session.py, nightly on a reference machine).
"""

import time

import pytest

from virtdeck.domain.enums import NodeStatus, VmStatus, VmType
from virtdeck.domain.node import Node
from virtdeck.domain.repositories import NodeRepository, VmRepository
from virtdeck.domain.vm import Vm
from virtdeck.ui.tree_panel import TreePanel


def _make_data(hosts, vms_per_host):
    node_repo = NodeRepository()
    vm_repo = VmRepository()
    cfgs = []
    for h in range(hosts):
        host = f"h{h}"
        cfgs.append({"name": host, "cluster": "", "skip": False})
        node_repo.add(Node(
            host_name=host, node=f"n{h}", cluster="",
            status=NodeStatus.ONLINE, error="",
            cpu_fraction=0.4, cpu_sockets=2,
            mem_bytes=8 * 1024**3, maxmem_bytes=16 * 1024**3,
            disk_bytes=0, maxdisk_bytes=0, uptime_seconds=3600,
            pve_version_raw="pve-manager/8.2.4/abc", kernel_version="6.8.12",
            qemu_version="9.0.0", lxc_version="6.0.0", is_cluster=False,
        ))
        for k in range(vms_per_host):
            vm_repo.add(Vm(
                vmid=100 + k, name=f"vm-{h}-{k}", vm_type=VmType.QEMU,
                node=f"n{h}", host_name=host, pool="", status=VmStatus.RUNNING,
                hastate="", tags="", template=False,
                cpu_fraction=0.3, mem_bytes=2 * 1024**3,
                maxmem_bytes=4 * 1024**3, disk_bytes=0, maxdisk_bytes=0,
                netin_bytes=0, netout_bytes=0, diskread_bytes=0,
                diskwrite_bytes=0, uptime_seconds=600,
            ))
    return cfgs, node_repo, vm_repo


def _rebuild_ms(tp, node_repo, vm_repo):
    t0 = time.perf_counter()
    tp.update_data(node_repo.all(), vm_repo.all(), final=True,
                   node_repo=node_repo, vm_repo=vm_repo)
    return (time.perf_counter() - t0) * 1000.0


@pytest.mark.parametrize(
    ("hosts", "vms_per_host", "limit_ms"),
    [(1, 100, 1000.0), (10, 100, 5000.0)],
)
def test_tree_rebuild_smoke(qtbot, hosts, vms_per_host, limit_ms):
    """Tree rebuild fits the generous smoke threshold.

    Local baseline: 100 items ~60 ms, 1000 ~430 ms (2026-09).
    """
    cfgs, node_repo, vm_repo = _make_data(hosts, vms_per_host)
    tp = TreePanel(cfgs)
    qtbot.addWidget(tp)
    tp.update_data(node_repo.all(), vm_repo.all(), final=True,
                   node_repo=node_repo, vm_repo=vm_repo)
    ms = _rebuild_ms(tp, node_repo, vm_repo)
    assert ms < limit_ms, (
        f"rebuild {hosts * vms_per_host} items: {ms:.0f} ms "
        f"> smoke threshold {limit_ms:.0f} ms — order-of-magnitude regression?"
    )
