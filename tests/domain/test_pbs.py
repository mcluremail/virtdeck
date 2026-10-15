"""Tests for virtdeck.domain.pbs — PBS domain models parsing."""
from datetime import datetime

from virtdeck.domain.pbs import PbsDatastore, PbsJob, PbsSnapshot, _verify_state


class TestVerifyState:
    def test_ok(self):
        assert _verify_state("ok") == "ok"

    def test_failed(self):
        assert _verify_state("failed") == "failed"

    def test_none(self):
        assert _verify_state(None) == "none"

    def test_unknown_value(self):
        assert _verify_state("pending") == "none"


class TestPbsDatastore:
    def test_build_from_config_and_status(self):
        ds = PbsDatastore.build(
            {"store": "main", "path": "/mnt/main", "comment": "primary"},
            {"usage": 0.755, "used": 755 * 10**9, "total": 1000 * 10**9},
        )
        assert ds.name == "main"
        assert ds.path == "/mnt/main"
        assert ds.comment == "primary"
        assert ds.usage == 0.755
        assert ds.used_bytes == 755 * 10**9
        assert ds.total_bytes == 1000 * 10**9
        assert ds.status_ok is True

    def test_build_defaults(self):
        ds = PbsDatastore.build({"name": "alt"})
        assert ds.name == "alt"
        assert ds.path == ""
        assert ds.usage == 0.0
        assert ds.used_bytes == 0
        assert ds.total_bytes == 0
        # no status response → numbers are placeholders, not data (D1)
        assert ds.status_ok is False

    def test_build_none_status_marks_unavailable(self):
        ds = PbsDatastore.build({"name": "alt"}, None)
        assert ds.status_ok is False
        assert ds.usage == 0.0
        assert ds.usage_pct() == 0  # no exception on missing data

    def test_build_empty_status_marks_unavailable(self):
        ds = PbsDatastore.build({"name": "alt"}, {})
        assert ds.status_ok is False

    def test_build_non_dict_status_marks_unavailable(self):
        assert PbsDatastore.build({"name": "x"}, ["bad"]).status_ok is False

    def test_build_partial_status_marks_unavailable(self):
        # usage alone is not a confirmed (usage, used, total) triple
        ds = PbsDatastore.build({"name": "x"}, {"usage": 0.5, "used": 5})
        assert ds.status_ok is False

    def test_build_zero_status_is_confirmed(self):
        # a successful response with genuine zeros stays a zero (D1)
        ds = PbsDatastore.build({"name": "x"}, {"usage": 0.0, "used": 0,
                                                "total": 0})
        assert ds.status_ok is True
        assert ds.usage == 0.0
        assert ds.used_bytes == 0

    def test_status_ok_default_true_for_direct_construction(self):
        assert PbsDatastore(name="x").status_ok is True

    def test_usage_pct_rounds(self):
        assert PbsDatastore(name="x", usage=0.754).usage_pct() == 75
        assert PbsDatastore(name="x", usage=0.999).usage_pct() == 100


class TestPbsSnapshot:
    def test_from_api_full(self):
        ts = 1700000000
        snap = PbsSnapshot.from_api("main", {
            "backup-type": "vm", "backup-id": "100",
            "backup-time": ts, "owner": "root@pam",
            "verify-state": "ok", "size": 42 * 10**9, "comment": "daily",
        })
        assert snap.store == "main"
        assert snap.ns == ""
        assert snap.backup_type == "vm"
        assert snap.backup_id == "100"
        assert snap.backup_time == datetime.fromtimestamp(ts)
        assert snap.owner == "root@pam"
        assert snap.verify == "ok"
        assert snap.size_bytes == 42 * 10**9
        assert snap.group == "vm/100"
        assert snap.snapshot_id == f"vm/100/{datetime.fromtimestamp(ts):%Y-%m-%dT%H:%M:%S}"

    def test_from_api_namespace_and_missing_fields(self):
        snap = PbsSnapshot.from_api("store2", {
            "backup-type": "ct", "backup-id": "7",
            "backup-time": "1700000000", "ns": "tenant1",
            "verify-state": "failed",
        })
        assert snap.ns == "tenant1"
        assert snap.backup_time == datetime.fromtimestamp(1700000000)
        assert snap.verify == "failed"
        assert snap.owner == ""
        assert snap.size_bytes == 0
        assert snap.group == "ct/7"

    def test_from_api_bad_time(self):
        snap = PbsSnapshot.from_api("main", {
            "backup-type": "vm", "backup-id": "1",
            "backup-time": "not-a-number",
        })
        assert snap.backup_time is None
        assert snap.snapshot_id == "vm/1/"

    def test_verify_state_default(self):
        snap = PbsSnapshot.from_api("main", {"backup-id": "1"})
        assert snap.verify == "none"


class TestPbsJob:
    def test_from_api_sync(self):
        job = PbsJob.from_api("sync", {
            "id": "s1", "store": "main", "schedule": "daily",
            "comment": "c", "disable": True,
        })
        assert job.id == "s1"
        assert job.kind == "sync"
        assert job.store == "main"
        assert job.schedule == "daily"
        assert job.disabled is True

    def test_from_api_defaults(self):
        job = PbsJob.from_api("verify", {})
        assert job.id == ""
        assert job.kind == "verify"
        assert job.disabled is False

    def test_from_api_prune_enable_key(self):
        job = PbsJob.from_api("prune", {"id": "p", "disable": False})
        assert job.disabled is False
