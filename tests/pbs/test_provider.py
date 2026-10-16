"""Tests for virtdeck.pbs.provider — typed facade over PbsClient."""
from __future__ import annotations

import pytest

from virtdeck.pbs.client import PbsError
from virtdeck.pbs.provider import PbsProvider


class FakeClient:
    def __init__(self):
        self.calls = []

    def datastores(self):
        self.calls.append("datastores")
        return [{"store": "main", "path": "/d1"}, {"store": "alt"}]

    def datastore_status(self, store):
        self.calls.append(f"status:{store}")
        if store == "alt":
            raise PbsError("boom", 500)
        return {"usage": 0.5, "used": 5, "total": 10}

    def namespaces(self, store, parent=""):
        self.calls.append(f"ns:{store}:{parent}")
        return [{"ns": "t1"}, {"ns": "t1"}, {"ns": "t2"}, {}]

    def snapshots(self, store, ns=""):
        self.calls.append(f"snap:{store}:{ns}")
        if ns == "":
            return [
                {"backup-type": "vm", "backup-id": "100", "backup-time": 1700000000},
                {"backup-type": "ct", "backup-id": "7", "backup-time": 1700000100},
            ]
        return []

    def jobs(self, kind):
        self.calls.append(f"jobs:{kind}")
        if kind == "verify":
            raise PbsError("no verify jobs", 404)
        return [{"id": f"{kind}-1", "store": "main"}]

    def run_job(self, kind, job_id):
        self.calls.append(f"run:{kind}:{job_id}")
        return "UPID:r"

    def verify_datastore(self, store):
        self.calls.append(f"verify:{store}")
        return "UPID:v"

    def forget_snapshot(self, store, backup_type, backup_id, backup_time, ns=""):
        self.calls.append(f"forget:{store}:{backup_type}/{backup_id}:{ns}")
        return None


def make_provider():
    p = PbsProvider({"host": "h", "user": "u", "token_value": "x"})
    p._client = FakeClient()
    return p


class TestDatastores:
    def test_datastores_combined(self):
        p = make_provider()
        stores = p.datastores()
        assert [s.name for s in stores] == ["main", "alt"]
        assert stores[0].usage == 0.5
        assert stores[0].path == "/d1"
        assert stores[0].status_ok is True
        # second store's status call raised → status unreadable, NOT zero (D1)
        assert stores[1].usage == 0.0
        assert stores[1].status_ok is False
        assert "status:broken" not in p._client.calls
        assert "status:alt" in p._client.calls

    def test_datastores_empty_status_response_is_unconfirmed(self):
        p = make_provider()
        p._client.datastore_status = lambda store: {}  # e.g. data: null
        stores = p.datastores()
        assert stores[0].status_ok is False

    def test_datastores_timeout_status_is_unconfirmed(self):
        # network/timeout failures raise PbsError too — same honesty rule
        p = make_provider()

        def timeout_status(store):
            raise PbsError("PBS timeout: read timed out")

        p._client.datastore_status = timeout_status
        stores = p.datastores()
        assert stores[0].usage == 0.0  # placeholder, not a confirmed zero
        assert stores[0].status_ok is False

    def test_namespaces_dedup_and_skip_empty(self):
        p = make_provider()
        assert p.namespaces("main") == ["t1", "t2"]


class TestSnapshots:
    def test_snapshots_parsed(self):
        p = make_provider()
        snaps = p.snapshots("main")
        assert [s.group for s in snaps] == ["vm/100", "ct/7"]
        assert all(s.store == "main" for s in snaps)

    def test_snapshots_ns_passthrough(self):
        p = make_provider()
        assert p.snapshots("main", ns="t1") == []


class TestJobs:
    def test_jobs_reports_failed_kind(self):
        # D10: a kind that cannot be read is reported in failed_kinds,
        # not silently dropped (it must not look like "no such jobs")
        p = make_provider()
        jobs, failed = p.jobs()
        assert [(j.kind, j.id) for j in jobs] == [
            ("sync", "sync-1"), ("prune", "prune-1"),
        ]
        assert failed == ["verify"]
        assert "jobs:verify" in p._client.calls

    def test_jobs_empty_success_is_valid(self):
        # D10: an empty list with no failures stays a legitimate
        # "no jobs" answer — not every empty result is an error
        p = make_provider()
        p._client.jobs = lambda kind: []
        assert p.jobs() == ([], [])

    def test_jobs_all_kinds_fail_raises(self):
        # D10: when no kind can be read, the error must surface —
        # an empty list must not masquerade as "no jobs"
        p = make_provider()

        def boom(kind):
            raise PbsError("boom", 500)

        p._client.jobs = boom
        with pytest.raises(PbsError, match="could not read jobs"):
            p.jobs()

    def test_run_job(self):
        p = make_provider()
        assert p.run_job("sync", "s1") == "UPID:r"

    def test_verify_datastore(self):
        p = make_provider()
        assert p.verify_datastore("main") == "UPID:v"

    def test_forget_snapshot(self):

        from virtdeck.domain.pbs import PbsSnapshot

        p = make_provider()
        snap = PbsSnapshot.from_api("main", {
            "backup-type": "vm", "backup-id": "100",
            "backup-time": 1700000000, "ns": "t1",
        })
        p.forget_snapshot(snap)
        assert p._client.calls == ["forget:main:vm/100:t1"]

    def test_forget_snapshot_without_time_raises(self):
        from virtdeck.domain.pbs import PbsSnapshot

        p = make_provider()
        snap = PbsSnapshot(store="main", backup_type="vm", backup_id="1")
        with pytest.raises(PbsError, match="no valid backup time"):
            p.forget_snapshot(snap)


# ── audit 6.3.3 D16: task status mapping (PBS tasks.rs contract) ───────


class FakeTaskClient:
    """Scripted client for provider.task_status()."""

    def __init__(self, statuses=None, node="pbs1", fail_times=0,
                 fail_code=404):
        self._statuses = list(statuses or [])
        self._node = node
        self.fail_times = fail_times
        self.fail_code = fail_code
        self.calls = []
        self.node_calls = 0
        self.forgot = 0

    def node_name(self):
        self.node_calls += 1
        self.calls.append(f"node:{self._node}")
        return self._node

    def forget_node(self):
        self.forgot += 1

    def task_status(self, node, upid):
        self.calls.append(f"status:{node}:{upid}")
        if self.fail_times > 0:
            self.fail_times -= 1
            raise PbsError(f"PBS API error (HTTP {self.fail_code})",
                           self.fail_code)
        return self._statuses.pop(0)


def _task_provider(client):
    p = make_provider()
    p._client = client
    return p


class TestTaskStatus:
    def test_running(self):
        p = _task_provider(FakeTaskClient([{"status": "running"}]))
        assert p.task_status("UPID:x") == ("running", "")
        assert "status:pbs1:UPID:x" in p._client.calls

    def test_stopped_ok_is_success(self):
        p = _task_provider(FakeTaskClient(
            [{"status": "stopped", "exitstatus": "OK"}]))
        assert p.task_status("UPID:x") == ("success", "")

    def test_stopped_error_is_failed_with_detail(self):
        p = _task_provider(FakeTaskClient(
            [{"status": "stopped", "exitstatus": "Error: verify failed"}]))
        state, detail = p.task_status("UPID:x")
        assert state == "failed"
        assert detail == "Error: verify failed"

    def test_stopped_without_exitstatus_is_unknown(self):
        # stopped but exit status unreadable — do not guess (never a
        # fake success, never the task's own failure)
        p = _task_provider(FakeTaskClient([{"status": "stopped"}]))
        assert p.task_status("UPID:x")[0] == "unknown"

    def test_stopped_unknown_exitstatus_is_unknown(self):
        p = _task_provider(FakeTaskClient(
            [{"status": "stopped", "exitstatus": "unknown"}]))
        assert p.task_status("UPID:x")[0] == "unknown"

    def test_odd_shape_is_read_failure(self):
        # a response without a status field is unreadable — it must be
        # a retryable read error, not a terminal verdict
        p = _task_provider(FakeTaskClient([{"nope": 1}]))
        with pytest.raises(PbsError):
            p.task_status("UPID:x")

    def test_node_resolution_uses_client(self):
        p = _task_provider(FakeTaskClient([{"status": "running"}]))
        p.task_status("UPID:x")
        assert p._client.node_calls == 1

    def test_stale_node_retried_once_after_404(self):
        # a stale cached node name must not kill tracking: forget the
        # cache, re-resolve, retry once (read-only, bounded)
        p = _task_provider(FakeTaskClient(
            [{"status": "running"}], fail_times=1, fail_code=404))
        state, _ = p.task_status("UPID:x")
        assert state == "running"
        assert p._client.forgot == 1
        assert p._client.node_calls == 2
        assert p._client.calls.count("status:pbs1:UPID:x") == 2

    def test_auth_error_is_not_swallowed(self):
        # 401/403 propagate — the tracker treats them as "unreadable",
        # not as the task's own failure
        p = _task_provider(FakeTaskClient([], fail_times=1, fail_code=403))
        with pytest.raises(PbsError) as exc:
            p.task_status("UPID:x")
        assert exc.value.status_code == 403
