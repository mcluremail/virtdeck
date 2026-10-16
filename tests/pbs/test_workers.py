"""Tests for virtdeck.pbs.workers — PbsApiWorker lifecycle.

Regression from the 2026-09-09 audit: the provider (requests.Session) is
closed in finally — on success and on error (previously never closed).
"""
from __future__ import annotations

import pytest

from virtdeck.pbs.client import PbsError
from virtdeck.pbs.provider import PbsProvider
from virtdeck.pbs.workers import PbsApiWorker


class FakeClient:
    def __init__(self, boom: bool = False):
        self.boom = boom
        self.closed = False

    def close(self):
        self.closed = True

    def datastores(self):
        if self.boom:
            raise PbsError("boom", 500)
        return [{"store": "main"}]

    def datastore_status(self, store):
        return {"usage": 0.5, "used": 5, "total": 10}


@pytest.fixture()
def fake_provider(monkeypatch):
    made = []

    def _make(cfg, timeout=15):
        p = PbsProvider(cfg, timeout=timeout)
        p._client = FakeClient(boom=cfg.get("_boom", False))
        made.append(p)
        return p

    monkeypatch.setattr("virtdeck.pbs.workers.PbsProvider", _make)
    return made


def _run_worker(cfg):
    results, failures = [], []
    w = PbsApiWorker(cfg, "datastores")
    # signals are per instance now (audit 6.3.2a D9)
    w.signals.done.connect(lambda tag, res: results.append(res))
    w.signals.failed.connect(lambda tag, err: failures.append(err))
    w.run()  # no QThreadPool needed: run() called directly
    return results, failures


def test_provider_closed_on_success(fake_provider):
    results, failures = _run_worker({"host": "h", "_boom": False})
    assert failures == []
    assert results and results[0] and results[0][0].name == "main"
    assert len(fake_provider) == 1
    assert fake_provider[0]._client.closed


def test_provider_closed_on_error(fake_provider):
    results, failures = _run_worker({"host": "h", "_boom": True})
    assert results == []
    assert failures == ["boom"]
    assert fake_provider[0]._client.closed


def test_finished_emitted_in_finally(fake_provider):
    """Audit 6.3.2a D9: finished fires exactly once per run — success,
    error and any exception must release the tracking slot."""
    finished = []
    w = PbsApiWorker({"host": "h"}, "datastores")
    w.signals.finished.connect(lambda: finished.append(True))
    w.run()
    assert finished == [True]


# ── audit 6.3.3 D16: PbsTaskTracker — background watch of one UPID ─────


from virtdeck.pbs.workers import PbsTaskTracker


class FakeTrackerProvider:
    """Scripted PbsProvider.task_status for tracker tests."""

    def __init__(self, script):
        self.script = script
        self.polls = 0
        self.closed_times = 0

    def close(self):
        self.closed_times += 1

    def task_status(self, upid):
        self.polls += 1
        item = self.script[min(self.polls - 1, len(self.script) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


class TrackerHarness:
    """Runs PbsTaskTracker directly (no QThreadPool, interval=0)."""

    def __init__(self, monkeypatch, script, **kw):
        self.provider = FakeTrackerProvider(script)
        made = []

        def _make(cfg, timeout=15):
            made.append(self.provider)
            return self.provider

        monkeypatch.setattr("virtdeck.pbs.workers.PbsProvider", _make)
        self.updates = []
        self.finished_count = 0
        self.tag = kw.pop("tag", ("pbs1", "UPID:x"))
        self.tracker = PbsTaskTracker({"host": "h"}, "UPID:x",
                                      interval=0.0, tag=self.tag, **kw)
        self.tracker.signals.update.connect(
            lambda tag, payload: self.updates.append((tag, payload)))
        self.tracker.signals.finished.connect(
            lambda: setattr(self, "finished_count",
                            self.finished_count + 1))

    def run(self):
        self.tracker.run()  # direct call: deterministic, no threads
        return self.updates, self.finished_count


def test_tracker_success_after_running(monkeypatch):
    h = TrackerHarness(monkeypatch,
                       [("running", ""), ("success", "")], deadline=5)
    updates, finished = h.run()
    assert updates[-1] == (h.tag, ("success", ""))
    assert finished == 1
    assert h.provider.closed_times == 1  # released exactly once


def test_tracker_task_failure(monkeypatch):
    h = TrackerHarness(monkeypatch,
                       [("running", ""), ("failed", "Error: verify boom")],
                       deadline=5)
    updates, finished = h.run()
    assert updates[-1] == (h.tag, ("failed", "Error: verify boom"))
    assert finished == 1


def test_tracker_unknown_is_terminal(monkeypatch):
    # stopped without exit status: stop polling immediately, do not
    # burn the deadline, report unknown
    h = TrackerHarness(
        monkeypatch,
        [("unknown", "task stopped but exit status is unavailable")],
        deadline=60)
    updates, _ = h.run()
    assert h.provider.polls == 1
    assert updates[-1][1][0] == "unknown"
    assert "exit status" in updates[-1][1][1]


def test_tracker_repeated_read_failures_become_unknown(monkeypatch):
    # transient read errors are tolerated within a budget, then the
    # outcome is reported unknown — never a task failure
    h = TrackerHarness(monkeypatch, [PbsError("HTTP 500", 500)],
                       deadline=60, max_read_failures=3)
    updates, _ = h.run()
    assert h.provider.polls == 3
    assert updates[-1][1][0] == "unknown"
    assert "unreadable" in updates[-1][1][1]


def test_tracker_rights_error_is_immediately_unknown(monkeypatch):
    # 401/403 will not heal by polling: one read, then unknown
    h = TrackerHarness(monkeypatch, [PbsError("HTTP 403", 403)],
                       deadline=60)
    updates, _ = h.run()
    assert h.provider.polls == 1
    assert updates[-1][1][0] == "unknown"
    assert "readable" in updates[-1][1][1]


def test_tracker_deadline_is_not_a_task_failure(monkeypatch):
    # VirtDeck stopped watching; the task may still run on PBS
    h = TrackerHarness(monkeypatch, [("running", "")], deadline=0)
    updates, finished = h.run()
    assert h.provider.polls == 1
    assert updates[-1][1][0] == "timeout"
    assert "still be running" in updates[-1][1][1]
    assert finished == 1


def test_tracker_provider_construction_error(monkeypatch):
    # even a crash inside run() emits an honest unknown, finishes once
    class Boom:
        def __init__(self, cfg, timeout=15):
            raise RuntimeError("no provider")

    monkeypatch.setattr("virtdeck.pbs.workers.PbsProvider", Boom)
    updates, finished = [], []

    t = PbsTaskTracker({"host": "h"}, "UPID:x", interval=0.0,
                       tag=("s", "UPID:x"))
    t.signals.update.connect(lambda tag, p: updates.append(p))
    t.signals.finished.connect(lambda: finished.append(1))
    t.run()
    assert updates[-1][0] == "unknown"
    assert len(finished) == 1


def test_tracker_stop_event(monkeypatch):
    # panel closed: no polls, no update, but finished fires exactly once
    h = TrackerHarness(monkeypatch, [("running", "")], deadline=60)
    h.tracker._stop.set()
    updates, finished = h.run()
    assert h.provider.polls == 0
    assert updates == []
    assert finished == 1
    assert h.provider.closed_times == 1
