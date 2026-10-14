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
    HaGroup as DomainHaGroup,
)
from virtdeck.domain import (
    Node as DomainNode,
)
from virtdeck.domain import (
    Pool as DomainPool,
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


def _ok(host, nodes, vms=(), storages=(), pools=()):
    return {"host": host, "status": "ok", "nodes": list(nodes),
            "vms": list(vms), "storages": list(storages),
            "pools": list(pools), "iso_images": {}, "ha_groups": []}


def _err(host, msg="connection refused"):
    return {"host": host, "status": "error", "error": msg}


def _cfg(name):
    # deterministic conn_id: seeded repo rows reference the same identity
    return {"name": name, "host": f"10.0.0.{name[-1]}", "user": "u@pam",
            "token_name": "t", "token_value": "s",
            "conn_id": f"id-{name}"}


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
    mw._node_repo.add(DomainNode.from_pve(
        dict(_node(node), conn_id=f"id-{host}"), host, "", False))
    for vmid in vmids:
        mw._vm_repo.add(DomainVm.from_pve(
            dict(_vm(vmid, node), conn_id=f"id-{host}"), host))
    mw._storage_repo.add(DomainStorage.from_pve(
        dict(_st(node), conn_id=f"id-{host}"), host, ""))


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


def _cached_node(host, node, conn_id=""):
    row = {"node": node, "status": "online", "host_name": host,
           "_is_cluster": False}
    # Stage 5.1.2: cache rows carry the producing connection's conn_id.
    if conn_id:
        row["conn_id"] = conn_id
    return row


def test_cache_does_not_restore_removed_host(qtbot, monkeypatch, tmp_path):
    """Test 9a: a host removed from the configuration must not resurrect
    from the cache at startup (its conn_id is no longer in the config)."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfgs = [_cfg("h1"), _cfg("h2")]
    cfgs[0]["conn_id"] = "id-h1"
    cfgs[1]["conn_id"] = "id-h2"
    save_resources_cache(
        nodes=[_cached_node("h1", "pve1", "id-h1"),
               _cached_node("h2", "pve2", "id-h2"),
               # the removed host's rows keep their (no longer known) id
               _cached_node("h3", "pve3", "id-h3-removed")],
        vms=[{"vmid": 300, "name": "gone", "type": "qemu", "node": "pve3",
              "status": "running", "host_name": "h3",
              "conn_id": "id-h3-removed"}],
        storages=[])
    _install_fake_fetch(monkeypatch)
    from virtdeck.ui.mainwindow import MainWindow

    mw = MainWindow(nodes_cfg=cfgs)
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
    cfgs = [_cfg("h1"), _cfg("h2")]
    cfgs[0]["conn_id"] = "id-h1"
    cfgs[1]["conn_id"] = "id-h2"
    save_resources_cache(
        nodes=[_cached_node("h1", "pve1", "id-h1"),
               _cached_node("h2", "pve2", "id-h2"),
               _cached_node("h3", "pve3", "id-h3")],
        vms=[{"vmid": 300, "name": "hidden", "type": "qemu", "node": "pve3",
              "status": "running", "host_name": "h3", "conn_id": "id-h3"}],
        storages=[])
    _install_fake_fetch(monkeypatch)
    from virtdeck.ui.mainwindow import MainWindow

    skipped = {**_cfg("h3"), "skip": True, "conn_id": "id-h3"}
    mw = MainWindow(nodes_cfg=[*cfgs, skipped])
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
    cluster_node = dict(_cached_node("cl1", "pve1", "id-cl1"), _is_cluster=True)
    cluster_node2 = dict(_cached_node("cl1", "pve2", "id-cl1"), _is_cluster=True)
    save_resources_cache(
        nodes=[cluster_node, cluster_node2],
        vms=[{"vmid": 10, "name": "web", "type": "qemu", "node": "pve1",
              "status": "running", "host_name": "cl1",
              "conn_id": "id-cl1"}],
        storages=[])
    _install_fake_fetch(monkeypatch)
    from virtdeck.ui.mainwindow import MainWindow

    cfg = {"name": "cl1", "host": "10.0.0.9", "user": "u@pam",
           "token_name": "t", "token_value": "s",
           "cluster_rep": True, "cluster": "cl1", "conn_id": "id-cl1"}
    mw = MainWindow(nodes_cfg=[cfg])
    qtbot.addWidget(mw)
    try:
        # PVE node names differ from the config name — still restored
        assert mw._node_repo.get("cl1", "pve1") is not None
        assert mw._node_repo.get("cl1", "pve2") is not None
        assert mw._vm_repo.get("cl1", 10) is not None
    finally:
        mw.close()


# --- Audit 4.2 / D1: late answers and cycle competition ------------------


def test_late_hard_answer_after_soft_does_not_overwrite(
        main_window, monkeypatch):
    """D1, the audit scenario: cycle A hangs, the watchdog closes it, a
    soft cycle applies a fresher snapshot — the delayed answer of cycle A
    must not overwrite it, neither in the repos nor in the cache."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    mw.nodes_cfg = [_cfg("h1")]

    mw.refresh_data()
    gen_a = mw._refresh.hard_gen
    epoch_a = mw._refresh.epoch

    # Watchdog closes cycle A; a soft cycle applies fresh data
    mw._refresh._hard_start = time.monotonic() - (mw._refresh.hard_timeout + 1)
    mw.last_refresh_ts = 0.0
    mw.soft_refresh()
    soft_gen = mw._refresh.soft_gen
    epoch_soft = mw._refresh.epoch
    mw.on_soft_refresh_result(
        _ok("h1", nodes=[_node("pve1")], vms=[_vm(300, "pve1")],
            storages=[_st("pve1")]),
        created[-1], soft_gen, epoch_soft)
    assert mw._vm_repo.get("h1", 300) is not None

    # The delayed answer of cycle A arrives with old content
    mw.on_worker_finished(
        _ok("h1", nodes=[_node("pve1")], vms=[_vm(555, "pve1")],
            storages=[_st("pve1")]),
        created[0], gen_a, epoch_a)

    assert mw._vm_repo.get("h1", 555) is None
    assert mw._vm_repo.get("h1", 300) is not None
    assert ("h1", 555) not in _cached_vmids()
    assert ("h1", 300) in _cached_vmids()


def test_lone_late_answer_is_not_lost(main_window, monkeypatch):
    """D1: a late answer must be rejected only when something FRESHER has
    already been applied for the host. A lone late answer (nothing fresher
    applied) is still accepted instead of being lost."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    mw.nodes_cfg = [_cfg("h1")]

    mw.refresh_data()
    gen_a = mw._refresh.hard_gen
    epoch_a = mw._refresh.epoch
    assert mw._refresh.hard_pending_count == 1

    # The watchdog force-finalizes the hung cycle; no soft cycle runs and
    # nothing fresher is applied for h1
    mw._refresh._hard_start = time.monotonic() - (mw._refresh.hard_timeout + 1)
    mw.last_refresh_ts = time.time()
    mw.soft_refresh()
    assert mw._refresh.hard_pending_count == 0

    # The only available answer arrives late — it must still apply
    mw.on_worker_finished(
        _ok("h1", nodes=[_node("pve1")], vms=[_vm(700, "pve1")],
            storages=[_st("pve1")]),
        created[0], gen_a, epoch_a)

    assert mw._vm_repo.get("h1", 700) is not None
    assert mw._node_repo.get("h1", "pve1") is not None


def test_new_hard_cycle_discards_late_answers(main_window, monkeypatch):
    """D1: a newly started hard cycle invalidates the hung previous one —
    its late answers never apply; the new cycle's own answers do."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    mw.nodes_cfg = [_cfg("h1")]

    mw.refresh_data()                       # cycle A hangs
    gen_a = mw._refresh.hard_gen
    epoch_a = mw._refresh.epoch
    mw._refresh._hard_start = time.monotonic() - (mw._refresh.hard_timeout + 1)
    mw.last_refresh_ts = time.time()
    mw.soft_refresh()                       # watchdog finalizes A

    mw.refresh_data()                       # cycle B starts
    gen_b = mw._refresh.hard_gen
    epoch_b = mw._refresh.epoch
    assert gen_b > gen_a and epoch_b > epoch_a

    # A's late answer: rejected (stale generation)
    mw.on_worker_finished(
        _ok("h1", nodes=[_node("pve1")], vms=[_vm(555, "pve1")],
            storages=[_st("pve1")]),
        created[0], gen_a, epoch_a)
    assert mw._vm_repo.get("h1", 555) is None
    assert mw._refresh.hard_pending_count == 1  # B still waits

    # B's answer: applied
    mw.on_worker_finished(
        _ok("h1", nodes=[_node("pve1")], vms=[_vm(100, "pve1")],
            storages=[_st("pve1")]),
        created[1], gen_b, epoch_b)
    assert mw._vm_repo.get("h1", 100) is not None
    assert mw._refresh.hard_pending_count == 0


def test_stale_answer_has_no_side_effects(main_window, monkeypatch):
    """D1: a stale answer is dropped silently — no repeated finalization,
    no cache rewrite, no status-line timestamp bump, no notifications."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    mw.nodes_cfg = [_cfg("h1")]

    shown = []
    from virtdeck.ui.notification import NotificationManager
    monkeypatch.setattr(NotificationManager, "show",
                        lambda self, msg, error=False: shown.append(msg))

    mw.refresh_data()
    gen_a = mw._refresh.hard_gen
    epoch_a = mw._refresh.epoch

    # A fresher soft answer applies first
    mw._refresh._hard_start = time.monotonic() - (mw._refresh.hard_timeout + 1)
    mw.last_refresh_ts = 0.0
    mw.soft_refresh()
    epoch_soft = mw._refresh.epoch
    mw.on_soft_refresh_result(
        _ok("h1", nodes=[_node("pve1")], vms=[_vm(300, "pve1")],
            storages=[_st("pve1")]),
        created[-1], mw._refresh.soft_gen, epoch_soft)
    ts_after_soft = mw.last_refresh_ts

    shown.clear()
    # The stale hard answer of cycle A
    mw.on_worker_finished(
        _ok("h1", nodes=[_node("pve1")], vms=[_vm(555, "pve1")],
            storages=[_st("pve1")]),
        created[0], gen_a, epoch_a)

    assert mw._vm_repo.get("h1", 555) is None
    assert mw.last_refresh_ts == ts_after_soft     # no re-finalization
    assert ("h1", 555) not in _cached_vmids()
    assert shown == []                             # no notifications


# --- Audit 4.2 / D2: pools survive partial failures ----------------------


def _pool_seed(mw, host, poolid, comment=""):
    mw._pool_repo.add(DomainPool.from_pve(
        {"poolid": poolid, "comment": comment}, host))


def test_partial_cycle_keeps_failed_host_pools(main_window, monkeypatch):
    """D2: pools of a host whose worker was rejected keep their last
    known-good data through the cycle."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    _pool_seed(mw, "h1", "web", "old")
    _pool_seed(mw, "h2", "db", "two")
    mw.nodes_cfg = [_cfg("h1"), _cfg("h2")]

    from virtdeck.ui.mainwindow import MAX_WORKERS
    for _ in range(MAX_WORKERS - 1):
        mw._workers.add(MagicMock())

    mw.refresh_data()
    gen = mw._refresh.hard_gen
    epoch = mw._refresh.epoch
    mw.on_worker_finished(
        _ok("h1", nodes=[_node("pve1")],
            pools=[{"poolid": "web", "comment": "new"}]),
        created[0], gen, epoch)

    # h1's pools replaced; h2's pools survived the cycle
    assert mw._pool_repo.get("h1", "web").comment == "new"
    assert mw._pool_repo.get("h2", "db").comment == "two"
    assert {p.host_name for p in mw._pool_repo.all()} == {"h1", "h2"}


def test_same_poolid_on_different_hosts_survives_cycle(
        main_window, monkeypatch):
    """D2: identical poolid on independent hosts must coexist — the
    refresh of one host never replaces the other's pool."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    _pool_seed(mw, "h1", "web", "one")
    _pool_seed(mw, "h2", "web", "two")
    mw.nodes_cfg = [_cfg("h1"), _cfg("h2")]

    mw.refresh_data()
    gen = mw._refresh.hard_gen
    epoch = mw._refresh.epoch
    mw.on_worker_finished(
        _ok("h1", nodes=[_node("pve1")],
            pools=[{"poolid": "web", "comment": "one-new"}]),
        created[0], gen, epoch)
    mw.on_worker_finished(
        _ok("h2", nodes=[_node("pve2")],
            pools=[{"poolid": "web", "comment": "two"}]),
        created[1], gen, epoch)

    assert mw._pool_repo.get("h1", "web").comment == "one-new"
    assert mw._pool_repo.get("h2", "web").comment == "two"


def test_confirmed_empty_pools_clear_host_pools(main_window, monkeypatch):
    """D2: a confirmed empty pool list (successful response) replaces the
    host's previous pools; a failed source (None) keeps them."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    _pool_seed(mw, "h1", "old", "one")
    mw.nodes_cfg = [_cfg("h1")]

    mw.refresh_data()
    gen = mw._refresh.hard_gen
    epoch = mw._refresh.epoch

    # Failed optional pool source: pools=None — previous data kept
    payload = _ok("h1", nodes=[_node("pve1")])
    payload["pools"] = None
    mw.on_worker_finished(payload, created[0], gen, epoch)
    assert mw._pool_repo.get("h1", "old") is not None

    # Confirmed empty list — previous pools cleared
    mw.refresh_data()
    gen = mw._refresh.hard_gen
    epoch = mw._refresh.epoch
    mw.on_worker_finished(
        _ok("h1", nodes=[_node("pve1")], pools=[]),
        created[-1], gen, epoch)
    assert mw._pool_repo.get("h1", "old") is None


def test_host_leaving_config_drops_its_pools(main_window, monkeypatch):
    """D2: hosts removed from the configuration lose their pools at the
    next cycle, while active hosts keep theirs."""
    mw = main_window
    _install_fake_fetch(monkeypatch)
    _pool_seed(mw, "h1", "web", "one")
    _pool_seed(mw, "h2", "db", "two")
    mw.nodes_cfg = [_cfg("h1")]  # h2 left the config

    mw.refresh_data()

    assert mw._pool_repo.get("h1", "web") is not None
    assert mw._pool_repo.get("h2", "db") is None


# --- Audit 6.1.1: HA sentinel (C-2) — same rules as pools -----------------


def _ha_seed(mw, host, group="g1", comment="old"):
    mw.all_ha_groups[host] = [DomainHaGroup.from_pve(
        {"group": group, "nodes": "pve1", "restricted": 0,
         "nofailback": 0, "comment": comment, "digest": ""})]


def _ha_payload(groups, comment="new"):
    return [{"group": g, "nodes": "pve1", "restricted": 0,
             "nofailback": 0, "comment": comment, "digest": ""}
            for g in groups]


def test_ok_replaces_pools_and_ha(main_window, monkeypatch):
    """A confirmed non-empty response replaces the host's previous pools
    and HA groups entirely."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    _pool_seed(mw, "h1", "web", "old")
    _ha_seed(mw, "h1", "g1", "old")
    mw.nodes_cfg = [_cfg("h1")]

    mw.refresh_data()
    gen = mw._refresh.hard_gen
    epoch = mw._refresh.epoch
    payload = _ok("h1", nodes=[_node("pve1")],
                  pools=[{"poolid": "web", "comment": "new"}])
    payload["ha_groups"] = _ha_payload(["g1"])
    mw.on_worker_finished(payload, created[0], gen, epoch)

    assert mw._pool_repo.get("h1", "web").comment == "new"
    assert mw.all_ha_groups["h1"][0].comment == "new"


def test_confirmed_empty_ha_clears_host_groups(main_window, monkeypatch):
    """An empty HA list in a successful response is a CONFIRMED absence:
    the host's previous groups are cleared, not kept."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    _ha_seed(mw, "h1", "old")
    mw.nodes_cfg = [_cfg("h1")]

    mw.refresh_data()
    gen = mw._refresh.hard_gen
    epoch = mw._refresh.epoch
    mw.on_worker_finished(
        _ok("h1", nodes=[_node("pve1")]),  # _ok carries ha_groups=[]
        created[0], gen, epoch)

    assert mw.all_ha_groups.get("h1") == []


def test_ha_not_fetched_keeps_previous_groups(main_window, monkeypatch):
    """ha_groups=None ("not fetched") keeps the host's previous HA
    groups; it must never be treated as a confirmed absence."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    _ha_seed(mw, "h1", "g1")
    mw.nodes_cfg = [_cfg("h1")]

    mw.refresh_data()
    gen = mw._refresh.hard_gen
    epoch = mw._refresh.epoch
    payload = _ok("h1", nodes=[_node("pve1")])
    payload["ha_groups"] = None
    mw.on_worker_finished(payload, created[0], gen, epoch)

    assert [g.group for g in mw.all_ha_groups.get("h1", [])] == ["g1"]


def test_errored_host_keeps_pools_and_ha(main_window, monkeypatch):
    """An error cycle after a successful one keeps the host's last
    known-good pools and HA groups (no wholesale wipe at cycle start)."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    mw.nodes_cfg = [_cfg("h1")]

    mw.refresh_data()
    gen = mw._refresh.hard_gen
    epoch = mw._refresh.epoch
    payload = _ok("h1", nodes=[_node("pve1")],
                  pools=[{"poolid": "web", "comment": "one"}])
    payload["ha_groups"] = _ha_payload(["g1"])
    mw.on_worker_finished(payload, created[0], gen, epoch)
    assert mw.all_ha_groups.get("h1")

    mw.refresh_data()
    gen = mw._refresh.hard_gen
    epoch = mw._refresh.epoch
    mw.on_worker_finished(_err("h1"), created[-1], gen, epoch)

    assert mw._pool_repo.get("h1", "web").comment == "one"
    assert [g.group for g in mw.all_ha_groups.get("h1", [])] == ["g1"]


def test_partial_host_keeps_pools_and_ha(main_window, monkeypatch):
    """A partial cycle (host confirmed, some lists missing) never wipes
    the host's pools or HA groups just because sources were
    unsuccessful."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    _pool_seed(mw, "h1", "web", "one")
    _ha_seed(mw, "h1", "g1")
    mw.nodes_cfg = [_cfg("h1")]

    mw.refresh_data()
    gen = mw._refresh.hard_gen
    epoch = mw._refresh.epoch
    mw.on_worker_finished(
        {"host": "h1", "status": "partial",
         "error": "incomplete snapshot — guest/storage lists: boom",
         "nodes": [_node("pve1")], "vms": [], "storages": [],
         "pools": None, "iso_images": {}, "ha_groups": None},
        created[0], gen, epoch)

    assert mw._pool_repo.get("h1", "web").comment == "one"
    assert [g.group for g in mw.all_ha_groups.get("h1", [])] == ["g1"]


def test_host_leaving_config_drops_its_ha(main_window, monkeypatch):
    """Hosts removed from the configuration lose their HA groups at the
    next cycle start (the pools rule), while active hosts keep theirs."""
    mw = main_window
    _install_fake_fetch(monkeypatch)
    _ha_seed(mw, "h1", "one")
    _ha_seed(mw, "h2", "two")
    mw.nodes_cfg = [_cfg("h1")]  # h2 left the config

    mw.refresh_data()

    assert [g.group for g in mw.all_ha_groups.get("h1", [])] == ["one"]
    assert mw.all_ha_groups.get("h2") is None


def test_one_hosts_failure_keeps_others_pools_and_ha(
        main_window, monkeypatch):
    """One host's failed cycle must not touch other hosts' pools or HA
    groups."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    _pool_seed(mw, "h1", "web", "one")
    _ha_seed(mw, "h1", "g1")
    mw.nodes_cfg = [_cfg("h1"), _cfg("h2")]

    mw.refresh_data()
    gen = mw._refresh.hard_gen
    epoch = mw._refresh.epoch
    mw.on_worker_finished(_err("h1"), created[0], gen, epoch)
    payload = _ok("h2", nodes=[_node("pve2")],
                  pools=[{"poolid": "db", "comment": "two"}])
    payload["ha_groups"] = _ha_payload(["g2"])
    mw.on_worker_finished(payload, created[1], gen, epoch)

    # h1 keeps its last known-good data; h2's confirmed data applied
    assert mw._pool_repo.get("h1", "web").comment == "one"
    assert [g.group for g in mw.all_ha_groups.get("h1", [])] == ["g1"]
    assert mw._pool_repo.get("h2", "db").comment == "two"
    assert [g.group for g in mw.all_ha_groups.get("h2", [])] == ["g2"]


def test_wrong_conn_id_leaves_pools_and_ha_untouched(
        main_window, monkeypatch):
    """The identity gate drops a result of an unknown connection before
    it can touch pools or HA groups."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    _pool_seed(mw, "h1", "web", "one")
    _ha_seed(mw, "h1", "g1")
    mw.nodes_cfg = [_cfg("h1")]

    mw.refresh_data()
    gen = mw._refresh.hard_gen
    epoch = mw._refresh.epoch
    payload = _ok("h1", nodes=[_node("pve1")],
                  pools=[{"poolid": "web", "comment": "intruder"}])
    payload["ha_groups"] = _ha_payload(["intruder"])
    payload["conn_id"] = "id-deleted-or-foreign"
    mw.on_worker_finished(payload, created[0], gen, epoch)

    assert mw._pool_repo.get("h1", "web").comment == "one"
    assert [g.group for g in mw.all_ha_groups.get("h1", [])] == ["g1"]


def test_late_old_generation_leaves_pools_and_ha_untouched(
        main_window, monkeypatch):
    """A late answer of an already-invalidated generation must not
    overwrite fresher pools or HA groups."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    mw.nodes_cfg = [_cfg("h1")]

    mw.refresh_data()                       # cycle A hangs
    gen_a = mw._refresh.hard_gen
    epoch_a = mw._refresh.epoch
    mw._refresh._hard_start = time.monotonic() - (mw._refresh.hard_timeout + 1)
    mw.last_refresh_ts = time.time()
    mw.soft_refresh()                       # watchdog finalizes A

    mw.refresh_data()                       # cycle B starts
    gen_b = mw._refresh.hard_gen
    epoch_b = mw._refresh.epoch

    payload_a = _ok("h1", nodes=[_node("pve1")],
                    pools=[{"poolid": "stale", "comment": "stale"}])
    payload_a["ha_groups"] = _ha_payload(["stale"], comment="stale")
    mw.on_worker_finished(payload_a, created[0], gen_a, epoch_a)

    payload_b = _ok("h1", nodes=[_node("pve1")],
                    pools=[{"poolid": "fresh", "comment": "fresh"}])
    payload_b["ha_groups"] = _ha_payload(["fresh"], comment="fresh")
    mw.on_worker_finished(payload_b, created[1], gen_b, epoch_b)

    assert mw._pool_repo.get("h1", "stale") is None
    assert mw._pool_repo.get("h1", "fresh").comment == "fresh"
    assert [g.group for g in mw.all_ha_groups.get("h1", [])] == ["fresh"]


def test_same_ha_group_on_different_hosts_survives_cycle(
        main_window, monkeypatch):
    """Identical HA group names on independent hosts must coexist — the
    refresh of one host never replaces the other's groups."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    _ha_seed(mw, "h1", "web")
    _ha_seed(mw, "h2", "web")
    mw.nodes_cfg = [_cfg("h1"), _cfg("h2")]

    mw.refresh_data()
    gen = mw._refresh.hard_gen
    epoch = mw._refresh.epoch
    payload = _ok("h1", nodes=[_node("pve1")])
    payload["ha_groups"] = _ha_payload(["web"], comment="h1-new")
    mw.on_worker_finished(payload, created[0], gen, epoch)

    assert mw.all_ha_groups["h1"][0].comment == "h1-new"
    assert mw.all_ha_groups["h2"][0].comment == "old"


def test_recreated_same_name_connection_starts_clean(main_window,
                                                     monkeypatch):
    """Delete + re-create under the same name (new conn_id): the old
    identity's in-memory pools and HA groups are dropped by the delete
    flow's refresh_data (departed hosts), so the re-created connection
    never shows the previous infrastructure's data."""
    mw = main_window
    created = _install_fake_fetch(monkeypatch)
    _pool_seed(mw, "h1", "web", "old")
    _ha_seed(mw, "h1", "g1", "old")

    # _on_host_remove removes the entry and ends with refresh_data() —
    # the departed-hosts drop clears the name-keyed data of the old
    # identity before the user can re-create the connection.
    mw.nodes_cfg = []
    mw.refresh_data()
    assert mw._pool_repo.get("h1", "web") is None
    assert mw.all_ha_groups.get("h1") is None

    # Re-created under the same name with a fresh conn_id: it starts
    # clean — no data is attached until its own results arrive.
    mw.nodes_cfg = [dict(_cfg("h1"), conn_id="id-h1-recreated")]
    mw.refresh_data()
    assert mw._pool_repo.get("h1", "web") is None
    assert mw.all_ha_groups.get("h1") is None

    gen = mw._refresh.hard_gen
    epoch = mw._refresh.epoch
    payload = _ok("h1", nodes=[_node("pve1")],
                  pools=[{"poolid": "web", "comment": "new-identity"}])
    payload["ha_groups"] = _ha_payload(["g1"])
    payload["conn_id"] = "id-h1-recreated"
    mw.on_worker_finished(payload, created[0], gen, epoch)

    assert mw._pool_repo.get("h1", "web").comment == "new-identity"
    assert [g.group for g in mw.all_ha_groups["h1"]] == ["g1"]


# --- Audit 4.2 / D3: duplicate cluster representatives --------------------


def test_duplicate_cluster_rep_dropped_with_notice(qtbot, monkeypatch,
                                                   tmp_path):
    """D3: two config entries of the SAME cluster keep only the first
    representative and notify the user instead of duplicating resources."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _install_fake_fetch(monkeypatch)
    shown = []
    from virtdeck.ui.notification import NotificationManager
    monkeypatch.setattr(NotificationManager, "show",
                        lambda self, msg, error=False: shown.append(msg))
    from virtdeck.ui.mainwindow import MainWindow

    rep_a = {"name": "cl1-a", "host": "10.0.0.1", "user": "u@pam",
             "token_name": "t", "token_value": "s",
             "cluster_rep": True, "cluster": "cl1"}
    rep_b = {"name": "cl1-b", "host": "10.0.0.2", "user": "u@pam",
             "token_name": "t", "token_value": "s",
             "cluster_rep": True, "cluster": "cl1"}

    created = _install_fake_fetch(monkeypatch)
    mw = MainWindow(nodes_cfg=[rep_a, rep_b])
    qtbot.addWidget(mw)
    try:
        assert [c["name"] for c in mw.nodes_cfg] == ["cl1-a"]
        assert any("cl1" in m and "cl1-b" in m for m in shown)

        created.clear()  # drop the workers of the __init__ cycle
        mw.refresh_data()
        assert len(created) == 1  # only cl1-a refreshes
        assert created[0].node_cfg["name"] == "cl1-a"
    finally:
        mw.close()


def test_same_node_names_different_clusters_stay_separate(
        qtbot, monkeypatch, tmp_path):
    """D3: clusters with DIFFERENT names but coinciding node names are
    independent infrastructures — both refresh, no cross-matching."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    created = _install_fake_fetch(monkeypatch)
    from virtdeck.ui.mainwindow import MainWindow

    cl1 = {"name": "cl1", "host": "10.0.0.1", "user": "u@pam",
           "token_name": "t", "token_value": "s",
           "cluster_rep": True, "cluster": "cl1"}
    cl2 = {"name": "cl2", "host": "10.0.0.2", "user": "u@pam",
           "token_name": "t", "token_value": "s",
           "cluster_rep": True, "cluster": "cl2"}

    mw = MainWindow(nodes_cfg=[cl1, cl2])
    qtbot.addWidget(mw)
    try:
        assert [c["name"] for c in mw.nodes_cfg] == ["cl1", "cl2"]
        created.clear()  # drop the workers of the __init__ cycle
        mw.refresh_data()
        gen = mw._refresh.hard_gen
        epoch = mw._refresh.epoch
        assert len(created) == 2
        for w, vmid in zip(created, (100, 200), strict=True):
            mw.on_worker_finished(
                _ok(w.node_cfg["name"], nodes=[_node("pve1")],
                    vms=[_vm(vmid, "pve1")], storages=[_st("pve1")]),
                w, gen, epoch)

        # Distinct hosts: the same node name never merges the clusters
        assert mw._node_repo.get("cl1", "pve1") is not None
        assert mw._node_repo.get("cl2", "pve1") is not None
        assert len(mw._node_repo.all()) == 2
        assert len(mw._vm_repo.all()) == 2
    finally:
        mw.close()


def test_dedupe_cluster_cfgs_helper(main_window):
    """D3 unit: first representative per cluster name is kept; standalone
    and non-representative configs are never touched."""
    mw = main_window
    cfgs = [
        {"name": "s1", "cluster": False},
        {"name": "a", "cluster_rep": True, "cluster": "cl1"},
        {"name": "b", "cluster_rep": True, "cluster": "cl1"},
        {"name": "c", "cluster_rep": True, "cluster": "cl2"},
        {"name": "s2", "cluster": "Standalone"},
        {"name": "d", "cluster_rep": True, "cluster": "cl1"},
    ]
    kept, dups = mw._dedupe_cluster_cfgs(cfgs)
    assert [c["name"] for c in kept] == ["s1", "a", "c", "s2"]
    assert dups == [("cl1", "b"), ("cl1", "d")]
