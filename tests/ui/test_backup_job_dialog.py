"""Stage 6.2.1: BackupJobDialog contracts (audit D1–D3b).

Round-trip semantics: an unchanged edit produces NO parameters (PVE
keeps every key not present in the PUT), a pool/all job never degrades
into a vmid-list, prune-backups is preserved in full, and defaults the
API omits (remove/compress) are not invented by the form.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from virtdeck.ui.backup_job_dialog import (
    BackupJobDialog,
    selection_label,
)

STORAGES = [
    SimpleNamespace(storage="pbs1", content_list=["backup", "rootdir"]),
    SimpleNamespace(storage="local", content_list=["images"]),
]
POOLS = ["web", "db"]


@pytest.fixture(autouse=True)
def dialog(qtbot, monkeypatch):
    """Bind the module-level dialog factory to qtbot (QApplication)."""

    def _make(job=None):
        dlg = BackupJobDialog(storages=STORAGES, job=job, pools=POOLS)
        qtbot.addWidget(dlg)
        return dlg

    monkeypatch.setattr(sys.modules[__name__], "dialog", _make)


def select_mode(dlg, key):
    idx = dlg._sel_combo.findData(key)
    dlg._sel_combo.setCurrentIndex(idx)


def storage_combo_data():
    return None  # the first backup storage ("pbs1") is the default


# -- creation ----------------------------------------------------------------


def test_create_defaults_to_all_guests_like_pve():
    dlg = dialog()
    assert dlg._sel_combo.currentData() == "all"


def test_create_vmid_job_sends_vmid_only():
    dlg = dialog()
    select_mode(dlg, "vmid")
    dlg._vmid_edit.setText("100, 101")
    params = dlg.get_params()
    assert params["vmid"] == "100, 101"
    assert "all" not in params and "pool" not in params
    assert params["storage"] == "pbs1"


def test_create_all_job_sends_all_without_vmid():
    dlg = dialog()
    select_mode(dlg, "all")
    params = dlg.get_params()
    assert params["all"] == 1
    assert "vmid" not in params and "pool" not in params


def test_create_all_job_with_exclude():
    dlg = dialog()
    select_mode(dlg, "all")
    dlg._exclude_edit.setText("100,102")
    params = dlg.get_params()
    assert params["all"] == 1
    assert params["exclude"] == "100,102"


def test_create_pool_job_sends_pool():
    dlg = dialog()
    select_mode(dlg, "pool")
    dlg._pool_combo.setCurrentText("web")
    params = dlg.get_params()
    assert params["pool"] == "web"
    assert "vmid" not in params and "all" not in params


def test_create_empty_vmid_rejected():
    dlg = dialog()
    select_mode(dlg, "vmid")
    with pytest.raises(ValueError):
        dlg.get_params()


def test_create_word_all_in_vmid_field_rejected():
    # pve-vmid-list does not accept the word "all" — "select all" is the
    # separate boolean parameter, and the old form's vmid="all" fallback
    # was a guaranteed 400 (audit D1).
    dlg = dialog()
    select_mode(dlg, "vmid")
    dlg._vmid_edit.setText("all")
    with pytest.raises(ValueError):
        dlg.get_params()


def test_create_node_restriction():
    dlg = dialog()
    select_mode(dlg, "vmid")
    dlg._vmid_edit.setText("100")
    dlg._node_edit.setText("pve01")
    params = dlg.get_params()
    assert params["node"] == "pve01"
    assert params["vmid"] == "100"


# -- editing: unchanged save is a no-op ---------------------------------------


def test_edit_pool_job_no_changes_sends_nothing():
    # THE D2 regression: editing a pool job without changes must not
    # send vmid (PVE deletes pool/all/exclude when vmid arrives).
    dlg = dialog({"id": "job-1", "pool": "web", "storage": "pbs1",
                       "schedule": "02:00", "mode": "snapshot"})
    assert dlg._sel_combo.currentData() == "pool"
    assert dlg._pool_combo.currentText() == "web"
    assert dlg.get_params() == {}


def test_edit_all_job_no_changes_sends_nothing():
    dlg = dialog({"id": "job-1", "all": 1, "storage": "pbs1",
                       "schedule": "sat 02:00"})
    assert dlg._sel_combo.currentData() == "all"
    assert dlg.get_params() == {}


def test_edit_vmid_job_no_changes_sends_nothing():
    dlg = dialog({"id": "job-1", "vmid": "100,101",
                       "storage": "pbs1", "schedule": "02:00"})
    assert dlg._vmid_edit.text() == "100,101"
    assert dlg.get_params() == {}


def test_edit_degenerate_job_no_changes_sends_nothing():
    # a job without any selection stays intact: no invented vmid="all"
    dlg = dialog({"id": "job-1", "storage": "pbs1",
                       "schedule": "02:00"})
    assert dlg.get_params() == {}


def test_edit_pool_job_comment_only_change():
    dlg = dialog({"id": "job-1", "pool": "web", "storage": "pbs1",
                       "schedule": "02:00", "comment": "old"})
    dlg._notes_edit.setText("new comment")
    assert dlg.get_params() == {"comment": "new comment"}


def test_edit_vmid_list_changed():
    dlg = dialog({"id": "job-1", "vmid": "100,101",
                       "storage": "pbs1", "schedule": "02:00"})
    dlg._vmid_edit.setText("100,102")
    params = dlg.get_params()
    assert params == {"vmid": "100,102"}


def test_edit_pool_job_switches_to_all():
    dlg = dialog({"id": "job-1", "pool": "web", "storage": "pbs1",
                       "schedule": "02:00"})
    select_mode(dlg, "all")
    params = dlg.get_params()
    assert params["all"] == 1
    assert "vmid" not in params and "pool" not in params


def test_edit_vmid_job_switches_to_pool():
    dlg = dialog({"id": "job-1", "vmid": "100,101",
                       "storage": "pbs1", "schedule": "02:00"})
    select_mode(dlg, "pool")
    dlg._pool_combo.setCurrentText("db")
    params = dlg.get_params()
    assert params == {"pool": "db"}


def test_edit_all_job_exclude_cleared_uses_delete_param():
    dlg = dialog({"id": "job-1", "all": 1, "exclude": "100,102",
                       "storage": "pbs1", "schedule": "02:00"})
    assert dlg._exclude_edit.text() == "100,102"
    dlg._exclude_edit.setText("")
    params = dlg.get_params()
    assert params == {"delete": "exclude"}


def test_edit_all_job_exclude_added():
    dlg = dialog({"id": "job-1", "all": 1, "storage": "pbs1",
                       "schedule": "02:00"})
    dlg._exclude_edit.setText("105")
    params = dlg.get_params()
    assert params["all"] == 1 and params["exclude"] == "105"


def test_edit_node_added_and_cleared():
    dlg = dialog({"id": "job-1", "vmid": "100", "storage": "pbs1",
                       "schedule": "02:00"})
    dlg._node_edit.setText("pve01")
    assert dlg.get_params() == {"node": "pve01"}
    dlg._node_edit.setText("")
    assert dlg.get_params() == {}
    dlg2 = dialog({"id": "job-1", "vmid": "100", "node": "pve01",
                        "storage": "pbs1", "schedule": "02:00"})
    dlg2._node_edit.setText("")
    assert dlg2.get_params() == {"delete": "node"}


def test_edit_invalid_vmid_change_rejected():
    dlg = dialog({"id": "job-1", "vmid": "100", "storage": "pbs1",
                       "schedule": "02:00"})
    dlg._vmid_edit.setText("abc")
    with pytest.raises(ValueError):
        dlg.get_params()


# -- unknown fields survive (audit A4) ----------------------------------------


def test_edit_never_sends_unknown_fields():
    job = {"id": "job-1", "pool": "web", "storage": "pbs1",
           "schedule": "02:00", "mailto": "ops@example.com",
           "mailnotification": "failure", "performance": "max-workers=2",
           "fleecing": "storage=local", "notes-template": "{{guest}}",
           "repeat-missed": 1}
    dlg = dialog(job)
    dlg._notes_edit.setText("changed")
    params = dlg.get_params()
    assert params == {"comment": "changed"}
    for key in ("mailto", "mailnotification", "performance", "fleecing",
                "notes-template", "repeat-missed"):
        assert key not in params


# -- defaults: absent ≠ explicit ≠ changed (audit D3b) -------------------------


def test_remove_absent_reads_as_checked_but_stays_unsent():
    # PVE default remove=1: the checkbox reflects it, but an unchanged
    # save must not flip the job's pruning off by sending remove=0.
    dlg = dialog({"id": "job-1", "vmid": "100", "storage": "pbs1",
                       "schedule": "02:00"})
    assert dlg._remove_check.isChecked()
    assert dlg.get_params() == {}


def test_remove_absent_user_disables_prune():
    dlg = dialog({"id": "job-1", "vmid": "100", "storage": "pbs1",
                       "schedule": "02:00"})
    dlg._remove_check.setChecked(False)
    assert dlg.get_params() == {"remove": 0}


def test_remove_explicit_zero_stays_unchecked_unsent():
    dlg = dialog({"id": "job-1", "vmid": "100", "storage": "pbs1",
                       "schedule": "02:00", "remove": 0})
    assert not dlg._remove_check.isChecked()
    assert dlg.get_params() == {}


def test_compress_absent_reads_as_lzo_but_stays_unsent():
    dlg = dialog({"id": "job-1", "vmid": "100", "storage": "pbs1",
                       "schedule": "02:00"})
    assert dlg._compress_combo.currentData() == "lzo"
    assert dlg.get_params() == {}


# -- prune-backups (audit D3) --------------------------------------------------


def test_prune_object_policy_preserved_on_unchanged_save():
    # PVE 8 returns prune-backups as an OBJECT in GET responses; the old
    # form collapsed it to keep-last=3 on save.
    dlg = dialog({"id": "job-1", "vmid": "100", "storage": "pbs1",
                       "schedule": "02:00", "remove": 1,
                       "prune-backups": {"keep-daily": 7,
                                         "keep-weekly": 4,
                                         "keep-last": 3}})
    assert dlg._prune_edit.text() == "keep-daily=7,keep-weekly=4,keep-last=3"
    assert dlg.get_params() == {}


def test_prune_string_policy_preserved_on_unchanged_save():
    dlg = dialog({"id": "job-1", "vmid": "100", "storage": "pbs1",
                       "schedule": "02:00", "remove": 1,
                       "prune-backups": "keep-daily=7,keep-monthly=6"})
    assert dlg.get_params() == {}


def test_prune_policy_edit_keeps_all_elements():
    dlg = dialog({"id": "job-1", "vmid": "100", "storage": "pbs1",
                       "schedule": "02:00", "remove": 1,
                       "prune-backups": {"keep-daily": 7,
                                         "keep-weekly": 4}})
    dlg._prune_edit.setText("keep-daily=5,keep-weekly=4,keep-monthly=6")
    params = dlg.get_params()
    assert params["prune-backups"] == \
        "keep-daily=5,keep-weekly=4,keep-monthly=6"
    assert "keep-last" not in str(params)


def test_prune_unparsable_policy_rejected():
    dlg = dialog({"id": "job-1", "vmid": "100", "storage": "pbs1",
                       "schedule": "02:00", "remove": 1,
                       "prune-backups": "keep-daily=7"})
    dlg._prune_edit.setText("keep-daily=seven")
    with pytest.raises(ValueError):
        dlg.get_params()


def test_prune_absent_and_remove_enabled_sends_no_policy():
    # remove=1 without an explicit policy → the storage's own retention
    # applies; the form must not invent keep-last=3.
    dlg = dialog({"id": "job-1", "vmid": "100", "storage": "pbs1",
                       "schedule": "02:00", "remove": 1})
    dlg._prune_edit.setText("")
    assert dlg.get_params() == {}


# -- schedule / enabled / mode diffs --------------------------------------------


def test_schedule_unchanged_daily_unsent():
    dlg = dialog({"id": "job-1", "vmid": "100", "storage": "pbs1",
                       "schedule": "02:00"})
    assert dlg._schedule_type_combo.currentData() == "daily"
    assert dlg.get_params() == {}


def test_schedule_changed_sent():
    dlg = dialog({"id": "job-1", "vmid": "100", "storage": "pbs1",
                       "schedule": "02:00"})
    from PySide6.QtCore import QTime
    dlg._time_edit.setTime(QTime(3, 30))
    assert dlg.get_params() == {"schedule": "03:30"}


def test_enabled_changed_sent():
    dlg = dialog({"id": "job-1", "vmid": "100", "storage": "pbs1",
                       "schedule": "02:00", "enabled": 0})
    assert not dlg._enabled_check.isChecked()
    assert dlg.get_params() == {}
    dlg._enabled_check.setChecked(True)
    assert dlg.get_params() == {"enabled": 1}


def test_storage_changed_sent():
    dlg = dialog({"id": "job-1", "vmid": "100", "storage": "pbs1",
                       "schedule": "02:00"})
    idx = dlg._storage_combo.findData("pbs1")
    assert idx >= 0
    assert dlg.get_params() == {}


# -- table labels (audit A2) -----------------------------------------------------


def test_selection_labels():
    assert selection_label({"all": 1}) == "All guests"
    assert selection_label({"all": 1, "exclude": "100,102"}) == \
        "All guests (excl: 100,102)"
    assert selection_label({"pool": "web"}) == "pool: web"
    assert selection_label({"vmid": "100,101", "node": "pve01"}) == \
        "100,101  @pve01"
    assert selection_label({}) == "—"


# -- end-to-end: dialog → provider → fake server → re-read -------------------

def _roundtrip_provider(monkeypatch):
    from tests.harness import fake_pve_cfg, install_fake_pve
    from tests.harness.scenarios import make_pve_cluster
    from virtdeck.provider import ProxmoxProvider
    api = make_pve_cluster("alpha")
    install_fake_pve(monkeypatch, api)
    return api, ProxmoxProvider(fake_pve_cfg("alpha"))


def test_roundtrip_pool_job_survives_edit(monkeypatch, qtbot):
    """D2 end-to-end: edit a pool job in the dialog, PUT through the
    real provider against the fake server, re-read: the selection and
    fields the form does not know survive; only the comment changed."""
    from tests.harness.scenarios import make_pve_cluster as _mk  # noqa: F401
    api, provider = _roundtrip_provider(monkeypatch)
    api.backup_jobs.append({"id": "job-1", "pool": "prod",
                            "storage": "pbs1", "schedule": "02:00",
                            "mailto": "ops@example.com"})
    with provider:
        job = next(j for j in provider.cluster.list_backup_jobs()
                   if j["id"] == "job-1")
        dlg = BackupJobDialog(storages=STORAGES, job=job, pools=POOLS)
        qtbot.addWidget(dlg)
        assert dlg._sel_combo.currentData() == "pool"
        dlg._notes_edit.setText("monthly")
        provider.cluster.update_backup_job("job-1", dlg.get_params(),
                                           pve_major=7)
        job2 = next(j for j in provider.cluster.list_backup_jobs()
                    if j["id"] == "job-1")
    assert job2["pool"] == "prod"
    assert job2["comment"] == "monthly"
    assert job2["mailto"] == "ops@example.com"
    assert "vmid" not in job2 and "all" not in job2


def test_roundtrip_exclude_clear(monkeypatch, qtbot):
    """Clearing exclude on an all=1 job goes through PUT ``delete``:
    the server keeps all=1 and drops only the exclude list."""
    api, provider = _roundtrip_provider(monkeypatch)
    api.backup_jobs.append({"id": "job-1", "all": 1, "exclude": "100,102",
                            "storage": "pbs1", "schedule": "02:00"})
    with provider:
        job = next(j for j in provider.cluster.list_backup_jobs()
                   if j["id"] == "job-1")
        dlg = BackupJobDialog(storages=STORAGES, job=job, pools=POOLS)
        qtbot.addWidget(dlg)
        dlg._exclude_edit.setText("")
        provider.cluster.update_backup_job("job-1", dlg.get_params(),
                                           pve_major=7)
        job2 = next(j for j in provider.cluster.list_backup_jobs()
                    if j["id"] == "job-1")
    assert job2["all"] == 1
    assert "exclude" not in job2
