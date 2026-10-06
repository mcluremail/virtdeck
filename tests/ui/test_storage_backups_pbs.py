"""B17 stage 1: PBS backup snapshot columns and actions in the Backups tab."""

from types import SimpleNamespace

from PySide6.QtCore import Qt

from virtdeck.ui.detail_panel import DetailPanel
from virtdeck.ui.detail_panel._constants import TabIndex
from virtdeck.ui.detail_panel._storage_tabs import StorageTabs
from virtdeck.ui.i18n import tr
from virtdeck.ui.theme import Color

PBS_ITEM = {
    "volid": "pbs1:backup/vm/100/2024-05-06T07:08:09Z",
    "size": 1073741824,
    "owner": "root@pam",
    "verification": {"state": "ok"},
    "notes": "daily",
}


def _build(qtbot):
    panel = DetailPanel([])
    qtbot.addWidget(panel)
    panel._cfg_by_name = {}
    panel._ensure_tabs()
    return panel, StorageTabs(panel)


def _load(qtbot, storage_type="pbs"):
    panel, storage_tabs = _build(qtbot)
    rep = SimpleNamespace(
        content_list=["backup"],
        node="n1",
        host_name="h1",
        storage_type=storage_type,
    )
    # No host config -> load_storage_content returns before spawning workers,
    # but headers and the pbs flag must already be set.
    storage_tabs.load_storage_content("pbs1", [rep], rep)
    return panel, storage_tabs


def test_pbs_backup_headers(qtbot):
    panel, _ = _load(qtbot, storage_type="pbs")
    table = panel.storage_backups_table
    assert panel.tabs.isTabVisible(TabIndex.BACKUPS)
    assert panel._storage_backups_pbs is True
    assert table.columnCount() == 6
    assert table.horizontalHeaderItem(0).text() == tr("Snapshot")
    assert table.horizontalHeaderItem(1).text() == tr("Owner")
    assert table.horizontalHeaderItem(2).text() == tr("Verify")
    assert table.horizontalHeaderItem(5).text() == tr("Notes")


def test_vzdump_backup_headers_unchanged(qtbot):
    panel, _ = _load(qtbot, storage_type="dir")
    table = panel.storage_backups_table
    assert panel._storage_backups_pbs is False
    assert table.columnCount() == 5
    assert table.horizontalHeaderItem(0).text() == tr("VM")


def test_populate_pbs_rows(qtbot):
    panel, storage_tabs = _load(qtbot, storage_type="pbs")
    storage_tabs.populate_storage_backups_table([PBS_ITEM], "h1", "n1")
    table = panel.storage_backups_table
    assert table.rowCount() == 1
    assert table.item(0, 0).data(Qt.UserRole) == PBS_ITEM["volid"]
    assert table.item(0, 0).data(Qt.UserRole + 1) == ("h1", 100, "n1")
    assert table.item(0, 1).text() == "root@pam"
    assert table.item(0, 2).text() == "ok"
    assert table.item(0, 3).text()
    assert table.item(0, 4).text()  # created timestamp rendered
    assert table.item(0, 5).text() == "daily"


def test_populate_marks_failed_verify_red(qtbot):
    panel, storage_tabs = _load(qtbot, storage_type="pbs")
    item = dict(PBS_ITEM, verification={"state": "failed"})
    storage_tabs.populate_storage_backups_table([item], "h1", "n1")
    table = panel.storage_backups_table
    assert table.item(0, 2).text() == "failed"
    assert table.item(0, 2).foreground().color().name() == Color.DANGER
