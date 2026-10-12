"""Audit 4.1 regression: refresh lifecycle keeps last known-good data.

The invariant under test: absence of an answer is not the absence of
resources — a failed, rejected or incomplete cycle never wipes confirmed
data from the repositories, the UI or the persistent cache, while a
confirmed full response replaces its host's snapshot entirely.

Workers are faked as QRunnables whose reports are delivered by hand
through on_worker_finished / on_soft_refresh_result — the real
MainWindow lifecycle (pool bookkeeping, generations, finalization,
cache save) is exercised end to end.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QRunnable

from virtdeck.config import load_resources_cache, save_resources_cache
from virtdeck.domain import (
    Node as DomainNode,
)
from virtdeck.domain import (
    Storage as DomainStorage,
)
from virtdeck.domain import (
    Vm as DomainVm,
)

# --- payload helpers ---------------------------------------------------


def _node(name="pve1", status="online"):
    return {"node": name, "status": status, "cpu": 0.1, "mem": 1024**3,
            "maxmem": 2 * 1024**3, "uptime": 100}


def _vm(vmid, node="pve1", status="running", name=None):
    return {"vmid": vmid, "name": name or f"vm-{vmid}", "type": "qemu",
            "node": node, "status": status}


def _st(node="pve1", storage="local"):
    return {"storage": storage, "node": node, "type": "dir",
            "content": "iso,vztmpl", "used": 1, "total": 10}


def _ok(host, nodes, vms=(), storages=()):
    return {"host": host, "status": "ok", "nodes": list(nodes),
            "vms": list(vms), "storages": list(storages),
            "pools": [], "iso_images": {}, "ha_groups": []}


def _err(host, msg="connection refused"):
    return {"host": host, "status": "error", "error": msg}


def _cfg(name):
    return {"name": name, "host": f"10.0.0.{name[-1]}", "user": "u@pam",
            "token_name": "t", "token_value": "s"}


# --- fixtures / fakes ---------------------------------------------------


@pytest.fixture()
def main_window(qtbot, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from virtdeck.ui.mainwindow import MainWindow

    mw = MainWindow()
    qtbot.addWidget(mw)
    yield mw
    mw.close()


def _install_fake_fetch(monkeypatch):
    """Replace FetchWorker with a QRunnable fake that never runs —
    reports are delivered by hand; returns the list of created workers."""
    import virtdeck.ui.mainwindow as mw_mod
    created = []

    class _FakeFetch(QRunnable):
        def __init__(self, cfg):
            super().__init__()
            self.node_cfg = cfg
            self.signals = MagicMock()
            created.append(self)

        def run(self):  # pragma: no cover — reports are simulated
            pass

    monkeypatch.setattr(mw_mod, "FetchWorker", _FakeFetch)
    return created


def _seed(mw, host, node="pve1", vmids=(100,)):
    """A previous known-good snapshot: one node + VMs + one storage."""
    mw._node_repo.add(DomainNode.from_pve(_node(node), host, "", False))
    for vmid in vmids:
        mw._vm_repo.add(DomainVm.from_pve(_vm(vmid, node), host))
    mw._storage_repo.add(DomainStorage.from_pve(_st(node), host, ""))


def _cached_vmids():
    cached, _ = load_resources_cache()
    return {(v["host_name"], v["vmid"]) for v in cached["vms"]}


# --- hard refresh (D3) ---------------------------------------------------


def test_partial_hard_rejection_keeps_unstarted_host(main_window, monkeypatch):
    """Test 6: a host whose worker was rejected by the pool keeps its
    last known-good data through the hard cycle — UI, repos and cache."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    _seed(mw, "h1", node="pve1", vmids=(100,))
    _seed(mw, "h2", node="pve2", vmids=(200,))
    mw.nodes_cfg = [_cfg("h1"), _cfg("h2")]

    from virtdeck.ui.mainwindow import MAX_WORKERS
    for _ in range(MAX_WORKERS - 1):
        mw._workers.add(MagicMock())

    mw.refresh_data()

    assert len(created) == 2
    assert created[0] in mw._workers      # h1 started
    assert created[1] not in mw._workers  # h2 rejected by the pool
    gen = mw._refresh.hard_gen

    mw.on_worker_finished(
        _ok("h1", nodes=[_node("pve1")], vms=[_vm(101, "pve1")],
            storages=[_st("pve1")]),
        created[0], gen)

    # h1's confirmed snapshot replaced the old one entirely
    assert mw._vm_repo.get("h1", 101) is not None
    assert mw._vm_repo.get("h1", 100) is None
    # h2 never reported: its previous data survived the cycle
    assert mw._vm_repo.get("h2", 200) is not None
    node_h2 = mw._node_repo.get("h2", "pve2")
    assert node_h2 is not None and node_h2.status_value == "online"
    assert ("h2", 200) in _cached_vmids()


def test_full_hard_rejection_restores_ui(main_window, monkeypatch):
    """Test 7: when the pool rejects every worker the UI must leave the
    loading state immediately instead of waiting forever, and the
    previous snapshot must stay untouched."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    _seed(mw, "h1", node="pve1", vmids=(100,))
    mw.nodes_cfg = [_cfg("h1")]

    from virtdeck.ui.mainwindow import MAX_WORKERS
    for _ in range(MAX_WORKERS):
        mw._workers.add(MagicMock())

    mw.refresh_data()

    assert len(created) == 1
    assert created[0] not in mw._workers
    assert mw._refresh.hard_pending_count == 0
    # Out of the loading state (no per-host loading stubs left)
    assert "h1" not in mw.tree_panel._loading_hosts
    # Previous snapshot untouched
    assert mw._vm_repo.get("h1", 100) is not None


def test_hard_error_keeps_previous_host_data(main_window, monkeypatch):
    """A hard worker reporting an error keeps the host's last known-good
    VMs/storages and only flags its node with the error."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    _seed(mw, "h1", node="pve1", vmids=(100,))
    mw.nodes_cfg = [_cfg("h1")]

    mw.refresh_data()
    gen = mw._refresh.hard_gen
    mw.on_worker_finished(_err("h1"), created[0], gen)

    node_h1 = mw._node_repo.get("h1", "pve1")
    assert node_h1.status_value == "error"
    assert mw._vm_repo.get("h1", 100) is not None
    assert ("h1", 100) in _cached_vmids()


def test_hard_timeout_leaves_loading_state(main_window, monkeypatch):
    """D3: a hung hard cycle is force-finalized by the watchdog — the UI
    leaves the loading state, and a late report of the same generation
    still applies per-host."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    _seed(mw, "h1", node="pve1", vmids=(100,))
    mw.nodes_cfg = [_cfg("h1")]

    mw.refresh_data()
    gen = mw._refresh.hard_gen
    assert mw._refresh.hard_pending_count == 1

    # Simulate the ceiling being long past
    mw._refresh._hard_start = time.monotonic() - (mw._refresh.hard_timeout + 1)
    mw.last_refresh_ts = time.time()  # keep the soft cycle off (interval)
    mw.soft_refresh()

    assert mw._refresh.hard_pending_count == 0
    assert "h1" not in mw.tree_panel._loading_hosts

    # The hung worker's late report still applies (same generation)
    mw.on_worker_finished(
        _ok("h1", nodes=[_node("pve1")], vms=[_vm(101, "pve1")],
            storages=[_st("pve1")]),
        created[0], gen)
    assert mw._vm_repo.get("h1", 101) is not None


def test_stale_generation_does_not_overwrite_new_state(main_window, monkeypatch):
    """Test 10: a late report of the previous refresh generation must not
    apply and must not block or finalize the new generation."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    _seed(mw, "h1", node="pve1", vmids=(100,))
    mw.nodes_cfg = [_cfg("h1")]

    mw.refresh_data()           # generation A
    gen_a = mw._refresh.hard_gen
    mw.refresh_data()           # generation B — A's reports are stale now
    gen_b = mw._refresh.hard_gen
    assert gen_b > gen_a

    mw.on_worker_finished(
        _ok("h1", nodes=[_node("pve1")], vms=[_vm(555)], storages=[_st("pve1")]),
        created[0], gen_a)

    assert mw._vm_repo.get("h1", 555) is None    # stale data not applied
    assert mw._refresh.hard_pending_count == 1   # gen B still awaits

    mw.on_worker_finished(
        _ok("h1", nodes=[_node("pve1")], vms=[_vm(100)], storages=[_st("pve1")]),
        created[1], gen_b)

    assert mw._vm_repo.get("h1", 100) is not None
    assert mw._refresh.hard_pending_count == 0


def test_recovery_replaces_snapshot_and_removes_gone_resources(
        main_window, monkeypatch):
    """Test 11: after connectivity is restored the confirmed response
    replaces the host snapshot entirely — including removing resources
    that really disappeared on the server."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    mw.nodes_cfg = [_cfg("h1")]

    mw.refresh_data()
    gen1 = mw._refresh.hard_gen
    mw.on_worker_finished(
        _ok("h1", nodes=[_node("pve1")], vms=[_vm(100), _vm(101)],
            storages=[_st("pve1")]),
        created[0], gen1)
    assert mw._vm_repo.get("h1", 100) is not None

    # Next cycle: VM 100 disappeared on the server
    mw.refresh_data()
    gen2 = mw._refresh.hard_gen
    mw.on_worker_finished(
        _ok("h1", nodes=[_node("pve1")], vms=[_vm(101)], storages=[_st("pve1")]),
        created[1], gen2)

    assert mw._vm_repo.get("h1", 100) is None
    assert mw._vm_repo.get("h1", 101) is not None
    assert ("h1", 100) not in _cached_vmids()
    assert ("h1", 101) in _cached_vmids()


# --- soft refresh (D1) ---------------------------------------------------


def test_soft_partial_failure_keeps_failed_host(main_window, monkeypatch):
    """Test 4: a soft cycle where one host fails — the failed host keeps
    its last known-good data (repos + cache) with its node flagged, while
    the successful host's snapshot is replaced entirely."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    _seed(mw, "h1", node="pve1", vmids=(100,))
    _seed(mw, "h2", node="pve2", vmids=(200,))
    mw.nodes_cfg = [_cfg("h1"), _cfg("h2")]
    mw.last_refresh_ts = 0.0

    mw.soft_refresh()
    gen = mw._refresh.soft_gen

    mw.on_soft_refresh_result(
        _ok("h1", nodes=[_node("pve1")], vms=[_vm(101, "pve1")],
            storages=[_st("pve1")]),
        created[0], gen)
    mw.on_soft_refresh_result(_err("h2"), created[1], gen)

    # h1: confirmed snapshot replaced entirely
    assert mw._vm_repo.get("h1", 101) is not None
    assert mw._vm_repo.get("h1", 100) is None
    # h2: failed host kept its data, node flagged with the error
    assert mw._vm_repo.get("h2", 200) is not None
    assert mw._node_repo.get("h2", "pve2").status_value == "error"
    # Cache holds the merged best-known state, not the failed cycle
    vmids = _cached_vmids()
    assert ("h1", 101) in vmids
    assert ("h2", 200) in vmids
    assert mw._soft_had_errors is True


def test_soft_full_failure_keeps_snapshot(main_window, monkeypatch):
    """Test 5: a soft cycle where every host fails must not wipe the
    previous snapshot — data stays, nodes are flagged, cache intact."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    _seed(mw, "h1", node="pve1", vmids=(100,))
    _seed(mw, "h2", node="pve2", vmids=(200,))
    mw.nodes_cfg = [_cfg("h1"), _cfg("h2")]
    mw.last_refresh_ts = 0.0

    mw.soft_refresh()
    gen = mw._refresh.soft_gen
    mw.on_soft_refresh_result(_err("h1"), created[0], gen)
    mw.on_soft_refresh_result(_err("h2"), created[1], gen)

    assert mw._vm_repo.get("h1", 100) is not None
    assert mw._vm_repo.get("h2", 200) is not None
    assert mw._node_repo.get("h1", "pve1").status_value == "error"
    assert mw._node_repo.get("h2", "pve2").status_value == "error"
    vmids = _cached_vmids()
    assert ("h1", 100) in vmids
    assert ("h2", 200) in vmids


def test_soft_recovery_after_failures(main_window, monkeypatch):
    """After several failed soft cycles a successful one restores the
    data: the snapshot is replaced, ERROR flags are cleared."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    _seed(mw, "h1", node="pve1", vmids=(100,))
    mw.nodes_cfg = [_cfg("h1")]

    for _ in range(2):  # two failed cycles
        mw.last_refresh_ts = 0.0
        mw.soft_refresh()
        gen = mw._refresh.soft_gen
        mw.on_soft_refresh_result(_err("h1"), created[-1], gen)
        assert mw._node_repo.get("h1", "pve1").status_value == "error"

    # Recovery: the host answers again with VM 101 (100 is gone)
    mw.last_refresh_ts = 0.0
    mw.soft_refresh()
    gen = mw._refresh.soft_gen
    mw.on_soft_refresh_result(
        _ok("h1", nodes=[_node("pve1")], vms=[_vm(101, "pve1")],
            storages=[_st("pve1")]),
        created[-1], gen)

    assert mw._node_repo.get("h1", "pve1").status_value == "online"
    assert mw._vm_repo.get("h1", 101) is not None
    assert mw._vm_repo.get("h1", 100) is None
    assert ("h1", 101) in _cached_vmids()


# --- cache vs config at startup (D5) -------------------------------------


def _cached_node(host, node):
    return {"node": node, "status": "online", "host_name": host,
            "_is_cluster": False}


def test_cache_does_not_restore_removed_host(qtbot, monkeypatch, tmp_path):
    """Test 9a: a host removed from the configuration must not resurrect
    from the cache at startup."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    save_resources_cache(
        nodes=[_cached_node("h1", "pve1"), _cached_node("h2", "pve2"),
               _cached_node("h3", "pve3")],
        vms=[{"vmid": 300, "name": "gone", "type": "qemu", "node": "pve3",
              "status": "running", "host_name": "h3"}],
        storages=[])
    _install_fake_fetch(monkeypatch)
    from virtdeck.ui.mainwindow import MainWindow

    mw = MainWindow(nodes_cfg=[_cfg("h1"), _cfg("h2")])
    qtbot.addWidget(mw)
    try:
        assert mw._node_repo.get("h1", "pve1") is not None
        assert mw._node_repo.get("h2", "pve2") is not None
        assert mw._node_repo.get("h3", "pve3") is None
        assert mw._vm_repo.get("h3", 300) is None
    finally:
        mw.close()


def test_cache_does_not_restore_skipped_host(qtbot, monkeypatch, tmp_path):
    """Test 9b: a host excluded by skip must not be restored from the
    cache at startup."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    save_resources_cache(
        nodes=[_cached_node("h1", "pve1"), _cached_node("h2", "pve2"),
               _cached_node("h3", "pve3")],
        vms=[{"vmid": 300, "name": "hidden", "type": "qemu", "node": "pve3",
              "status": "running", "host_name": "h3"}],
        storages=[])
    _install_fake_fetch(monkeypatch)
    from virtdeck.ui.mainwindow import MainWindow

    skipped = {**_cfg("h3"), "skip": True}
    mw = MainWindow(nodes_cfg=[_cfg("h1"), _cfg("h2"), skipped])
    qtbot.addWidget(mw)
    try:
        assert mw._node_repo.get("h1", "pve1") is not None
        assert mw._node_repo.get("h2", "pve2") is not None
        assert mw._node_repo.get("h3", "pve3") is None
        assert mw._vm_repo.get("h3", 300) is None
    finally:
        mw.close()


def test_cache_keeps_cluster_nodes_despite_name_difference(
        qtbot, monkeypatch, tmp_path):
    """Test 9c: for a cluster representative the cache is keyed by the
    config name; PVE node names inside must not be filtered out."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cluster_node = dict(_cached_node("cl1", "pve1"), _is_cluster=True)
    cluster_node2 = dict(_cached_node("cl1", "pve2"), _is_cluster=True)
    save_resources_cache(
        nodes=[cluster_node, cluster_node2],
        vms=[{"vmid": 10, "name": "web", "type": "qemu", "node": "pve1",
              "status": "running", "host_name": "cl1"}],
        storages=[])
    _install_fake_fetch(monkeypatch)
    from virtdeck.ui.mainwindow import MainWindow

    cfg = {"name": "cl1", "host": "10.0.0.9", "user": "u@pam",
           "token_name": "t", "token_value": "s",
           "cluster_rep": True, "cluster": "cl1"}
    mw = MainWindow(nodes_cfg=[cfg])
    qtbot.addWidget(mw)
    try:
        # PVE node names differ from the config name — still restored
        assert mw._node_repo.get("cl1", "pve1") is not None
        assert mw._node_repo.get("cl1", "pve2") is not None
        assert mw._vm_repo.get("cl1", 10) is not None
    finally:
        mw.close()
