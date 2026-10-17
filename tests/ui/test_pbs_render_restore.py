"""GAP-8 / R12: the PBS path — healthy renders with data and the restore
flow up to the confirmation screen.

A real PBS server is not available in the environment (owner decision:
the behavioral run against a live PBS is postponed); the transport seam
(tests/harness install.pbs_session) substitutes FakePbsApi under the
REAL provider/workers, so the panel's async render path is exercised
for real — only the wire is fake.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from tests.harness.fake_pbs import FakePbsApi
from tests.harness.install import pbs_session
from virtdeck.domain.enums import VmStatus, VmType
from virtdeck.domain.vm import Vm
from virtdeck.pbs.client import PbsClient
from virtdeck.ui.detail_panel import DetailPanel
from virtdeck.ui.detail_panel._vm_tabs import VMTabs
from virtdeck.ui.pbs_panel import PbsPanel
from virtdeck.ui.vm_restore_dialog import VmRestoreDialog

_CFG = {
    "name": "pbs1", "type": "pbs", "host": "pbs.local",
    "port": 8007, "user": "root@pam", "token_value": "secret",
    "trust_ssl": True,
}


@pytest.fixture()
def pbs_api():
    api = FakePbsApi()
    api.add_datastore("tank", total=1000 * 10**9, used=430 * 10**9)
    api.add_datastore("vault", total=500 * 10**9, used=40 * 10**9)
    api.add_snapshot("tank", 100, backup_time=1727740800)
    api.add_snapshot("tank", 101, backup_time=1727827200)
    api.add_snapshot("tank", 301, backup_type="ct", backup_time=1727830000)
    return api


@pytest.fixture()
def pbs_panel(qtbot, monkeypatch, pbs_api):
    """PbsPanel whose workers talk to FakePbsApi through the real client."""
    orig = PbsClient.__init__

    def patched(self, cfg, timeout=15, http=None):
        orig(self, cfg, timeout=timeout, http=http or pbs_session(pbs_api))

    monkeypatch.setattr(PbsClient, "__init__", patched)
    panel = PbsPanel()
    qtbot.addWidget(panel)
    panel.update_nodes_cfg([_CFG])
    return panel


def test_healthy_datastore_render_end_to_end(pbs_panel, qtbot, pbs_api):
    """show_server → datastore list → datastore view with status,
    snapshots — all rendered from the fake wire through real workers."""
    pbs_panel.show_server("pbs1")
    qtbot.waitUntil(
        lambda: pbs_panel._ds_table.rowCount() == 2, timeout=15000)

    pbs_panel.show_datastore("pbs1", "tank")
    qtbot.waitUntil(
        lambda: pbs_panel._snap_table.rowCount() >= 3, timeout=15000)
    # three snapshots rendered with owner and verify state
    owners = {pbs_panel._snap_table.item(r, 1).text()
              for r in range(pbs_panel._snap_table.rowCount())}
    assert owners == {"root@pam"}
    verify = {pbs_panel._snap_table.item(r, 2).text()
              for r in range(pbs_panel._snap_table.rowCount())}
    assert verify  # verify column rendered


def test_restore_reaches_confirmation_screen(qtbot, monkeypatch):
    """R12: from a backup row on the VM Backups tab the restore flow
    reaches the confirmation dialog with the archive, the next free
    VMID and the node's backup storages — and stops there (the dialog
    is rejected; no worker is started)."""
    panel = DetailPanel([])
    qtbot.addWidget(panel)
    panel._ensure_tabs()
    panel._cfg_by_name = {"h1": {"name": "h1", "host": "10.0.0.1",
                                 "user": "u@pam", "token_name": "t",
                                 "token_value": "s"}}
    vm = Vm(vmid=100, name="web", vm_type=VmType.QEMU, node="n1",
            host_name="h1", pool="", status=VmStatus.STOPPED, hastate="",
            tags="", template=False, cpu_fraction=0.1, mem_bytes=1,
            maxmem_bytes=2, disk_bytes=0, maxdisk_bytes=0, uptime_seconds=1,
            netin_bytes=0, netout_bytes=0, diskread_bytes=0,
            diskwrite_bytes=0, conn_id="h1")
    panel._last_vm_data = vm
    panel.all_vms = [vm]
    stor_rep = SimpleNamespace = type("S", (), {})()
    stor_rep.content_list = ["backup", "images"]
    stor_rep.node = "n1"
    stor_rep.host_name = "h1"
    stor_rep.storage = "local"
    panel.all_storages = [stor_rep]

    tabs = VMTabs(panel)
    volid = "pbs1:backup/vm/100/2026-05-06T07:08:09Z"
    tabs.populate_vm_backups_table([
        {"volid": volid, "size": 42 * 10**9, "format": "pbs-vm",
         "type": "backup", "storage": "pbs1"},
        {"volid": "local:backup/vzdump-qemu-100-2026_04_01.foo",
         "size": 21 * 10**9, "format": "vma.zst", "type": "backup",
         "storage": "local"},
    ])
    panel.vm_backup_table.selectRow(0)

    captured = {}
    started = []

    def fake_exec(self):
        captured["volid"] = self._volid
        captured["next_vmid"] = self._vmid_spin.value()
        captured["storages"] = [self._storage_combo.itemText(i) for i in
                                range(self._storage_combo.count())]
        return QDialog.DialogCode.Rejected  # stop at confirmation

    monkeypatch.setattr(VmRestoreDialog, "exec", fake_exec)

    class _Guard:  # no restore worker may start in this test
        def __getattr__(self, name):
            raise AssertionError("restore worker started")

    monkeypatch.setattr("virtdeck.backend.VmRestoreWorker", _Guard)
    tabs.on_vm_restore()

    assert captured["volid"] == volid
    assert captured["next_vmid"] == 101  # next free VMID
    assert any("local" in s for s in captured["storages"])
    del started
