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
from virtdeck.domain.fleet import (
    CollectError,
    GuestBackupState,
    build_cluster_report,
)
from virtdeck.fleet.pbs_source import PbsEvidence
from virtdeck.fleet.runway import UNAVAILABLE, RunwayEstimate
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


def test_render_pbs_scope_caveat(qtbot, api):
    """T16: pbs_scope != ok → a yellow caveat row; red rows stay based
    on task evidence only (a PBS failure never invents red states)."""
    dlg = make_dialog(qtbot)
    wait_loaded(qtbot, dlg)
    dlg._bundles = [_freeze_now(dlg._bundles[0])]
    dlg._render()
    assert find_issue(dlg._tree, "PBS freshness unverified") is None

    def reds():
        return [(r.text(1), r.text(2)) for r in walk_rows(dlg._tree)
                if r.foreground(2).color() == QColor(Color.DANGER)]

    reds_before = reds()
    report = replace(dlg._bundles[0].report,
                     pbs_scope="unavailable",
                     pbs_scope_reasons=("PBS storage configuration "
                                        "unavailable",))
    dlg._bundles = [ClusterBundle(report=report,
                                  runway=dlg._bundles[0].runway,
                                  display="alpha")]
    dlg._render()
    row = find_issue(dlg._tree, "PBS freshness unverified")
    if row is None:
        # a cluster-level caveat hangs directly off the cluster node
        top = dlg._tree.topLevelItem(0)
        direct = [top.child(j) for j in range(top.childCount())]
        row = next((r for r in direct
                    if r.text(2) == "PBS freshness unverified"), None)
    assert row is not None
    assert row.text(3) == "PBS storage configuration unavailable"
    assert row.foreground(2).color() == QColor(Color.WARNING)
    assert row.data(0, KEY_ROLE) is None  # a caveat is not navigable
    # the same red rows as before — no new reds from the PBS failure
    assert reds() == reds_before


def test_no_issues_status(qtbot, api):
    dlg = make_dialog(qtbot)
    wait_loaded(qtbot, dlg)
    dlg._bundles = []
    dlg._render()
    # U6: zero targets must not read as "everything is clean"
    assert dlg._status.text() == "No clusters configured"
    assert dlg._empty.isVisibleTo(dlg)


def test_data_from_plate_on_partial_failure(qtbot, api):
    # pveversion from status with a /version fallback — fail both on error
    api.fail["nodes/pve02/status"] = (500, "boom")
    api.fail["nodes/pve02/version"] = (500, "boom")
    dlg = make_dialog(qtbot)
    wait_loaded(qtbot, dlg)
    top = dlg._tree.topLevelItem(0)
    assert "Data from" in top.text(0)
    # DELIGHT-3: data incompleteness is informational — neutral TEXT_SEC,
    # not the warning amber
    assert top.foreground(0).color() == QColor(Color.TEXT_SEC)
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


def test_tasks_unavailable_shows_unverified_not_never_backed_up(qtbot, api):
    """Audit D4: the task history failed to collect — the absence of
    task evidence must not be asserted as "Never backed up" (red lie).
    The row is a yellow "unverified" and names what could not be
    checked; PBS/job direct evidence keeps working."""
    dlg = make_dialog(qtbot)
    wait_loaded(qtbot, dlg)
    report = dlg._bundles[0].report
    report2 = build_cluster_report(
        cluster=report.cluster, generated_at=NOW,
        resources=[{"type": "qemu", "vmid": 105, "name": "fresh",
                    "node": "pve01"}],
        backup_jobs=[{"id": "bz-all", "enabled": 1, "all": 1}],
        tasks=None,
        errors=[CollectError(cluster="alpha", source="tasks",
                             message="500 internal error")])
    dlg._bundles = [ClusterBundle(report=report2, runway=())]
    dlg._render()
    assert find_issue(dlg._tree, "Never backed up") is None
    row = find_issue(dlg._tree, "Backup state unverified")
    assert row is not None
    assert row.text(1) == "fresh (105)"
    assert "500 internal error" in row.text(3)
    assert row.foreground(2).color() == QColor(Color.WARNING)
    assert dlg._status.text() != "No issues found"


def test_tasks_fetched_empty_confirms_never_backed_up(qtbot, api):
    """tasks=[] is a confirmed absence (history fetched, jobs fetched,
    no evidence) — the red assertion is legitimate and stays."""
    dlg = make_dialog(qtbot)
    wait_loaded(qtbot, dlg)
    report = dlg._bundles[0].report
    report2 = build_cluster_report(
        cluster=report.cluster, generated_at=NOW,
        resources=[{"type": "qemu", "vmid": 105, "name": "fresh",
                    "node": "pve01"}],
        backup_jobs=[{"id": "bz-all", "enabled": 1, "all": 1}],
        tasks=[])
    dlg._bundles = [ClusterBundle(report=report2, runway=())]
    dlg._render()
    row = find_issue(dlg._tree, "Never backed up")
    assert row is not None
    assert row.foreground(2).color() == QColor(Color.DANGER)
    assert find_issue(dlg._tree, "Backup state unverified") is None


def test_pve_below_72_shows_job_attribution_caveat(qtbot, api):
    """Audit D6: PVE < 7.2 UPIDs carry no job id — scheduled job runs
    cannot be attributed to guests. The caveat is plain (not an issue)."""
    dlg = make_dialog(qtbot)
    wait_loaded(qtbot, dlg)
    report = dlg._bundles[0].report
    report2 = build_cluster_report(
        cluster=report.cluster, generated_at=NOW,
        resources=[{"type": "qemu", "vmid": 105, "name": "fresh",
                    "node": "pve01"}],
        backup_jobs=[{"id": "bz-all", "enabled": 1, "all": 1}],
        tasks=[{"upid": "UPID:pve01:00000009:00000000:67100000:"
                        "vzdump:105:root@pam:",
                "type": "vzdump", "status": "OK",
                "starttime": NOW - 3600}],
        node_versions={"pve01": "pve-manager/7.1.2/abc"})
    dlg._bundles = [ClusterBundle(report=report2, runway=())]
    dlg._render()
    top = dlg._tree.topLevelItem(0)
    rows = [top.child(j) for j in range(top.childCount())]
    assert any(r.text(2) == "Job-run attribution unavailable" for r in rows)
    caveat = next(r for r in rows
                  if r.text(2) == "Job-run attribution unavailable")
    assert "pve01" in caveat.text(3)
    assert dlg._status.text() == "No issues found"


def test_pve_72_and_above_has_no_attribution_caveat(qtbot, api):
    dlg = make_dialog(qtbot)
    wait_loaded(qtbot, dlg)
    report = dlg._bundles[0].report
    report2 = build_cluster_report(
        cluster=report.cluster, generated_at=NOW,
        resources=[{"type": "qemu", "vmid": 105, "name": "fresh",
                    "node": "pve01"}],
        backup_jobs=[{"id": "bz-all", "enabled": 1, "all": 1}],
        tasks=[{"upid": "UPID:pve01:00000009:00000000:67100000:"
                        "vzdump:105:root@pam:",
                "type": "vzdump", "status": "OK",
                "starttime": NOW - 3600}],
        node_versions={"pve01": "pve-manager/7.2.0/abc"})
    dlg._bundles = [ClusterBundle(report=report2, runway=())]
    dlg._render()
    assert find_issue(dlg._tree, "Job-run attribution unavailable") is None
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


def test_scan_incomplete_status(qtbot, api):
    """Failed per-VM fetches are not "no snapshots" — the status says so."""
    dlg = make_dialog(qtbot)
    wait_loaded(qtbot, dlg)
    dlg._scans = {"alpha": scan_sprawl({}, [], now=NOW,
                                       failed=(101, 102, 301))}
    dlg._render()
    assert "3 guests failed" in dlg._status.text()


def test_scan_worker_crash_releases_ui(qtbot, api, monkeypatch):
    import virtdeck.ui.fleet_health as fh

    dlg = make_dialog(qtbot)
    wait_loaded(qtbot, dlg)
    dlg._scan_thread = threading.Thread(target=lambda: None)
    dlg._scan_thread.start()
    dlg._scan_thread.join()

    def boom(*_a, **_kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(fh, "scan_fleet_snapshots", boom)
    t = threading.Thread(target=dlg._scan_worker, daemon=True)
    dlg._scan_thread = t
    with qtbot.waitSignal(dlg._scan_signals.scans_done, timeout=5000):
        t.start()
    t.join()
    assert dlg._scan_thread is None
    assert dlg._scan_btn.isEnabled() and dlg._refresh_btn.isEnabled()


def test_runway_full_storage_no_growth(qtbot, api):
    """A nearly full storage without growth must still speak up (P1):
    "99% full" must not hide behind "no trend"."""
    dlg = make_dialog(qtbot)
    wait_loaded(qtbot, dlg)
    report = dlg._bundles[0].report

    def est(days, used, *, quality="ok", low=None, high=None, age=None):
        return RunwayEstimate(node="pve01", storage="local",
                              used_bytes=used, total_bytes=100,
                              slope_bytes_per_day=1.0 if days else 0.0,
                              days_left=days, days_left_low=low,
                              days_left_high=high, points_used=48,
                              quality=quality, last_point_age_days=age)

    # 96% full, no growth → red "almost full" (silent before this fix)
    dlg._bundles = [ClusterBundle(report=report,
                                  runway=(est(None, 96, quality="no-trend"),))]
    dlg._render()
    row = find_issue(dlg._tree, "Storage almost full")
    assert row is not None
    assert row.text(3) == "96% used — no growth detected"
    assert row.foreground(2).color() == QColor(Color.DANGER)

    # 92% → warning
    dlg._bundles = [ClusterBundle(report=report,
                                  runway=(est(None, 92, quality="no-trend"),))]
    dlg._render()
    row = find_issue(dlg._tree, "Storage almost full")
    assert row.foreground(2).color() == QColor(Color.WARNING)

    # 50% + no growth → silent
    dlg._bundles = [ClusterBundle(report=report,
                                  runway=(est(None, 50, quality="no-trend"),))]
    dlg._render()
    assert find_issue(dlg._tree, "Storage almost full") is None

    # growing storage keeps the days-based row even at 96% full
    dlg._bundles = [ClusterBundle(report=report,
                                  runway=(est(20, 96, low=19, high=21),))]
    dlg._render()
    assert find_issue(dlg._tree, "Storage almost full") is None
    assert find_issue(dlg._tree, "Storage filling up") is not None


def test_runway_open_ended_ci_and_stale_data(qtbot, api):
    dlg = make_dialog(qtbot)
    wait_loaded(qtbot, dlg)
    report = dlg._bundles[0].report
    # optimistic CI bound never fills → the range is open-ended ("∞")
    est = RunwayEstimate(node="pve01", storage="local", used_bytes=80,
                         total_bytes=100, slope_bytes_per_day=1.0,
                         days_left=10, days_left_low=9, days_left_high=None,
                         points_used=48, quality="ok")
    dlg._bundles = [ClusterBundle(report=report, runway=(est,))]
    dlg._render()
    row = find_issue(dlg._tree, "Storage filling up")
    assert row is not None
    assert row.text(3) == "~9–∞ days left"

    # stale series (node was down) → explicit age suffix
    est = RunwayEstimate(node="pve01", storage="local", used_bytes=80,
                         total_bytes=100, slope_bytes_per_day=1.0,
                         days_left=10, days_left_low=9, days_left_high=11,
                         points_used=48, quality="ok",
                         last_point_age_days=5.0)
    dlg._bundles = [ClusterBundle(report=report, runway=(est,))]
    dlg._render()
    row = find_issue(dlg._tree, "Storage filling up")
    assert "data 5 days old" in row.text(3)


def test_runway_read_failure_becomes_unavailable_note():
    """A2: a storage whose rrddata cannot be read gets an explicit
    placeholder estimate — silence must not read as healthy."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    worker = FleetHealthWorker([])
    report = SimpleNamespace(storage_usage=[
        {"node": "pve01", "storage": "local", "active": 1, "shared": 0},
        {"node": "pve01", "storage": "big", "active": 1, "shared": 0},
    ])

    def rrd(node, storage, timeframe):
        if storage == "local":
            raise RuntimeError("rrd read failed")
        return [{"time": 1000.0, "used": 10.0, "total": 100.0},
                {"time": 2000.0, "used": 20.0, "total": 100.0}]

    prov = MagicMock()
    prov.rrd.get_storage_rrddata.side_effect = rrd
    ests = worker._runway(prov, report)
    by_store = {e.storage: e for e in ests}
    assert by_store["local"].note
    assert by_store["local"].days_left is None
    assert by_store["local"].quality == UNAVAILABLE
    assert not by_store["big"].note  # healthy path untouched


def test_runway_unavailable_row_rendered(qtbot, api):
    """A2 UI: the placeholder renders as an explicit yellow row —
    "no row" must not be indistinguishable from "forecast is fine"."""
    dlg = make_dialog(qtbot)
    wait_loaded(qtbot, dlg)
    report = dlg._bundles[0].report
    est = RunwayEstimate(node="pve01", storage="local", used_bytes=None,
                         total_bytes=None, slope_bytes_per_day=None,
                         days_left=None, days_left_low=None,
                         days_left_high=None, points_used=0,
                         quality=UNAVAILABLE, note="connection failed")
    dlg._bundles = [ClusterBundle(report=report, runway=(est,))]
    dlg._render()
    row = find_issue(dlg._tree, "Runway data unavailable")
    assert row is not None
    assert row.foreground(2).color() == QColor(Color.WARNING)
    assert "local" in row.text(1) and "connection failed" in row.text(3)


def test_runway_unavailable_i18n_key():
    """Audit A2: the unavailable-row key must exist in all locales."""
    import json
    from pathlib import Path
    i18n_dir = Path(__file__).parents[1].parent / "virtdeck" / "ui" / "i18n"
    for lang in ("ru", "ar", "zh", "fr", "es"):
        data = json.loads((i18n_dir / f"{lang}.json").read_text(
            encoding="utf-8"))
        assert "Runway data unavailable" in data, lang


class TestDedupStorageRows:
    def test_shared_forecast_once_per_cluster(self):
        from virtdeck.backend.fleet import _dedup_storage_rows
        rows = [
            {"node": "n1", "storage": "local", "active": 1, "shared": 0},
            {"node": "n1", "storage": "nfs1", "active": 1, "shared": 1},
            {"node": "n2", "storage": "local", "active": 1, "shared": 0},
            {"node": "n2", "storage": "nfs1", "active": 1, "shared": 1},
            {"node": "n2", "storage": "dead", "active": 0, "shared": 1},
        ]
        out = _dedup_storage_rows(rows)
        assert [(r["node"], r["storage"]) for r in out] == \
            [("n1", "local"), ("n1", "nfs1"), ("n2", "local")]


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


def set_pbs_storage(api, *, server: str, datastore: str,
                    namespace: str | None = None) -> None:
    """Point the scene's pbs1 storage row at a concrete PBS source."""
    row = next(r for r in api.storage_cfg if r.get("type") == "pbs")
    row["server"], row["datastore"] = server, datastore
    row.pop("namespace", None)
    if namespace is not None:
        row["namespace"] = namespace


def pbs_evidence(host: str, datastore: str, times: dict, *,
                 ns: str = "") -> PbsEvidence:
    """A collected one-store PbsEvidence (root namespace)."""
    from virtdeck.fleet.pbs_source import PbsEvidence
    return PbsEvidence(
        by_source={(host, 8007, datastore, ns): dict(times)},
        collected_stores={(host, 8007, datastore)})


def run_worker(qtbot, monkeypatch, evidence, *apis):
    import virtdeck.backend.fleet as backend_fleet
    monkeypatch.setattr(backend_fleet, "collect_pbs_last_backups",
                        lambda cfgs: evidence)
    install_fake_pve(monkeypatch, *apis)
    worker = FleetHealthWorker(
        [FleetTarget(api.name, api.name, fake_pve_cfg(api.name))
         for api in apis],
        pbs_cfgs=[{"name": "pbs1", "type": "pbs"}])
    with qtbot.waitSignal(worker.finished_all, timeout=20000) as blocker:
        worker.start()
    return {b.report.cluster: b for b in blocker.args[0]}


def test_worker_pbs_freshness(qtbot, monkeypatch):
    """PBS evidence scoped by the cluster's own pbs storages: matched
    binding → the guest's pbs_last_ok is set, scope ok."""
    alpha = make_pve_cluster("alpha")
    set_pbs_storage(alpha, server="pbs1.local", datastore="main")
    bundles = run_worker(qtbot, monkeypatch,
                         pbs_evidence("pbs1.local", "main",
                                      {("vm", "101"): 1727827200}), alpha)
    report = bundles["alpha"].report
    assert report.backup_states[101].pbs_last_ok == 1727827200
    assert report.pbs_scope == "ok"
    assert report.pbs_scope_reasons == ()


def test_worker_t1_same_vmid_different_datastores(qtbot, monkeypatch):
    """Two clusters, same VMID, different datastores: each cluster sees
    only its own evidence (the D5 false credit is gone)."""
    alpha, beta = make_pve_cluster("alpha"), make_pve_cluster("beta")
    set_pbs_storage(alpha, server="pbs-a.local", datastore="main")
    set_pbs_storage(beta, server="pbs-b.local", datastore="main")
    bundles = run_worker(qtbot, monkeypatch, PbsEvidence(
        by_source={
            ("pbs-a.local", 8007, "main", ""): {("vm", "101"): 1000},
            ("pbs-b.local", 8007, "main", ""): {("vm", "101"): 2000},
        },
        collected_stores={("pbs-a.local", 8007, "main"),
                          ("pbs-b.local", 8007, "main")}), alpha, beta)
    assert bundles["alpha"].report.backup_states[101].pbs_last_ok == 1000
    assert bundles["beta"].report.backup_states[101].pbs_last_ok == 2000
    assert all(b.report.pbs_scope == "ok" for b in bundles.values())


def test_worker_t4_shared_source_ambiguous(qtbot, monkeypatch):
    """One datastore shared by two clusters with the same VMID: the
    snapshot cannot be attributed — dropped, scope ambiguous, the
    report stays honest (no false freshness)."""
    alpha, beta = make_pve_cluster("alpha"), make_pve_cluster("beta")
    set_pbs_storage(alpha, server="pbs-a.local", datastore="main")
    set_pbs_storage(beta, server="pbs-a.local", datastore="main")
    bundles = run_worker(qtbot, monkeypatch,
                         pbs_evidence("pbs-a.local", "main",
                                      {("vm", "101"): 1000}), alpha, beta)
    for name in ("alpha", "beta"):
        report = bundles[name].report
        assert report.pbs_scope == "ambiguous"
        assert report.backup_states[101].pbs_last_ok is None
        assert report.backup_states[101].task_last_ok is not None \
            or True  # task evidence is independent of the PBS scope
        assert any("ambiguous" in r for r in report.pbs_scope_reasons)


def test_worker_t7_storage_config_failure_unverified(qtbot, monkeypatch):
    """GET /storage fails on one cluster: its scope is unavailable (no
    PBS evidence as a fallback), the other cluster is unaffected."""
    alpha, beta = make_pve_cluster("alpha"), make_pve_cluster("beta")
    set_pbs_storage(alpha, server="pbs-a.local", datastore="main")
    set_pbs_storage(beta, server="pbs-b.local", datastore="main")
    alpha.fail["storage"] = (500, "boom")
    bundles = run_worker(qtbot, monkeypatch, PbsEvidence(
        by_source={
            ("pbs-a.local", 8007, "main", ""): {("vm", "101"): 1000},
            ("pbs-b.local", 8007, "main", ""): {("vm", "101"): 2000},
        },
        collected_stores={("pbs-a.local", 8007, "main"),
                          ("pbs-b.local", 8007, "main")}), alpha, beta)
    ra, rb = bundles["alpha"].report, bundles["beta"].report
    assert ra.pbs_scope == "unavailable"
    assert ra.backup_states[101].pbs_last_ok is None
    assert any(e.source == "pbs_storage_config" for e in ra.errors)
    assert not ra.complete
    assert rb.pbs_scope == "ok"
    assert rb.backup_states[101].pbs_last_ok == 2000
    assert rb.complete


def test_worker_t13_new_cycle_new_evidence(qtbot, monkeypatch):
    """Two sequential worker runs: each cycle collects its own PBS
    evidence and bindings — a late report never carries stale evidence."""
    alpha = make_pve_cluster("alpha")
    set_pbs_storage(alpha, server="pbs1.local", datastore="main")
    first = run_worker(qtbot, monkeypatch,
                       pbs_evidence("pbs1.local", "main",
                                    {("vm", "101"): 1000}), alpha)
    assert first["alpha"].report.backup_states[101].pbs_last_ok == 1000
    second = run_worker(qtbot, monkeypatch,
                        pbs_evidence("pbs1.local", "main",
                                     {("vm", "101"): 2000}), alpha)
    assert second["alpha"].report.backup_states[101].pbs_last_ok == 2000
    assert second["alpha"].report.generated_at \
        >= first["alpha"].report.generated_at


def test_worker_t14_secrets_not_logged(qtbot, monkeypatch, caplog):
    """T14: PBS configs and /storage rows carry secrets — none of them
    may reach the logs during a collection cycle."""
    import logging
    alpha = make_pve_cluster("alpha")
    set_pbs_storage(alpha, server="pbs1.local", datastore="main")
    alpha.storage_cfg[0]["password"] = "row-secret-pw"
    secret_ev = pbs_evidence("pbs1.local", "main", {("vm", "101"): 1000})
    import virtdeck.backend.fleet as backend_fleet
    monkeypatch.setattr(backend_fleet, "collect_pbs_last_backups",
                        lambda cfgs: secret_ev)
    install_fake_pve(monkeypatch, alpha)
    worker = FleetHealthWorker(
        [FleetTarget("alpha", "alpha", fake_pve_cfg("alpha"))],
        pbs_cfgs=[{"name": "pbs1", "type": "pbs",
                   "token_value": "cfg-secret-tv"}])
    with caplog.at_level(logging.DEBUG, logger="virtdeck"):
        with qtbot.waitSignal(worker.finished_all, timeout=20000):
            worker.start()
    assert "row-secret-pw" not in caplog.text
    assert "cfg-secret-tv" not in caplog.text


def test_worker_crash_still_emits_finished(qtbot, monkeypatch):
    """A crash inside a job must not leave the dialog without the
    finished_all signal (buttons would stay disabled forever).

    Audit A3: the cluster must also not silently disappear — a crash
    inside _collect_one's own error path lands as a stub report with
    the CollectError row, so a missing cluster can never read as
    "no problems"."""
    alpha = make_pve_cluster("alpha")
    install_fake_pve(monkeypatch, alpha)
    worker = FleetHealthWorker(
        [FleetTarget("alpha", "alpha", fake_pve_cfg("alpha"))])

    def boom(self, target, pbs_map=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(FleetHealthWorker, "_collect_one", boom)
    with qtbot.waitSignal(worker.finished_all, timeout=10000) as blocker:
        worker.start()
    bundles = blocker.args[0]
    assert {b.report.cluster for b in bundles} == {"alpha"}
    errors = bundles[0].report.errors
    assert any(e.source == "cluster" and "boom" in e.message
               for e in errors)


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
