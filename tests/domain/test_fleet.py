"""M4.2: pure Fleet Health aggregation — tables and invariants.

Sources: task history (vzdump tasks) and optional PBS mapping.
Partial failure: a failed source (None) must not fake coverage.
"""

from __future__ import annotations

import pytest

from virtdeck.domain.backup_coverage import Guest
from virtdeck.domain.fleet import (
    ClusterFleetReport,
    CollectError,
    build_backup_states,
    build_cluster_report,
    last_pbs_backup_times,
    merge_fleet_reports,
)


def upid(vmid: int, start_hex: str, node: str = "pve01") -> str:
    return f"UPID:{node}:00000001:00000000:{start_hex}:vzdump:{vmid}:root@pam:"


def guest(vmid: int, vm_type: str = "qemu", pool: str = "") -> Guest:
    return Guest(vmid=vmid, vm_type=vm_type, pool=pool)


def res(vmid: int, node: str = "n1", pool: str = "", template: int = 0,
        gtype: str = "qemu") -> dict:
    return {"type": gtype, "vmid": vmid, "name": f"g{vmid}", "node": node,
            "pool": pool, "template": template}


def job_raw(job_id: str, **kw) -> dict:
    base = {"id": job_id, "enabled": 1, "schedule": "daily",
            "storage": "pbs1"}
    base.update(kw)
    return base


def state_of(states, vmid):
    return states.get(vmid)


class TestBackupStatesFromTasks:
    def test_ok_task(self):
        states = build_backup_states(
            [{"upid": upid(101, "0000003c"), "type": "vzdump",
              "status": "OK"}],
            [guest(101)], {})
        s = state_of(states, 101)
        assert s.task_last_ok == 60          # hex slot of the UPID
        assert s.task_last_attempt == 60
        assert s.task_last_failed is None
        assert s.last_successful == 60
        assert s.ever_backed_up

    def test_failed_after_ok(self):
        tasks = [
            {"upid": upid(101, "00000064"), "type": "vzdump",
             "status": "OK", "starttime": 1727827200},
            {"upid": upid(101, "000000c8"), "type": "vzdump",
             "status": "stopped: exit code 1", "starttime": 1727913600},
        ]
        s = state_of(build_backup_states(tasks, [guest(101)], {}), 101)
        assert s.task_last_ok == 1727827200      # row field is an int
        assert s.task_last_failed == 1727913600
        assert s.task_last_attempt == 1727913600
        assert s.last_successful == 1727827200

    def test_running_task_counts_as_attempt_only(self):
        tasks = [{"upid": upid(101, "00000064"), "type": "vzdump",
                  "status": None, "starttime": 1727827200}]
        s = state_of(build_backup_states(tasks, [guest(101)], {}), 101)
        assert s.task_last_attempt == 1727827200
        assert s.task_last_ok is None
        assert s.ever_backed_up is False

    def test_non_vzdump_ignored(self):
        tasks = [{"upid": upid(101, "00000064").replace("vzdump", "vzrestore"),
                  "type": "vzrestore", "status": "OK"}]
        states = build_backup_states(tasks, [guest(101)], {})
        assert states[101].task_last_ok is None

    def test_vmid_zero_and_garbage_skipped(self):
        tasks = [
            {"upid": upid(0, "00000064"), "type": "vzdump", "status": "OK"},
            {"upid": "broken", "type": "vzdump", "status": "OK"},
        ]
        states = build_backup_states(tasks, [], {})
        assert states == {}

    def test_orphan_task_vmid_kept(self):
        """Guest removed between runs, tasks remain — state persists."""
        states = build_backup_states(
            [{"upid": upid(101, "00000064"), "type": "vzdump",
              "status": "OK"}], [], {})
        assert 101 in states


class TestBuildBackupStatesWithPbs:
    def test_pbs_newer_than_task(self):
        tasks = [{"upid": upid(101, "00000064"), "type": "vzdump",
                  "status": "OK", "starttime": 1727827200}]
        states = build_backup_states(tasks, [guest(101)],
                                     {("vm", "101"): 1727913600})
        s = states[101]
        assert s.task_last_ok == 1727827200
        assert s.pbs_last_ok == 1727913600
        assert s.last_successful == 1727913600

    def test_pbs_only_guest_without_tasks(self):
        states = build_backup_states([], [guest(101), guest(102)],
                                     {("vm", "102"): 1727827200})
        assert states[101].ever_backed_up is False
        assert states[102].last_successful == 1727827200

    def test_lxc_pbs_type(self):
        states = build_backup_states([], [guest(301, vm_type="lxc")],
                                     {("lxc", "301"): 1727827200})
        assert states[301].pbs_last_ok == 1727827200


class TestLastPbsBackupTimes:
    def test_picks_max_per_key(self):
        snaps = [{"backup-type": "vm", "backup-id": "101",
                  "backup-time": 1727740800},
                 {"backup-type": "vm", "backup-id": "101",
                  "backup-time": 1727827200}]
        assert last_pbs_backup_times(snaps) == {("vm", "101"): 1727827200}

    def test_failed_verify_excluded(self):
        snaps = [{"backup-type": "vm", "backup-id": "101",
                  "backup-time": 1727827200, "verify-state": "failed"},
                 {"backup-type": "vm", "backup-id": "101",
                  "backup-time": 1727740800, "verify-state": "ok"}]
        assert last_pbs_backup_times(snaps) == {("vm", "101"): 1727740800}

    def test_unverified_counted(self):
        for state in ("none", "", None):
            snaps = [{"backup-type": "vm", "backup-id": "9",
                      "backup-time": 1727827200, "verify-state": state}]
            assert last_pbs_backup_times(snaps) == {("vm", "9"): 1727827200}

    def test_empty_and_garbage(self):
        assert last_pbs_backup_times([]) == {}
        assert last_pbs_backup_times([{"backup-id": ""}]) == {}
        assert last_pbs_backup_times(
            [{"backup-type": "vm", "backup-id": "1",
              "backup-time": "soon"}]) == {}


def make_cluster_report(cluster: str = "alpha", **kw) -> ClusterFleetReport:
    kwargs = {
        "cluster": cluster,
        "generated_at": 1727827200,
        "resources": [res(101, pool="prod"), res(102), res(201, template=1)],
        "backup_jobs": [job_raw("bz-all", all=1, exclude="")],
        "tasks": [{"upid": upid(101, "00000064"), "type": "vzdump",
                   "status": "OK", "starttime": 1727827200}],
        "node_versions": {"n1": "pve-manager/8.2.4/x"},
        "storage_usage": [{"node": "n1", "storage": "local",
                           "total": 100, "used": 80}],
    }
    kwargs.update(kw)
    return build_cluster_report(**kwargs)


class TestBuildClusterReport:
    def test_happy_path(self):
        report = make_cluster_report()
        assert report.complete
        assert report.errors == ()
        assert report.coverage is not None
        assert report.coverage.covered == frozenset({101, 102})
        assert report.coverage.uncovered == frozenset()
        assert report.coverage.exempt == frozenset({201})
        assert report.backup_states[101].task_last_ok == 1727827200
        assert report.node_versions["n1"].startswith("pve-manager/8.2.4")
        assert report.storage_usage[0]["storage"] == "local"

    def test_failed_resources_no_false_coverage(self):
        """resources failed → no coverage at all (no false report)."""
        report = make_cluster_report(resources=None,
                                     errors=(CollectError(
                                         "alpha", "resources", "boom"),))
        assert not report.complete
        assert report.coverage is None
        assert report.guests == ()
        # tasks aggregated anyway: sources are independent
        assert 101 in report.backup_states

    def test_failed_jobs_no_false_coverage(self):
        report = make_cluster_report(
            backup_jobs=None,
            errors=(CollectError("alpha", "backup_jobs", "boom"),))
        assert report.coverage is None
        assert report.guests  # guests still collected


class TestMergeFleetReports:
    def test_merge_min_generated_at_and_errors(self):
        alpha = make_cluster_report("alpha")
        beta = make_cluster_report(
            "beta", generated_at=1727827100,
            errors=(CollectError("beta", "tasks", "boom"),))
        fleet = merge_fleet_reports([alpha, beta])
        assert fleet.generated_at == 1727827100  # honest "data as of"
        assert not fleet.complete
        assert fleet.errors == beta.errors
        assert [c.cluster for c in fleet.clusters] == ["alpha", "beta"]

    def test_merge_empty(self):
        fleet = merge_fleet_reports([])
        assert fleet.generated_at == 0
        assert fleet.complete

    @pytest.mark.parametrize("reports", [
        pytest.param([], id="empty"),
        pytest.param([make_cluster_report("a")], id="ok"),
    ])
    def test_complete_only_when_all_complete(self, reports):
        assert merge_fleet_reports(reports).complete
