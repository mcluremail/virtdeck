"""FetchWorker.cancel() must abort run() quietly (no signal emissions)
so app shutdown is not delayed by in-flight refresh workers."""

from __future__ import annotations

from tests.backend.test_backend import FakeProvider, FakePveApi
from virtdeck import backend
from virtdeck.backend import FetchWorker


def _make_worker(monkeypatch, provider):
    monkeypatch.setattr(backend.fetch, "create_provider", lambda cfg, timeout=15: provider)
    return FetchWorker({"name": "h1"})


def test_cancel_skips_all_work_and_emits_nothing(qtbot, monkeypatch):
    provider = FakeProvider()
    worker = _make_worker(monkeypatch, provider)
    worker.cancel()

    emitted = []
    worker.signals.result_ready.connect(lambda d: emitted.append(d))
    worker.run()

    assert emitted == []
    assert provider.closed


def test_uncancelled_worker_emits_result(qtbot, monkeypatch):
    # Every API call succeeds with empty lists: a CONFIRMED absence of
    # resources — the result must be a full "ok" snapshot, not an error
    # and not a masked partial (audit 4.1, test 3).
    provider = FakeProvider()
    provider.nodes = FakePveApi().nodes
    provider.vms = FakePveApi().vms
    provider.cluster = FakePveApi().cluster
    provider.pools = FakePveApi().pools
    provider.storage = FakePveApi().storage
    worker = _make_worker(monkeypatch, provider)

    emitted = []
    worker.signals.result_ready.connect(lambda d: emitted.append(d))
    worker.run()

    assert len(emitted) == 1
    assert emitted[0]["status"] == "ok"
    # The node itself is confirmed; guests/storages are a confirmed empty
    assert len(emitted[0]["nodes"]) == 1
    assert emitted[0]["vms"] == []
    assert emitted[0]["storages"] == []
    assert provider.closed
