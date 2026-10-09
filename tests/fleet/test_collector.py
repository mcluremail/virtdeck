"""M4.2: Fleet Health collector over the real provider and harness.

Checks the path "collect_cluster → provider → proxmoxer → fake":
fan-out across sources, partial-failure isolation, multi-cluster
merging (tests/harness — no sockets).
"""

from __future__ import annotations

import pytest

from tests.harness import fake_pve_cfg, install_fake_pve
from tests.harness.scenarios import make_pve_cluster
from virtdeck.domain.fleet import merge_fleet_reports
from virtdeck.fleet.collector import collect_cluster, collect_fleet
from virtdeck.provider import ProxmoxProvider

NOW = 1727830000


@pytest.fixture()
def alpha(monkeypatch):
    api = make_pve_cluster("alpha")
    install_fake_pve(monkeypatch, api)
    return api


def collect_alpha(monkeypatch=None, **kw):
    with ProxmoxProvider(fake_pve_cfg("alpha")) as provider:
        return collect_cluster(provider, name="alpha", now=NOW, **kw)


def test_happy_path_fanout(alpha):
    report = collect_alpha()
    assert report.complete and report.errors == ()
    assert report.generated_at == NOW
    # coverage via the real engine
    assert report.coverage.covered == frozenset({101, 102, 301})
    assert report.coverage.exempt == frozenset({201})
    # task history aggregated: 101 ok, 301 failed (no success yet)
    s101 = report.backup_states[101]
    assert s101.task_last_ok == 1727827200
    s301 = report.backup_states[301]
    assert s301.task_last_failed == 1727827400
    assert s301.ever_backed_up is False
    # both node versions collected (drift, M4.3): pveversion from status
    assert report.node_versions["pve01"].startswith("pve-manager/8.2.4")
    assert report.node_versions["pve02"].startswith("pve-manager/7.4.3")
    # storage usage tagged with its node
    assert {r["node"] for r in report.storage_usage} == {"pve01"}
    # fan-out reached every source
    paths = {c[1] for c in alpha.calls}
    assert {"/cluster/resources", "/cluster/backup", "/cluster/tasks",
            "/nodes/pve01/status", "/nodes/pve02/status",
            "/nodes/pve01/storage"} <= paths


def test_partial_failure_version_node(alpha):
    # pveversion from status with /version fallback — both must fail
    alpha.fail["nodes/pve02/status"] = (500, "disk full")
    alpha.fail["nodes/pve02/version"] = (500, "disk full")
    report = collect_alpha()
    assert not report.complete
    assert [(e.source, e.cluster) for e in report.errors] \
        == [("version:pve02", "alpha")]
    assert "pve01" in report.node_versions
    assert "pve02" not in report.node_versions
    # other sources untouched
    assert report.coverage is not None


def test_partial_failure_storage_node(alpha):
    alpha.fail["nodes/pve01/storage"] = (500, "boom")
    report = collect_alpha()
    assert not report.complete
    assert report.errors[0].source == "storage:pve01"
    assert report.node_versions  # versions collected


def test_failed_resources_no_coverage_but_tasks_alive(alpha):
    alpha.fail["cluster/resources"] = (500, "boom")
    report = collect_alpha()
    assert not report.complete
    assert report.coverage is None
    assert report.guests == ()
    # nodes unknown → per-node fan-out skipped without new errors
    assert len(report.errors) == 1
    # tasks — independent source
    assert 101 in report.backup_states


def test_whole_cluster_down(monkeypatch):
    """Host fully unreachable: all sources in errors, empty report."""
    alpha = make_pve_cluster("alpha")
    install_fake_pve(monkeypatch, alpha)
    with ProxmoxProvider(fake_pve_cfg("gamma")) as provider:
        report = collect_cluster(provider, name="gamma", now=NOW)
    assert not report.complete
    sources = {e.source for e in report.errors}
    assert {"resources", "backup_jobs", "tasks"} <= sources
    assert report.coverage is None and report.guests == ()


def test_pbs_enrichment(alpha):
    report = collect_alpha(pbs_last_backups={("vm", "101"): 1727827200})
    s101 = report.backup_states[101]
    assert s101.pbs_last_ok == 1727827200
    s301 = report.backup_states[301]
    assert s301.pbs_last_ok is None  # lxc guest absent from the PBS mapping


def test_task_history_truncation_flag(alpha):
    """Exactly at the fetch limit the report must carry the flag: the
    window may have cut off older successful backups (P0 honesty)."""
    from virtdeck.fleet.collector import TASK_HISTORY_LIMIT
    for i in range(TASK_HISTORY_LIMIT):
        alpha.add_task("pve01", f"UPID:pve01:1:2:67000000:apt:update{i}:root@pam:",
                       task_type="aptupdate", starttime=NOW - i)
    report = collect_alpha()
    assert report.tasks_truncated
    assert len(report.backup_states) >= 0  # no crash on non-vzdump rows


def test_collect_fleet_merge(monkeypatch):
    alpha = make_pve_cluster("alpha")
    beta = make_pve_cluster("beta")
    install_fake_pve(monkeypatch, alpha, beta)
    providers = {}
    for name in ("alpha", "beta"):
        providers[name] = ProxmoxProvider(fake_pve_cfg(name))
    try:
        reports = collect_fleet(providers, now=NOW)
    finally:
        for p in providers.values():
            p.close()
    fleet = merge_fleet_reports(reports)
    assert fleet.complete
    assert fleet.generated_at == NOW
    assert [c.cluster for c in fleet.clusters] == ["alpha", "beta"]
    # cluster isolation: each has its own guests and states
    for cluster in fleet.clusters:
        assert {g.vmid for g in cluster.guests} == {101, 102, 201, 301}
        assert cluster.backup_states[301].task_last_failed == 1727827400
