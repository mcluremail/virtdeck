"""Tests for PbsPanel — PBS datastore/snapshot/job views (B17 stage 2)."""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from virtdeck.domain.pbs import PbsDatastore, PbsJob, PbsSnapshot
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


def _ds(name="main", usage=0.5):
    return PbsDatastore(name=name, path=f"/mnt/{name}", usage=usage,
                        used_bytes=500 * 10**9, total_bytes=1000 * 10**9)


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
        panel._start("run_job", "sync", "s1", tag=("run", "pbs1"))
        assert panel.started[-1] == ("run_job", ("sync", "s1"), ("run", "pbs1"), {})


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
