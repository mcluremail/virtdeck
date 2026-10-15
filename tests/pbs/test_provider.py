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
    def test_jobs_swallows_kind_errors(self):
        p = make_provider()
        jobs = p.jobs()
        assert [(j.kind, j.id) for j in jobs] == [
            ("sync", "sync-1"), ("prune", "prune-1"),
        ]
        assert "jobs:verify" in p._client.calls

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
