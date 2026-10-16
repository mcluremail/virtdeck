"""Tests for PbsPanel — PBS datastore/snapshot/job views (B17 stage 2)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt

from virtdeck.domain.pbs import PbsDatastore, PbsJob, PbsSnapshot
from virtdeck.pbs.client import PbsError
from virtdeck.pbs.provider import PbsProvider
from virtdeck.ui import pbs_panel as pbs_panel_mod
from virtdeck.ui.pbs_panel import PbsPanel
from virtdeck.ui.theme import Color

_CFG = {
    "name": "pbs1", "type": "pbs", "host": "pbs.local",
    "port": 8007, "user": "root@pam", "token_value": "s",
}


@pytest.fixture
def panel(qtbot, monkeypatch):
    p = PbsPanel()
    qtbot.addWidget(p)
    # Never start real workers: capture requests instead.
    started = []

    def fake_start(method, *args, tag=None, **kwargs):
        started.append((method, args, tag, kwargs))

    monkeypatch.setattr(p, "_start", fake_start)
    p.started = started
    p.update_nodes_cfg([_CFG])
    return p


def _ds(name="main", usage=0.5, status_ok=True):
    return PbsDatastore(name=name, path=f"/mnt/{name}", usage=usage,
                        used_bytes=500 * 10**9, total_bytes=1000 * 10**9,
                        status_ok=status_ok)


def _snap(**kw):
    base = {
        "backup-type": "vm", "backup-id": "100",
        "backup-time": 1700000000, "owner": "root@pam",
        "verify-state": "ok", "size": 42 * 10**9,
    }
    base.update(kw)
    return PbsSnapshot.from_api("main", base)


class TestServerView:
    def test_show_server_loads_datastores(self, panel):
        panel.show_server("pbs1")
        assert panel._server == "pbs1"
        assert panel._stack.currentIndex() == 0
        assert panel.started == [("datastores", (), ("ds", "pbs1"), {})]

    def test_show_server_unknown_ignored(self, panel):
        panel.show_server("nope")
        assert panel._server == ""
        assert panel.started == []

    def test_fill_ds_table(self, panel):
        panel.show_server("pbs1")
        panel._fill_ds_table([_ds("main"), _ds("alt", 0.95)])
        assert panel._ds_table.rowCount() == 2
        assert panel._ds_table.item(0, 0).text() == "alt"  # sorted by name
        assert panel._ds_table.item(1, 0).text() == "main"
        assert panel._ds_table.item(1, 1).text() == "50%"

    def test_datastores_loaded_signal(self, panel, qtbot):
        panel.show_server("pbs1")
        with qtbot.waitSignal(panel.datastores_loaded) as blocker:
            panel._on_worker_done(("ds", "pbs1"), [_ds()])
        assert blocker.args == ["pbs1", [_ds()]]

    def test_fill_status(self, panel):
        panel.show_datastore("pbs1", "main")
        panel._fill_status(_ds(usage=0.842))
        assert "84%" in panel._usage_lbl.text()

    # -- audit D1: unreadable status must not render as fake zeros --

    def test_fill_ds_table_unavailable_status_shows_dashes(self, panel):
        panel.show_server("pbs1")
        panel._fill_ds_table([_ds("broken", status_ok=False)])
        assert panel._ds_table.item(0, 1).text() == "—"  # usage
        assert panel._ds_table.item(0, 2).text() == "—"  # used
        assert panel._ds_table.item(0, 3).text() == "—"  # total

    def test_fill_ds_table_confirmed_zero_stays_zero(self, panel):
        panel.show_server("pbs1")
        zero = PbsDatastore(name="empty", usage=0.0, used_bytes=0,
                            total_bytes=0, status_ok=True)
        panel._fill_ds_table([zero])
        assert panel._ds_table.item(0, 1).text() == "0%"
        assert "0 B" in panel._ds_table.item(0, 2).text()
        assert "0 B" in panel._ds_table.item(0, 3).text()

    def test_fill_status_unavailable_shows_message(self, panel):
        panel.show_datastore("pbs1", "main")
        panel._fill_status(_ds("broken", status_ok=False))
        assert panel._usage_lbl.text() == "Usage data unavailable"
        assert panel._usage_bar.value() == 0

    def test_fill_status_confirmed_zero_shows_zero(self, panel):
        panel.show_datastore("pbs1", "main")
        panel._fill_status(PbsDatastore(name="empty", usage=0.0,
                                        used_bytes=0, total_bytes=0,
                                        status_ok=True))
        assert "0%" in panel._usage_lbl.text()
        assert panel._usage_bar.value() == 0


class TestDatastoreView:
    def test_show_datastore_loads_all(self, panel):
        panel.show_datastore("pbs1", "main")
        assert panel._stack.currentIndex() == 1
        methods = [s[0] for s in panel.started]
        assert methods == ["datastores", "snapshots", "jobs"]
        # snapshots request carried empty namespace
        snap_call = panel.started[1]
        assert snap_call[1] == ("main",)
        assert snap_call[3] == {"ns": ""}
        assert snap_call[2] == ("snap", "pbs1", "main", "")

    def test_fill_snapshots(self, panel):
        panel.show_datastore("pbs1", "main")
        panel._fill_snapshots([_snap(), _snap(backup_id="101",
                                              verify_state="failed")])
        assert panel._snap_table.rowCount() == 2
        assert panel._snap_table.item(0, 0).text().startswith("vm/100/")
        assert panel._snap_table.item(0, 1).text() == "root@pam"

    def test_snap_row_holds_snapshot_in_user_role(self, panel):
        snap = _snap()
        panel.show_datastore("pbs1", "main")
        panel._fill_snapshots([snap])
        assert panel._snap_table.item(0, 0).data(Qt.UserRole) is snap

    def test_snap_tag_mismatch_ignored(self, panel):
        panel.show_datastore("pbs1", "main")
        # result for another server is dropped
        panel._on_worker_done(("snap", "other", "main", ""), [_snap()])
        assert panel._snap_table.rowCount() == 0

    def test_fill_jobs_with_user_role_kind(self, panel):
        panel.show_datastore("pbs1", "main")
        jobs = [PbsJob(id="s1", kind="sync", store="main", schedule="daily"),
                PbsJob(id="v1", kind="verify", store="main", disabled=True)]
        panel._fill_jobs(jobs)
        assert panel._jobs_table.rowCount() == 2
        assert panel._jobs_table.item(0, 0).data(Qt.UserRole) == "sync"
        assert panel._jobs_table.item(1, 0).data(Qt.UserRole) == "verify"
        assert panel._jobs_table.item(1, 4).text() == "Disabled"

    def test_run_job_uses_user_role_kind(self, panel):
        panel.show_datastore("pbs1", "main")
        panel._fill_jobs([PbsJob(id="s1", kind="sync", store="main")])
        # simulate the context-menu action without exec()
        panel._start("run_job", "sync", "s1",
                     tag=("run", "pbs1", "sync", "s1"))
        assert panel.started[-1] == (
            ("run_job", ("sync", "s1"), ("run", "pbs1", "sync", "s1"), {}))


class TestUsageColors:
    def test_usage_color_thresholds(self):
        # tokens, not hex: values change with the contrast audit
        color = pbs_panel_mod._usage_color
        assert color(0.5) == Color.SUCCESS
        assert color(0.8) == Color.WARNING
        assert color(0.95) == Color.DANGER


class TestNsCombo:
    def test_namespace_repopulated(self, panel):
        panel.show_datastore("pbs1", "main")
        panel._on_worker_done(("ns", "pbs1", "main"), ["t1", "t2"])
        assert panel._ns_combo.count() == 3
        assert panel._ns_combo.itemText(1) == "t1"

    def test_namespace_selection_preserved(self, panel):
        panel.show_datastore("pbs1", "main")
        panel._on_worker_done(("ns", "pbs1", "main"), ["t1", "t2"])
        panel._ns_combo.setCurrentText("t2")
        panel._on_worker_done(("ns", "pbs1", "main"), ["t1", "t2", "t3"])
        assert panel._ns_combo.currentText() == "t2"

    def test_ns_change_reloads_snapshots(self, panel, monkeypatch):
        panel.show_datastore("pbs1", "main")
        panel.started.clear()
        panel._on_worker_done(("ns", "pbs1", "main"), ["t1"])
        panel._ns_combo.setCurrentText("t1")  # signal → _on_ns_changed
        assert panel.started[-1][0] == "snapshots"
        assert panel.started[-1][3] == {"ns": "t1"}

    def test_ns_hidden_when_root_only(self, panel):
        panel.show_datastore("pbs1", "main")
        panel._on_worker_done(("ns", "pbs1", "main"), [])
        assert panel._ns_lbl.isHidden()
        assert panel._ns_combo.isHidden()
        assert panel._ns_combo.currentData() == ""

    def test_ns_visible_with_namespaces(self, panel):
        panel.show_datastore("pbs1", "main")
        panel._on_worker_done(("ns", "pbs1", "main"), ["t1"])
        assert not panel._ns_lbl.isHidden()
        assert not panel._ns_combo.isHidden()
        assert panel._ns_combo.itemText(0) == "/"
        assert panel._ns_combo.currentData() == ""

    def test_show_datastore_hides_ns_until_loaded(self, panel):
        panel.show_datastore("pbs1", "main")
        assert panel._ns_lbl.isHidden()
        assert panel._ns_combo.isHidden()


class TestUpdateNodesCfg:
    def test_only_pbs_cfgs_kept(self, panel):
        panel.update_nodes_cfg([
            _CFG,
            {"name": "pve1", "host": "h1"},
            {"type": "pbs", "host": "h2"},  # no name → skipped
        ])
        assert set(panel._cfg_by_name) == {"pbs1"}
        assert panel._cfg_by_name["pbs1"]["host"] == "pbs.local"


class TestShowDatastoreTabKeep:
    def test_same_datastore_keeps_tab(self, panel):
        panel.show_datastore("pbs1", "main")
        assert panel._tabs.currentIndex() == 0
        panel._tabs.setCurrentIndex(1)  # user opens Snapshots
        panel.show_datastore("pbs1", "main")
        assert panel._tabs.currentIndex() == 1

    def test_other_datastore_resets_tab(self, panel):
        panel.show_datastore("pbs1", "main")
        panel._tabs.setCurrentIndex(1)
        panel.show_datastore("pbs1", "other")
        assert panel._tabs.currentIndex() == 0


# --- audit 6.3.2a D9: worker tracking, discard and pool limit ---------------


class _FakePbsClient:
    def __init__(self, boom=False):
        self.boom = boom
        self.closed = False

    def close(self):
        self.closed = True

    def datastores(self):
        if self.boom:
            raise PbsError("boom", 500)
        return [{"store": "main"}]


def _make_live(monkeypatch):
    """PbsPanel with the real _start, no qtbot registration (callers that
    destroy the panel must not register it)."""
    p = PbsPanel()
    p._server = "pbs1"
    p.update_nodes_cfg([_CFG])
    started = []
    made = []

    def fake_start(runnable):
        started.append(runnable)

    monkeypatch.setattr(pbs_panel_mod.QThreadPool, "globalInstance",
                        staticmethod(lambda: SimpleNamespace(start=fake_start)))

    def _make_provider(cfg, timeout=15):
        prov = PbsProvider(cfg, timeout=timeout)
        prov._client = _FakePbsClient(boom=cfg.get("_boom", False))
        made.append(prov)
        return prov

    monkeypatch.setattr("virtdeck.pbs.workers.PbsProvider", _make_provider)
    p.started = started
    p.made = made
    return p


@pytest.fixture
def live_panel(qtbot, monkeypatch):
    """PbsPanel with the real _start: QThreadPool stubbed (workers are
    collected, never auto-run), PbsProvider faked in the workers module."""
    p = _make_live(monkeypatch)
    qtbot.addWidget(p)
    return p


def _drain_deferred_deletes():
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    QCoreApplication.processEvents()


class TestPbsWorkerTracking:
    def test_finished_worker_discarded_on_success(self, live_panel):
        p = live_panel
        p._start("datastores", tag=("ds", "pbs1"))
        assert len(p._workers) == 1
        w = p.started[0]
        w.run()  # same thread: done/finished fire synchronously
        assert p.made[0]._client.closed
        assert w not in p._workers

    def test_finished_worker_discarded_on_error(self, live_panel):
        p = live_panel
        boom_cfg = dict(_CFG, _boom=True)
        p._cfg_by_name["pbs1"] = boom_cfg
        p._start("datastores", tag=("ds", "pbs1"))
        w = p.started[0]
        w.run()
        assert p.made[0]._client.closed
        assert w not in p._workers

    def test_starts_connect_before_start_no_fast_finish_race(
            self, live_panel, monkeypatch):
        """A worker finishing instantly still removes itself: all
        connections are made before QThreadPool.start (audit 6.3.2a D9)."""
        p = live_panel

        class _InstantProvider:
            def __init__(self, cfg, timeout=15):
                pass

            def datastores(self):
                return []

            def close(self):
                pass

        monkeypatch.setattr("virtdeck.pbs.workers.PbsProvider",
                            _InstantProvider)
        p._start("datastores", tag=("ds", "pbs1"))
        w = p.started[0]
        w.run()
        assert p._workers == set()

    def test_concurrent_starts_capped(self, live_panel):
        p = live_panel
        from virtdeck.ui.pbs_panel import _MAX_PBS_WORKERS
        for _ in range(_MAX_PBS_WORKERS):
            p._start("jobs", tag=("jobs", "pbs1"))
        assert len(p.started) == _MAX_PBS_WORKERS
        p._start("jobs", tag=("jobs", "pbs1"))
        assert len(p.started) == _MAX_PBS_WORKERS  # 17th refused
        assert "Too many concurrent operations" in p._status_lbl.text()

    def test_panel_destroyed_while_worker_running_is_safe(self, qapp,
                                                          monkeypatch):
        p = _make_live(monkeypatch)  # deliberately NOT tracked by qtbot
        p._start("datastores", tag=("ds", "pbs1"))
        w = p.started[0]
        p.close()
        p.deleteLater()
        _drain_deferred_deletes()
        # The panel is destroyed; the worker completes and emits into the
        # void — no callback into the destroyed widget, no exception.
        w.run()
        assert p.made[0]._client.closed


# --- audit 6.3.2b D10: jobs result states reach the UI ----------------------


def _job(kind="sync", id_="s1", store="main"):
    return PbsJob(id=id_, kind=kind, store=store, schedule="daily")


class TestJobsResultStates:
    def _with_server(self, panel):
        panel._server = "pbs1"  # fixture leaves it empty; tags filter on it
        return panel

    def test_partial_load_marks_unread_kinds(self, panel):
        """Partially loaded jobs are shown with an explicit note —
        a failed kind must not look like a confident 'no jobs'."""
        self._with_server(panel)._on_worker_done(
            ("jobs", "pbs1"), ([_job()], ["verify", "prune"]))
        assert panel._jobs_table.rowCount() == 1
        text = panel._status_lbl.text()
        assert "verify" in text and "prune" in text

    def test_empty_success_is_not_an_error(self, panel):
        self._with_server(panel)._on_worker_done(("jobs", "pbs1"), ([], []))
        assert panel._jobs_table.rowCount() == 0
        assert panel._status_lbl.text() == ""

    def test_full_success_after_partial_clears_the_note(self, panel):
        self._with_server(panel)._on_worker_done(
            ("jobs", "pbs1"), ([], ["verify"]))
        assert panel._status_lbl.text()
        panel._on_worker_done(("jobs", "pbs1"), ([_job()], []))
        assert panel._status_lbl.text() == ""

    def test_stale_server_result_is_ignored(self, panel):
        self._with_server(panel)._on_worker_done(
            ("jobs", "other"), ([_job()], ["verify"]))
        assert panel._jobs_table.rowCount() == 0
        assert panel._status_lbl.text() == ""

    def test_total_failure_shows_error_text(self, panel):
        self._with_server(panel)._on_worker_failed(
            ("jobs", "pbs1"),
            "could not read jobs (sync, verify, prune): boom")
        assert "could not read jobs" in panel._status_lbl.text()


# ── audit 6.3.3 D16: PBS task tracking in the panel ─────────────────────

import json

from PySide6.QtCore import QRunnable

from virtdeck.pbs.workers import _TrackerSignals


def _upid(n=1):
    return f"UPID:pbs:1:2:{n}:syncjob:j{n}:root@pam"


@pytest.fixture
def stub_tracker(monkeypatch):
    """Replace PbsTaskTracker with a no-thread stub; return started list."""
    started = []

    class StubTracker(QRunnable):
        def __init__(self, cfg, upid, **kw):
            super().__init__()
            self.cfg = cfg
            self.upid = upid
            self.kw = kw
            self.signals = _TrackerSignals()
            started.append(self)

        def run(self):  # never actually polled in UI tests
            pass

    monkeypatch.setattr(pbs_panel_mod, "PbsTaskTracker", StubTracker)
    return started


class TestTaskTracking:
    def test_run_done_starts_tracker_and_row(self, panel, stub_tracker):
        panel._server = "pbs1"
        panel._on_worker_done(
            ("run", "pbs1", "sync", "j1"), _upid())
        assert len(stub_tracker) == 1
        assert stub_tracker[0].upid == _upid()
        row = panel._ops[0]
        assert row["state"] == "starting"
        assert "sync/j1" in row["op"]
        assert panel._ops_table.rowCount() == 1

    def test_verify_done_tracks_datastore(self, panel, stub_tracker):
        panel._server = "pbs1"
        panel._on_worker_done(("verify", "pbs1", "main"), _upid(2))
        assert stub_tracker[0].upid == _upid(2)
        assert "main" in panel._ops[0]["op"]

    def test_run_done_without_upid_is_no_success(self, panel, stub_tracker):
        # contract drift guard: a start without UPID must not read as
        # a confirmed start
        panel._server = "pbs1"
        panel._on_worker_done(("run", "pbs1", "sync", "j1"), "")
        assert stub_tracker == []
        assert "not be confirmed" in panel._status_lbl.text()

    def test_stale_run_result_ignored(self, panel, stub_tracker):
        # a run that finished while the user switched servers must not
        # write anything into the current server's UI (§6.9)
        panel._server = "pbs1"
        panel._on_worker_done(("run", "other", "sync", "j1"), _upid())
        assert stub_tracker == []
        assert panel._status_lbl.text() == ""
        assert panel._ops == []

    def test_stale_verify_result_ignored(self, panel, stub_tracker):
        panel._server = "pbs1"
        panel._on_worker_done(("verify", "other", "main"), _upid())
        assert stub_tracker == []
        assert panel._status_lbl.text() == ""

    def test_duplicate_upid_not_tracked_twice(self, panel, stub_tracker):
        panel._server = "pbs1"
        panel._start_tracker("pbs1", _upid(), "Run job sync/j1")
        panel._start_tracker("pbs1", _upid(), "Run job sync/j1")
        assert len(stub_tracker) == 1
        assert "already being tracked" in panel._status_lbl.text()

    def test_tracking_limit_is_honest(self, panel, stub_tracker):
        panel._server = "pbs1"
        limit = pbs_panel_mod._MAX_PBS_TRACKERS
        for i in range(limit):
            panel._start_tracker("pbs1", _upid(i + 1), "op")
        assert len(stub_tracker) == limit
        panel._start_tracker("pbs1", _upid(limit + 1), "op")
        assert len(stub_tracker) == limit  # no new watcher
        assert "not be watched" in panel._status_lbl.text()

    def test_states_and_terminal_result_persist(self, panel, stub_tracker):
        panel._server = "pbs1"
        panel._start_tracker("pbs1", _upid(), "Run job sync/j1")
        key = ("pbs1", _upid())
        panel._on_tracker_update(key, ("running", ""))
        assert panel._ops[0]["state"] == "running"
        panel._on_tracker_update(key, ("failed", "Error: verify boom"))
        assert panel._ops[0]["state"] == "failed"
        assert "Task failed" in panel._status_lbl.text()
        # worker finished → resources freed, the result stays readable
        panel._on_tracker_finished(key, stub_tracker[0])
        assert key not in panel._trackers
        assert panel._ops[0]["state"] == "failed"
        assert "verify boom" in panel._ops_table.item(0, 2).text()

    def test_unknown_and_timeout_states(self, panel, stub_tracker):
        panel._server = "pbs1"
        panel._start_tracker("pbs1", _upid(), "op")
        key = ("pbs1", _upid())
        panel._on_tracker_update(key, ("unknown", "status unreadable"))
        assert panel._ops[0]["state"] == "unknown"
        assert "outcome unknown" in panel._status_lbl.text()
        panel._on_tracker_update(key, ("timeout", ""))
        assert panel._ops[0]["state"] == "timeout"
        assert "timed out" in panel._status_lbl.text()

    def test_success_state_shown(self, panel, stub_tracker):
        panel._server = "pbs1"
        panel._start_tracker("pbs1", _upid(), "op")
        panel._on_tracker_update(("pbs1", _upid()), ("success", ""))
        assert panel._ops[0]["state"] == "success"
        assert "successfully" in panel._status_lbl.text()

    def test_stale_server_update_ignored(self, panel, stub_tracker):
        panel._server = "pbs1"
        panel._start_tracker("pbs1", _upid(), "op")
        panel._on_tracker_update(("other", _upid()), ("failed", "x"))
        assert panel._ops[0]["state"] == "starting"
        assert panel._status_lbl.text() == ""

    def test_server_switch_filters_rows(self, panel, stub_tracker):
        panel.update_nodes_cfg([
            _CFG,
            {"name": "pbs2", "type": "pbs", "host": "h2", "port": 8007,
             "user": "root@pam", "token_value": "s"},
        ])
        panel._server = "pbs1"
        panel._start_tracker("pbs1", _upid(), "op")
        assert panel._ops_table.rowCount() == 1
        panel.show_server("pbs2")
        assert panel._ops_table.rowCount() == 0  # other server's ops hidden
        panel.show_server("pbs1")
        assert panel._ops_table.rowCount() == 1

    def test_close_sets_stop_events(self, panel, stub_tracker):
        panel._server = "pbs1"
        panel._start_tracker("pbs1", _upid(), "op")
        assert len(stub_tracker) == 1
        panel._stop_all_trackers()
        assert stub_tracker[0].kw["stop_event"].is_set()

    def test_finished_tracker_removed_from_registry(self, panel, stub_tracker):
        panel._server = "pbs1"
        panel._start_tracker("pbs1", _upid(), "op")
        key = ("pbs1", _upid())
        panel._on_tracker_finished(key, stub_tracker[0])
        assert key not in panel._trackers

    def test_update_after_widget_destroyed_is_safe(self, stub_tracker):
        # §6.10: a tracker finishing after the panel is destroyed must
        # not touch dead Qt objects (guards + Qt auto-disconnect).  No
        # qtbot registration: the C++ object is deleted by hand here and
        # pytest-qt must not try to close it again.
        panel = PbsPanel()
        panel.update_nodes_cfg([_CFG])
        panel._server = "pbs1"
        panel._start_tracker("pbs1", _upid(), "op")
        assert len(stub_tracker) == 1
        key = ("pbs1", _upid())
        panel.deleteLater()
        QCoreApplication.sendPostedEvents(panel, QEvent.DeferredDelete)
        panel._on_tracker_update(key, ("success", ""))   # must not raise
        panel._on_tracker_finished(key, stub_tracker[0])
        panel._render_ops()
        panel._stop_all_trackers()


def test_task_tracking_i18n_keys_translated():
    """Every new D16 UI key must exist in all shipped locales."""
    from pathlib import Path

    keys = [
        "Starting", "Success", "Failed", "Unknown outcome",
        "Watch timed out", "Run job {kind}/{id}",
        "Verify datastore {store}", "Operation",
        "This task is already being tracked",
        "Tracking limit reached — the result will not be watched; "
        "check the server",
        "Task finished successfully", "Task failed: {detail}",
        "Task outcome unknown: {detail}",
        "Task watch timed out — it may still be running on the server",
        "Job start could not be confirmed — no task id in the response",
    ]
    i18n_dir = Path(__file__).parents[1].parent / "virtdeck" / "ui" / "i18n"
    for lang in ("ru", "ar", "zh", "fr", "es"):
        data = json.loads((i18n_dir / f"{lang}.json").read_text(
            encoding="utf-8"))
        missing = [k for k in keys if k not in data]
        assert not missing, f"{lang}: missing {missing}"
