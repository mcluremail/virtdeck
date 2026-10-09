"""M4.1: table-driven tests for the backup compliance matching engine.

The engine is the trickiest part of Fleet Health (B24): false
positives/negatives break trust from the first run. Each case pins one
vzdump semantics rule (see the ``backup_coverage`` docmodule):
all>pool>vmid, exclude only with all, templates outside the report,
a disabled job covers nobody, job overlaps allowed, duplicate vmid — first wins.
"""

from __future__ import annotations

import pytest

from virtdeck.domain.backup_coverage import (
    BackupJob,
    Guest,
    compute_coverage,
)


def g(vmid: int, *, pool: str = "", template: bool = False,
      vm_type: str = "qemu", node: str = "n1", name: str = "") -> Guest:
    return Guest(vmid=vmid, name=name, node=node, vm_type=vm_type,
                 pool=pool, template=template)


def j(job_id: str, *, enabled: bool = True, all_vms: bool = False,
      vmids=(), exclude=(), pool: str = "", node: str = "",
      schedule: str = "daily", storage: str = "pbs1") -> BackupJob:
    return BackupJob(job_id=job_id, enabled=enabled, all_vms=all_vms,
                     vmids=frozenset(vmids), exclude=frozenset(exclude),
                     pool=pool, node=node, schedule=schedule,
                     storage=storage)


# Scene: 2 nodes, qemu+lxc, a template, two pools.
SCENE = [
    g(101, pool="prod"),
    g(102),
    g(201, template=True),
    g(301, pool="prod", vm_type="lxc", node="n2"),
]

# (case name, jobs, covered, uncovered, exempt)
COVERAGE_CASES = [
    ("no_jobs_all_uncovered", [],
     set(), {101, 102, 301}, {201}),
    ("all_job_covers_all_nodes_and_types",
     [j("bz-all", all_vms=True)],
     {101, 102, 301}, set(), {201}),
    ("all_plus_exclude",
     [j("bz-all", all_vms=True, exclude=[201, 301])],
     {101, 102}, {301}, {201}),
    ("exclude_without_all_ignored",
     [j("bz-list", vmids=[101], exclude=[101])],
     {101}, {102, 301}, {201}),
    ("pool_job_includes_stopped_cross_node",
     [j("bz-pool", pool="prod")],
     {101, 301}, {102}, {201}),
    ("vmid_job",
     [j("bz-list", vmids=[102])],
     {102}, {101, 301}, {201}),
    ("priority_all_over_pool_and_vmid",
     [j("bz", all_vms=True, pool="prod", vmids=[102])],
     {101, 102, 301}, set(), {201}),
    ("disabled_job_no_coverage",
     [j("bz-list", vmids=[102], enabled=False),
      j("bz-pool", pool="prod", enabled=False)],
     set(), {101, 102, 301}, {201}),
    ("malformed_job_selects_nothing",
     [j("bz-empty", schedule="daily")],
     set(), {101, 102, 301}, {201}),
    ("template_listed_in_vmid_still_exempt",
     [j("bz-list", vmids=[102, 201])],
     {102}, {101, 301}, {201}),
    ("node_restricted_all_job_covers_only_that_node",
     [j("bz-n1", all_vms=True, node="n1")],
     {101, 102}, {301}, {201}),
    ("node_restricted_pool_job_cross_node_uncovered",
     [j("bz-n2", pool="prod", node="n2")],
     {301}, {101, 102}, {201}),
]


@pytest.mark.parametrize(
    ("jobs", "covered", "uncovered", "exempt"),
    [(c[1], c[2], c[3], c[4]) for c in COVERAGE_CASES],
    ids=[c[0] for c in COVERAGE_CASES],
)
def test_coverage_table(jobs, covered, uncovered, exempt):
    cov = compute_coverage(jobs, SCENE)
    assert cov.covered == frozenset(covered)
    assert cov.uncovered == frozenset(uncovered)
    assert cov.exempt == frozenset(exempt)


def test_pool_migration_recomputed_fresh():
    """The VM moved between pools between runs — the engine is stateless,
    a run over fresh resources gives the current answer (B24)."""
    migrated = [g(101, pool="staging")]
    cov = compute_coverage([j("bz-pool", pool="prod")], migrated)
    assert cov.uncovered == frozenset({101})


def test_overlap_multiple_jobs_both_listed():
    jobs = [j("bz-all", all_vms=True), j("bz-pool", pool="prod"),
            j("bz-list", vmids=[101])]
    cov = compute_coverage(jobs, SCENE)
    assert cov.by_guest[101] == ("bz-all", "bz-list", "bz-pool")
    assert cov.by_guest[102] == ("bz-all",)


def test_by_job_includes_empty_enabled_job():
    cov = compute_coverage(
        [j("bz-list", vmids=[999]), j("bz-empty")], SCENE)
    assert cov.by_job["bz-list"] == frozenset()
    assert cov.by_job["bz-empty"] == frozenset()


def test_disabled_job_absent_from_by_job():
    cov = compute_coverage([j("bz-off", enabled=False)], SCENE)
    assert "bz-off" not in cov.by_job


def test_disjoint_and_total():
    cov = compute_coverage(
        [j("bz-pool", pool="prod"), j("bz-list", vmids=[102])], SCENE)
    assert not (cov.covered & cov.uncovered)
    assert not (cov.covered & cov.exempt)
    assert cov.covered | cov.uncovered | cov.exempt \
        == frozenset({101, 102, 201, 301})


def test_duplicate_vmid_first_wins():
    guests = [g(101, pool="prod"), g(101, pool="other")]
    cov = compute_coverage([j("bz-pool", pool="other")], guests)
    assert cov.uncovered == frozenset({101})


def test_empty_scene():
    cov = compute_coverage([j("bz-all", all_vms=True)], [])
    assert cov.covered == frozenset()
    assert cov.uncovered == frozenset()
    assert cov.exempt == frozenset()
    assert cov.by_job == {"bz-all": frozenset()}
    assert cov.by_guest == {}


class TestBackupJobFromRaw:
    """Parsing GET /cluster/backup: PVE types (0/1, string lists)."""

    def test_full_raw(self):
        job = BackupJob.from_raw({"id": "bz-1", "enabled": 1, "all": 1,
                                  "exclude": "101, 102", "vmid": "",
                                  "schedule": "02:30", "storage": "pbs1"})
        assert job == BackupJob(job_id="bz-1", all_vms=True,
                                exclude=frozenset({101, 102}),
                                schedule="02:30", storage="pbs1")

    def test_node_parsed_and_restricts(self):
        job = BackupJob.from_raw({"id": "bz-n", "all": 1, "node": "pve01"})
        assert job.node == "pve01"
        # node-restricted job never reaches guests on other nodes
        assert job.selects(Guest(vmid=1, node="pve01"))
        assert not job.selects(Guest(vmid=2, node="pve02"))

    def test_vmid_list_with_spaces_and_garbage(self):
        job = BackupJob.from_raw({"id": "x", "vmid": "101, 103, abc, , 105"})
        assert job.vmids == frozenset({101, 103, 105})

    def test_defaults_missing_fields(self):
        job = BackupJob.from_raw({"id": "x"})
        assert job.enabled and not job.all_vms
        assert job.vmids == frozenset() and job.exclude == frozenset()
        assert job.pool == "" and job.schedule == "" and job.storage == ""

    def test_enabled_zero_and_string_variants(self):
        assert not BackupJob.from_raw({"id": "x", "enabled": 0}).enabled
        assert BackupJob.from_raw({"id": "x", "enabled": "1"}).enabled


class TestGuestFromRaw:
    """Parsing /cluster/resources: non-guests and broken vmids → None."""

    def test_from_resources_row(self):
        guest = Guest.from_raw({"type": "qemu", "vmid": 101, "name": "web",
                                "node": "pve01", "pool": "prod",
                                "template": 0})
        assert guest == Guest(101, "web", "pve01", "qemu", "prod", False)

    def test_template_truthy_variants(self):
        assert Guest.from_raw({"type": "lxc", "vmid": 5, "template": 1}) \
            .template
        assert Guest.from_raw({"type": "lxc", "vmid": 5, "template": True}) \
            .template
        assert not Guest.from_raw({"type": "lxc", "vmid": 5}).template

    def test_non_guest_rows_none(self):
        assert Guest.from_raw({"type": "node", "node": "pve01"}) is None
        assert Guest.from_raw({"type": "storage", "storage": "local"}) is None
        assert Guest.from_raw({"type": "sdn", "vnet": "vn1"}) is None

    def test_missing_or_bad_vmid_none(self):
        assert Guest.from_raw({"type": "qemu"}) is None
        assert Guest.from_raw({"type": "qemu", "vmid": "abc"}) is None
