"""Tests for WorkerManager queueing instead of silently dropping workers."""
from types import SimpleNamespace

import pytest

import virtdeck.ui.detail_panel._worker_manager as wmod
from virtdeck.ui.detail_panel._constants import _MAX_WORKERS_DP
from virtdeck.ui.detail_panel._worker_manager import WorkerManager


class _SignalStub:
    """Minimal finished-signal double: connect() stores, emit() fires."""

    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self):
        for slot in list(self._slots):
            slot()


class _FakePool:
    def __init__(self):
        self.started = []

    def start(self, worker):
        self.started.append(worker)


@pytest.fixture
def pool(monkeypatch):
    fake = _FakePool()
    monkeypatch.setattr(wmod.QThreadPool, "globalInstance", staticmethod(lambda: fake))
    return fake


def _worker():
    from unittest.mock import MagicMock

    w = MagicMock()
    w.signals.finished.connect = MagicMock()
    return w


def test_worker_starts(pool):
    wm = WorkerManager()
    w = _worker()
    wm.run_worker(w)
    assert pool.started == [w]
    assert w in wm._workers


def test_pool_full_queues_then_starts_on_free(pool):
    wm = WorkerManager()
    workers = [_worker() for _ in range(_MAX_WORKERS_DP)]
    for w in workers:
        wm.run_worker(w)
    assert len(pool.started) == _MAX_WORKERS_DP

    queued = _worker()
    wm.run_worker(queued)
    assert pool.started == workers  # not started while pool is full

    wm.discard_worker(workers[0])
    assert pool.started == workers + [queued]  # pumped as a slot frees
    assert queued in wm._workers


def test_queue_is_bounded(pool):
    wm = WorkerManager()
    for _ in range(_MAX_WORKERS_DP):
        wm.run_worker(_worker())
    limit = _MAX_WORKERS_DP * 2
    for _ in range(limit):
        wm.run_worker(_worker())
    overflow = _worker()
    wm.run_worker(overflow)
    assert overflow not in wm._pending
    assert len(wm._pending) == limit


def test_host_worker_tracked_for_cancel(pool):
    wm = WorkerManager()
    w = _worker()
    wm.run_host_worker(w)
    assert w in wm.current_host_workers
    # Simulate the finished signal firing its registered callback.
    on_finished = w.signals.finished.connect.call_args[0][0]
    on_finished()
    assert w not in wm._workers
    assert w not in wm.current_host_workers


def test_cancel_general_clears_pending(pool):
    wm = WorkerManager()
    for _ in range(_MAX_WORKERS_DP):
        wm.run_worker(_worker())
    for _ in range(3):
        wm.run_worker(_worker())
    assert wm._pending
    wm.cancel_general_workers()
    assert not wm._pending


# --- audit 6.3.2a D8: overload must be observable, not silent -------------

def test_drop_returns_false_and_fires_on_overload(pool):
    """Pool and queue both full: run_worker reports the refusal and the
    wired callback fires (the old behaviour was a bare logger.warning and
    an eternal "Loading…" tab)."""
    wm = WorkerManager()
    fired = []
    wm.on_overload = lambda: fired.append(True)
    for _ in range(_MAX_WORKERS_DP):
        assert wm.run_worker(_worker()) is True
    for _ in range(_MAX_WORKERS_DP * 2):
        assert wm.run_worker(_worker()) is True
    overflow = _worker()
    assert wm.run_worker(overflow) is False
    assert fired == [True]
    assert overflow not in wm._workers
    assert overflow not in wm._pending
    assert pool.started[-1] is not overflow


def test_no_on_overload_still_reports_false(pool):
    wm = WorkerManager()
    for _ in range(_MAX_WORKERS_DP):
        wm.run_worker(_worker())
    for _ in range(_MAX_WORKERS_DP * 2):
        wm.run_worker(_worker())
    assert wm.run_worker(_worker()) is False


def test_queued_worker_reports_true(pool):
    """Queued is accepted (the action will run once a slot frees): the
    caller must not treat it as a refusal."""
    wm = WorkerManager()
    for _ in range(_MAX_WORKERS_DP):
        wm.run_worker(_worker())
    queued = _worker()
    assert wm.run_worker(queued) is True
    assert (queued, False) in wm._pending


def test_worker_accepted_then_raising_is_discarded(pool):
    """A task accepted by the manager but finished by an exception: the
    backend workers emit finished in finally, so the manager must free
    the slot (no leak, the pool keeps accepting)."""
    wm = WorkerManager()

    class _RaisingWorker:
        def __init__(self):
            self.signals = SimpleNamespace(finished=_SignalStub())

        def run(self):
            raise RuntimeError("boom")

    w = _RaisingWorker()
    wm.run_worker(w)
    assert w in wm._workers
    # the finished connection registered by _try_start:
    w.signals.finished.emit()
    assert w not in wm._workers
