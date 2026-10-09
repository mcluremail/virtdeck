"""M4.5: Fleet Health — report rendering, partial failure, navigation,
worker.

The transport is swapped by the harness: the dialog builds a real
report against a fake cluster through FleetHealthWorker (the real
provider + the fake adapter).
"""

from __future__ import annotations

import threading
from dataclasses import replace

import pytest
from PySide6.QtGui import QColor

from tests.harness import fake_pve_cfg, install_fake_pve
from tests.harness.scenarios import make_pve_cluster
from virtdeck.backend.fleet import (
    ClusterBundle,
    FleetHealthWorker,
    FleetTarget,
    build_fleet_targets,
)
from virtdeck.domain.backup_coverage import Guest
from virtdeck.domain.fleet import GuestBackupState, build_cluster_report
from virtdeck.fleet.runway import RunwayEstimate
from virtdeck.fleet.sprawl import scan_sprawl
from virtdeck.ui.fleet_health import KEY_ROLE, FleetHealthDialog
from virtdeck.ui.theme import Color

NOW = 1727830000


@pytest.fixture()
def api(monkeypatch):
    api = make_pve_cluster("alpha")
    install_fake_pve(monkeypatch, api)
    return api


def make_dialog(qtbot, names=("alpha",)) -> FleetHealthDialog:
    dlg = FleetHealthDialog(
        [FleetTarget(n, n, fake_pve_cfg(n)) for n in names])
    qtbot.addWidget(dlg)
    return dlg


def wait_loaded(qtbot, dlg) -> None:
    qtbot.waitUntil(
        lambda: dlg._worker is None and dlg._tree.topLevelItemCount() > 0,
        timeout=15000)


def walk_rows(tree):
    for i in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(i)
        for j in range(top.childCount()):
            section = top.child(j)
            for k in range(section.childCount()):
                yield section.child(k)


def _freeze_now(bundle: ClusterBundle) -> ClusterBundle:
    """Shift the report's generated_at to the scene NOW (determinism)."""
    return ClusterBundle(
        report=replace(bundle.report, generated_at=NOW),
        runway=bundle.runway)


def find_by_key(tree, key):
    for row in walk_rows(tree):
        if row.data(0, KEY_ROLE) == key:
            return row
    return None


def find_issue(tree, issue_text: str):
    for row in walk_rows(tree):
        if row.text(2) == issue_text:
            return row
    return None


def test_render_issues_and_status(qtbot, api):
    dlg = make_dialog(qtbot)
    wait_loaded(qtbot, dlg)
    # freeze the report time to the scene's (otherwise backup ages are in years)
    dlg._bundles = [_freeze_now(dlg._bundles[0])]
    dlg._render()
    # 301: task failed, no successes → red
    row = find_issue(dlg._tree, "Never backed up")
    assert row is not None
    assert row.text(1) == "cache01 (301)"
    assert row.data(0, KEY_ROLE) == ("alpha", 301, "pve02")
    assert row.foreground(2).color() == QColor(Color.DANGER)
    # drift: 7.4.3 vs 8.2.4 → major
    drift = find_issue(dlg._tree, "Behind by major version")
    assert drift is not None
    assert drift.text(1) == "pve02"
    assert drift.text(3) == "7.4.3"  # human-readable version, not a hash
    # the up-to-date node is visible in the same section — a neutral row
    ok = find_issue(dlg._tree, "Up to date")
    assert ok is not None
    assert ok.text(1) == "pve01"
    assert ok.text(3) == "8.2.4"
    assert ok.foreground(2).color() != QColor(Color.DANGER)
    # sections are expanded (otherwise rows are hidden), the cluster
    # column of rows is empty
    top = dlg._tree.topLevelItem(0)
    for j in range(top.childCount()):
        section = top.child(j)
        assert section.isExpanded()
        for k in range(section.childCount()):
            assert section.child(k).text(0) == ""
    # runway: the scene's rrddata grows → the local storage lands in the report
    assert find_issue(dlg._tree, "Storage filling up") is not None
    assert dlg._status.text() == "3 issues on 1 clusters"


def test_no_issues_status(qtbot, api):
    dlg = make_dialog(qtbot)
    wait_loaded(qtbot, dlg)
    dlg._bundles = []
    dlg._render()
    assert dlg._status.text() == "No issues found"


def test_data_from_plate_on_partial_failure(qtbot, api):
    # pveversion from status with a /version fallback — fail both on error
    api.fail["nodes/pve02/status"] = (500, "boom")
    api.fail["nodes/pve02/version"] = (500, "boom")
    dlg = make_dialog(qtbot)
    wait_loaded(qtbot, dlg)
    top = dlg._tree.topLevelItem(0)
    assert "Data from" in top.text(0)
    # data incompleteness — signal color of the cluster plate
    assert top.foreground(0).color() == QColor(Color.WARNING)
    # no drift row (pve02 version not collected), compliance alive
    assert find_issue(dlg._tree, "Behind by major version") is None
    assert find_issue(dlg._tree, "Never backed up") is not None


def test_data_unavailable_plate_and_incomplete_status(qtbot, monkeypatch):
    """Provider creation failed (unknown plugin type → generated_at=0):
    the cluster plate must not say "Data from 1970", and the status line
    must not say a bare "No issues found" while a cluster has no data."""
    alpha = make_pve_cluster("alpha")
    install_fake_pve(monkeypatch, alpha)
    dlg = FleetHealthDialog([
        FleetTarget("alpha", "alpha", fake_pve_cfg("alpha")),
        FleetTarget("ghost", "ghost",
                    {"name": "ghost", "type": "nosuchplugin"})])
    qtbot.addWidget(dlg)
    wait_loaded(qtbot, dlg)
    tops = [dlg._tree.topLevelItem(i)
            for i in range(dlg._tree.topLevelItemCount())]
    ghost = next(t for t in tops if t.text(0).startswith("ghost"))
    assert "Data unavailable" in ghost.text(0)
    assert "1970" not in ghost.text(0)
    assert "with incomplete data" in dlg._status.text()


def test_tasks_truncated_row(qtbot, api):
    from virtdeck.fleet.collector import TASK_HISTORY_LIMIT
    for i in range(TASK_HISTORY_LIMIT):
        api.add_task("pve01",
                     f"UPID:pve01:1:2:67000000:apt:u{i}:root@pam:",
                     task_type="aptupdate", starttime=NOW - i)
    dlg = make_dialog(qtbot)
    wait_loaded(qtbot, dlg)
    top = dlg._tree.topLevelItem(0)
    rows = [top.child(j) for j in range(top.childCount())]
    assert any(r.text(2) == "Task history truncated" for r in rows)
    # the caveat is not an issue: it must not inflate the counter
    assert "with incomplete data" not in dlg._status.text()


def test_cluster_job_run_covers_guests(qtbot, api):
    """A guest with no own task evidence but covered by an OK cluster-
    wide job run must not be reported as "never backed up" (P0)."""
    dlg = make_dialog(qtbot)
    wait_loaded(qtbot, dlg)
    report = dlg._bundles[0].report
    report2 = build_cluster_report(
        cluster=report.cluster, generated_at=NOW,
        resources=[{"type": "qemu", "vmid": 105, "name": "fresh",
                    "node": "pve01"}],
        backup_jobs=[{"id": "bz-all", "enabled": 1, "all": 1}],
        tasks=[{"upid": "UPID:pve01:00000009:00000000:67100000:"
                        "vzdump:bz-all:root@pam:",
                "type": "vzdump", "status": "OK",
                "starttime": NOW - 3600}])
    dlg._bundles = [ClusterBundle(report=report2, runway=())]
    dlg._render()
    assert find_issue(dlg._tree, "Never backed up") is None
    assert dlg._status.text() == "No issues found"


def test_object_navigation_signal(qtbot, api):
    dlg = make_dialog(qtbot)
    wait_loaded(qtbot, dlg)
    item = find_by_key(dlg._tree, ("alpha", 301, "pve02"))
    assert item is not None
    with qtbot.waitSignal(dlg.object_selected, timeout=2000) as blocker:
        dlg._activate_item(item)
    assert blocker.args == [("alpha", 301, "pve02")]


def test_runway_severity_colors(qtbot, api):
    dlg = make_dialog(qtbot)
    wait_loaded(qtbot, dlg)
    report = dlg._bundles[0].report

    def est(days: float, quality: str = "ok") -> RunwayEstimate:
        ci = quality == "ok"
        return RunwayEstimate(node="pve01", storage="local", used_bytes=80,
                              total_bytes=100, slope_bytes_per_day=1.0,
                              days_left=days,
                              days_left_low=days - 1 if ci else None,
                              days_left_high=days + 1 if ci else None,
                              points_used=48, quality=quality)

    dlg._bundles = [ClusterBundle(report=report, runway=(est(5.0),))]
    dlg._render()
    row = find_issue(dlg._tree, "Storage filling up")
    assert row.foreground(2).color() == QColor(Color.DANGER)
    assert "~4–6 days left" in row.text(3)

    # sparse history: point estimate without CI — cautious wording (B24)
    dlg._bundles = [ClusterBundle(report=report, runway=(est(5.0, "sparse"),))]
    dlg._render()
    row = find_issue(dlg._tree, "Storage filling up")
    assert row.foreground(2).color() == QColor(Color.DANGER)
    assert "rough estimate" in row.text(3)

    dlg._bundles = [ClusterBundle(report=report, runway=(est(20.0),))]
    dlg._render()
    row = find_issue(dlg._tree, "Storage filling up")
    assert row.foreground(2).color() == QColor(Color.WARNING)

    dlg._bundles = [ClusterBundle(report=report, runway=(est(100.0),))]
    dlg._render()
    assert find_issue(dlg._tree, "Storage filling up") is None


def test_sprawl_section_after_scan(qtbot, api):
    dlg = make_dialog(qtbot)
    wait_loaded(qtbot, dlg)
    dlg._bundles = [_freeze_now(dlg._bundles[0])]
    snaps = {101: [{"name": "old", "snaptime": NOW - 45 * 86400}],
             102: [{"name": "zombie"}]}
    dlg._scans = {"alpha": scan_sprawl(snaps, [
        Guest(101, "web01", "pve01", "qemu"),
        Guest(102, "db01", "pve01", "qemu")], now=NOW)}
    dlg._render()
    fresh = find_by_key(dlg._tree, ("alpha", 101, "pve01"))
    assert fresh is not None
    assert fresh.text(2) == "1 snapshots, oldest 45 days"
    assert fresh.foreground(2).color() == QColor(Color.WARNING)
    zombie = find_by_key(dlg._tree, ("alpha", 102, "pve01"))
    assert zombie.foreground(2).color() == QColor(Color.DANGER)
    assert zombie.text(3) == "Unknown snapshot age"
    # no timestamp → no age in the issue column either ("oldest None" lies)
    assert zombie.text(2) == "1 snapshots, unknown age"


def test_scan_progress_in_status(qtbot, api):
    dlg = make_dialog(qtbot)
    wait_loaded(qtbot, dlg)
    # progress from the background thread lands in the "Scanning... d/t" status
    dlg._scan_thread = threading.Thread(target=lambda: None)
    dlg._scan_thread.start()
    dlg._on_scan_progress(45, 120)
    assert "45/120" in dlg._status.text()
    # after the scan finishes, late updates leave the status alone
    dlg._scan_thread.join()
    dlg._scan_thread = None
    dlg._status.setText("done")
    dlg._on_scan_progress(50, 120)
    assert dlg._status.text() == "done"


def test_worker_multi_cluster(qtbot, monkeypatch):
    alpha = make_pve_cluster("alpha")
    beta = make_pve_cluster("beta")
    install_fake_pve(monkeypatch, alpha, beta)
    worker = FleetHealthWorker([
        FleetTarget("alpha", "alpha", fake_pve_cfg("alpha")),
        FleetTarget("beta", "beta", fake_pve_cfg("beta")),
    ])
    with qtbot.waitSignal(worker.finished_all, timeout=20000) as blocker:
        worker.start()
    bundles = blocker.args[0]
    assert {b.report.cluster for b in bundles} == {"alpha", "beta"}
    assert all(b.report.complete for b in bundles)
    assert all(b.runway for b in bundles)  # scene rrddata → estimates


def test_worker_pbs_freshness(qtbot, monkeypatch):
    """PBS configs passed to the worker enrich every cluster report."""
    import virtdeck.backend.fleet as backend_fleet
    monkeypatch.setattr(backend_fleet, "collect_pbs_last_backups",
                        lambda cfgs: {("vm", "101"): 1727827200})
    alpha = make_pve_cluster("alpha")
    install_fake_pve(monkeypatch, alpha)
    worker = FleetHealthWorker(
        [FleetTarget("alpha", "alpha", fake_pve_cfg("alpha"))],
        pbs_cfgs=[{"name": "pbs1", "type": "pbs"}])
    with qtbot.waitSignal(worker.finished_all, timeout=20000) as blocker:
        worker.start()
    bundle = blocker.args[0][0]
    assert bundle.report.backup_states[101].pbs_last_ok == 1727827200


def test_cluster_display_label(qtbot, monkeypatch):
    """The cluster is labeled with the cluster name, VM keys use the
    config name."""
    api = make_pve_cluster("pve01")
    install_fake_pve(monkeypatch, api)
    dlg = FleetHealthDialog(
        [FleetTarget("pve01", "mycluster", fake_pve_cfg("pve01"))])
    qtbot.addWidget(dlg)
    wait_loaded(qtbot, dlg)
    top = dlg._tree.topLevelItem(0)
    assert top.text(0) == "mycluster"
    row = find_by_key(dlg._tree, ("pve01", 301, "pve02"))
    assert row is not None  # navigation key — by the config-endpoint name


class TestBuildFleetTargets:
    """Config grouping — tree semantics (creator = cluster_rep)."""

    def test_cluster_grouped_by_name(self):
        creator = {"name": "pve01", "cluster": "mylab",
                   "cluster_rep": True}
        joinee = {"name": "pve02", "cluster": "mylab"}
        targets = build_fleet_targets([creator, joinee])
        assert len(targets) == 1
        t = targets[0]
        assert t.name == "pve01"        # the endpoint is the representative
        assert t.display == "mylab"     # the label is the cluster name
        assert t.cfg is creator

    def test_cluster_without_rep_first_member(self):
        members = [{"name": "pve02", "cluster": "mylab"},
                   {"name": "pve03", "cluster": "mylab"}]
        t = build_fleet_targets(members)[0]
        assert t.name == "pve02"
        assert t.display == "mylab"

    def test_standalone_each_own_target(self):
        cfgs = [{"name": "solo1"}, {"name": "solo2", "cluster": False}]
        targets = build_fleet_targets(cfgs)
        assert [(t.name, t.display) for t in targets] == \
            [("solo1", "solo1"), ("solo2", "solo2")]

    def test_excludes_pbs_and_skip(self):
        cfgs = [{"name": "pbs1", "type": "pbs"},
                {"name": "off", "skip": True},
                {"name": "solo"}]
        targets = build_fleet_targets(cfgs)
        assert [t.name for t in targets] == ["solo"]

    def test_standalone_word_is_not_cluster(self):
        """cluster='Standalone' — a service value; it is a single host."""
        t = build_fleet_targets([{"name": "solo",
                                  "cluster": "Standalone"}])
        assert [(x.name, x.display) for x in t] == [("solo", "solo")]

    def test_sorted_by_display(self):
        targets = build_fleet_targets([
            {"name": "b-host", "cluster": "zeta", "cluster_rep": True},
            {"name": "a-host"}])
        assert [t.display for t in targets] == ["a-host", "zeta"]


def test_stale_compliance_warning(qtbot, api):
    """A backup exists but is older than the threshold — a yellow row."""
    dlg = make_dialog(qtbot)
    wait_loaded(qtbot, dlg)
    report = dlg._bundles[0].report
    old = GuestBackupState(vmid=101, task_last_ok=NOW - 30 * 86400,
                           task_last_attempt=NOW - 30 * 86400)
    states = dict(report.backup_states)
    states[101] = old
    report = replace(report, generated_at=NOW, backup_states=states)
    dlg._bundles = [ClusterBundle(report=report, runway=())]
    dlg._render()
    row = find_issue(dlg._tree, "Last backup is 30 days old")
    assert row is not None
    assert row.foreground(2).color() == QColor(Color.WARNING)
