"""Audit 4.1 (D2): FetchWorker must not mask mandatory-source failures as
an "ok" snapshot — absence of an answer is not the absence of resources.

Status semantics (see FetchWorker docstring):
- ok        every mandatory source completed successfully (empty lists
            are a confirmed absence);
- partial   the host is confirmed, some mandatory resource lists are not;
- error     the mandatory core is unavailable entirely.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

from tests.backend.test_backend import FakeProvider, FakePveApi
from virtdeck import backend
from virtdeck.backend import FetchWorker


def _run_worker(monkeypatch, provider, cfg):
    monkeypatch.setattr(backend.fetch, "create_provider",
                        lambda c, timeout=15: provider)
    worker = FetchWorker(cfg)
    emitted = []
    worker.signals.result_ready.connect(lambda d: emitted.append(d))
    worker.run()
    assert len(emitted) == 1
    return emitted[0]


def test_failed_mandatory_cluster_request_is_error(qtbot, monkeypatch):
    """/cluster/resources raising must yield "error", not an "ok" with
    empty lists (the old masking: "empty" looked like "no resources")."""
    provider = FakeProvider()
    calls = {"n": 0}

    def failing_resources():
        calls["n"] += 1
        raise RuntimeError("connection refused")

    provider.cluster = SimpleNamespace(
        list_resources=failing_resources, list_ha_groups=lambda: [])
    provider.pools = FakePveApi().pools

    data = _run_worker(monkeypatch, provider,
                       {"name": "h1", "cluster_rep": True, "cluster": "c1"})

    assert calls["n"] == 1
    assert data["status"] == "error"
    assert "connection refused" in data["error"]
    # No fake empty snapshot is offered as confirmed data
    assert "nodes" not in data
    assert "vms" not in data


def test_join_timeout_marks_mandatory_result_error(qtbot, monkeypatch):
    """A mandatory thread outliving its join deadline means its data never
    arrived — the result must not be "ok" (audit 4.1)."""
    provider = FakeProvider()
    started = threading.Event()
    release = threading.Event()

    def hanging_resources():
        started.set()
        release.wait(5)
        return []

    provider.cluster = SimpleNamespace(
        list_resources=hanging_resources, list_ha_groups=lambda: [])
    provider.pools = FakePveApi().pools

    worker_cfg = {"name": "h1", "cluster_rep": True, "cluster": "c1"}
    monkeypatch.setattr(backend.fetch, "create_provider",
                        lambda c, timeout=15: provider)
    worker = FetchWorker(worker_cfg)
    worker.join_phase1 = 0.1  # shrink the ceiling for the test
    emitted = []
    worker.signals.result_ready.connect(lambda d: emitted.append(d))
    try:
        worker.run()
    finally:
        release.set()  # unblock the daemon thread
    assert started.is_set()

    assert len(emitted) == 1
    assert emitted[0]["status"] == "error"
    assert "did not finish" in emitted[0]["error"]


def test_failed_guest_lists_are_partial(qtbot, monkeypatch):
    """Standalone: the node itself is confirmed, but the guest/storage
    listings failed — "partial", not an "ok" with empty lists."""
    provider = FakeProvider()
    provider.nodes = SimpleNamespace(
        list=lambda: [{"node": "pve1"}],
        get_status=lambda n: {"pveversion": "8.2.4", "memory": {},
                              "rootfs": {}, "cpuinfo": {}},
        get_version=lambda n: {},
        list_storage=_raise_runtime("storage boom"),
    )
    provider.vms = FakePveApi().vms
    provider.cluster = FakePveApi().cluster
    provider.pools = FakePveApi().pools

    data = _run_worker(monkeypatch, provider, {"name": "h1"})

    assert data["status"] == "partial"
    assert "incomplete" in data["error"]
    assert "storage boom" in data["error"]
    # The confirmed part is still delivered
    assert len(data["nodes"]) == 1


def test_failed_node_status_is_error(qtbot, monkeypatch):
    """Standalone: without the node status there is no confirmed snapshot
    at all — "error" with an error-node payload, never an empty "ok"."""
    provider = FakeProvider()
    provider.nodes = SimpleNamespace(
        list=lambda: [{"node": "pve1"}],
        get_status=_raise_runtime("auth failed"),
        get_version=lambda n: {},
        list_storage=lambda n: [],
    )
    provider.vms = FakePveApi().vms
    provider.cluster = FakePveApi().cluster
    provider.pools = FakePveApi().pools

    data = _run_worker(monkeypatch, provider, {"name": "h1"})

    assert data["status"] == "error"
    assert "auth failed" in data["error"]


def test_optional_source_failure_keeps_ok(qtbot, monkeypatch):
    """Pools/HA are optional: their failure never downgrades the snapshot
    and must not wipe already-collected UI data (omitted keys/empty)."""
    provider = FakeProvider()
    resources = [
        {"type": "node", "node": "pve1", "status": "online"},
        {"type": "qemu", "vmid": 100, "name": "web", "node": "pve1",
         "status": "running"},
    ]

    def failing_pools():
        raise RuntimeError("pools boom")

    provider.cluster = SimpleNamespace(
        list_resources=lambda: resources, list_ha_groups=_raise_runtime("ha"))
    provider.pools = SimpleNamespace(list=failing_pools, get=lambda p: {})
    provider.nodes = FakePveApi().nodes
    provider.storage = FakePveApi().storage

    data = _run_worker(monkeypatch, provider,
                       {"name": "h1", "cluster_rep": True, "cluster": "c1"})

    assert data["status"] == "ok"
    assert len(data["vms"]) == 1
    assert len(data["nodes"]) == 1


def test_failed_pool_source_signals_not_fetched(qtbot, monkeypatch):
    """Audit 4.2, D2: a failed optional pool source emits ``pools: None``
    (\"not fetched\") instead of a fake confirmed-empty list, so the
    consumer keeps the previous pool data of the host."""
    provider = FakeProvider()
    resources = [{"type": "node", "node": "pve1", "status": "online"}]

    def failing_pools():
        raise RuntimeError("pools boom")

    provider.cluster = SimpleNamespace(
        list_resources=lambda: resources, list_ha_groups=lambda: [])
    provider.pools = SimpleNamespace(list=failing_pools, get=lambda p: {})
    provider.nodes = FakePveApi().nodes
    provider.storage = FakePveApi().storage

    data = _run_worker(monkeypatch, provider,
                       {"name": "h1", "cluster_rep": True, "cluster": "c1"})

    assert data["status"] == "ok"
    assert data["pools"] is None


def test_confirmed_empty_pools_emit_empty_list(qtbot, monkeypatch):
    """A successful pool fetch returning nothing is a CONFIRMED absence:
    an empty list, not None."""
    provider = FakeProvider()
    resources = [{"type": "node", "node": "pve1", "status": "online"}]
    provider.cluster = SimpleNamespace(
        list_resources=lambda: resources, list_ha_groups=lambda: [])
    provider.pools = FakePveApi().pools  # list() -> []
    provider.nodes = FakePveApi().nodes
    provider.storage = FakePveApi().storage

    data = _run_worker(monkeypatch, provider,
                       {"name": "h1", "cluster_rep": True, "cluster": "c1"})

    assert data["status"] == "ok"
    assert data["pools"] == []


def test_failed_ha_source_signals_not_fetched(qtbot, monkeypatch):
    """Audit 6.1.1, C-2: a failed optional HA source emits ``ha_groups:
    None`` ("not fetched") instead of a fake confirmed-empty list, so the
    consumer keeps the previous HA data of the host."""
    provider = FakeProvider()
    resources = [{"type": "node", "node": "pve1", "status": "online"}]
    provider.cluster = SimpleNamespace(
        list_resources=lambda: resources, list_ha_groups=_raise_runtime("ha"))
    provider.pools = FakePveApi().pools
    provider.nodes = FakePveApi().nodes
    provider.storage = FakePveApi().storage

    data = _run_worker(monkeypatch, provider,
                       {"name": "h1", "cluster_rep": True, "cluster": "c1"})

    assert data["status"] == "ok"
    assert data["ha_groups"] is None


def test_pool_thread_timeout_signals_not_fetched(qtbot, monkeypatch):
    """Audit 6.1.1, C-1: a pools thread outliving the join deadline means
    its data never arrived — ``pools: None``, never the empty default
    that would look like a confirmed absence."""
    started, release = threading.Event(), threading.Event()

    def hanging_pools():
        started.set()
        release.wait(5)
        return []

    provider = FakeProvider()
    resources = [{"type": "node", "node": "pve1", "status": "online"}]
    provider.cluster = SimpleNamespace(
        list_resources=lambda: resources, list_ha_groups=lambda: [])
    provider.pools = SimpleNamespace(list=hanging_pools, get=lambda p: {})
    provider.nodes = FakePveApi().nodes
    provider.storage = FakePveApi().storage

    monkeypatch.setattr(backend.fetch, "create_provider",
                        lambda c, timeout=15: provider)
    worker = FetchWorker({"name": "h1", "cluster_rep": True, "cluster": "c1"})
    worker.join_phase1 = 0.1  # shrink the ceiling for the test
    emitted = []
    worker.signals.result_ready.connect(lambda d: emitted.append(d))
    try:
        worker.run()
    finally:
        release.set()  # unblock the daemon thread
    assert started.is_set()

    assert len(emitted) == 1
    assert emitted[0]["status"] == "ok"
    assert emitted[0]["pools"] is None


def test_ha_thread_timeout_signals_not_fetched(qtbot, monkeypatch):
    """Audit 6.1.1, C-2: an HA thread outliving the join deadline is
    "not fetched" (``ha_groups: None``), not a confirmed absence."""
    started, release = threading.Event(), threading.Event()

    def hanging_ha():
        started.set()
        release.wait(5)
        return []

    provider = FakeProvider()
    resources = [{"type": "node", "node": "pve1", "status": "online"}]
    provider.cluster = SimpleNamespace(
        list_resources=lambda: resources, list_ha_groups=hanging_ha)
    provider.pools = FakePveApi().pools
    provider.nodes = FakePveApi().nodes
    provider.storage = FakePveApi().storage

    monkeypatch.setattr(backend.fetch, "create_provider",
                        lambda c, timeout=15: provider)
    worker = FetchWorker({"name": "h1", "cluster_rep": True, "cluster": "c1"})
    worker.join_phase1 = 0.1
    emitted = []
    worker.signals.result_ready.connect(lambda d: emitted.append(d))
    try:
        worker.run()
    finally:
        release.set()
    assert started.is_set()

    assert len(emitted) == 1
    assert emitted[0]["status"] == "ok"
    assert emitted[0]["ha_groups"] is None


def _raise_runtime(msg):
    def _inner(*args, **kwargs):
        raise RuntimeError(msg)
    return _inner
