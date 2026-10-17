"""Stage 6 (forms, tables, data) gates: Д8 form pattern, DELIGHT-2/A9/A10
table conventions, U4/U21/U23/U24 form micro-batch, U36 DPR icons,
U37 AccessibleName, GAP-11 task -> object navigation.

Audit refs: Д8 (DELIGHT-4/6), DELIGHT-2, A9/A10, U4/U21/U23/U24, U36,
U37, GAP-11.
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QComboBox,
)

from virtdeck.ui.theme import Color, fill_bytes_column
from virtdeck.domain.enums import NodeStatus, VmStatus, VmType
from virtdeck.domain.node import Node
from virtdeck.domain.repositories import NodeRepository, VmRepository
from virtdeck.domain.task import Task
from virtdeck.domain.vm import Vm

G = 1024 ** 3


def _node(name, status=NodeStatus.ONLINE, cluster="rep1"):
    return Node(host_name=name, node=name, cluster=cluster,
                status=status, error="", cpu_fraction=0.3,
                cpu_sockets=2, mem_bytes=2 * G, maxmem_bytes=8 * G,
                disk_bytes=10 * G, maxdisk_bytes=100 * G, uptime_seconds=1,
                pve_version_raw="8.0", kernel_version="k", qemu_version="q",
                lxc_version="l", is_cluster=bool(cluster), conn_id=name)


def _vm(vmid, name, node):
    return Vm(vmid=vmid, name=name, vm_type=VmType.QEMU, node=node,
              host_name=node, pool="", status=VmStatus.RUNNING,
              hastate="", tags="", template=False, cpu_fraction=0.1,
              mem_bytes=G, maxmem_bytes=2 * G, disk_bytes=0,
              maxdisk_bytes=0, uptime_seconds=1, netin_bytes=0,
              netout_bytes=0, diskread_bytes=0, diskwrite_bytes=0,
              conn_id=node)


def _task(upid, node="pve-alpha", status="OK", vmid=100, endtime=200.0):
    return Task(upid=upid, node=node, task_type="qmigrate", status=status,
                starttime=100.0, endtime=endtime, user="root@pam",
                vmid=vmid, display_name=None, vm_name="web-01")


# ── Д8: the form pattern ────────────────────────────────────────────


class TestFormPatternBackupJob:
    @pytest.fixture()
    def dlg(self, qtbot):
        from virtdeck.ui.backup_job_dialog import BackupJobDialog

        d = BackupJobDialog()
        qtbot.addWidget(d)
        d.show()
        return d

    def test_single_form_layout(self, dlg):
        """DELIGHT-4: one QFormLayout — independent per-section label
        columns made the field edges ragged."""
        forms = dlg.findChildren(QFormLayout)
        assert len(forms) == 1

    def test_field_edges_aligned(self, dlg):
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QComboBox, QLineEdit

        form = dlg.findChildren(QFormLayout)[0]
        dlg.resize(560, 760)
        xs = []
        for r in range(form.rowCount()):
            item = form.itemAt(r, QFormLayout.ItemRole.FieldRole)
            w = item.widget() if item else None
            if isinstance(w, (QLineEdit, QComboBox)):
                xs.append(w.mapTo(dlg, QPoint(0, 0)).x())
        assert xs, "no editable fields found"
        assert len(set(xs)) == 1, f"field edges drift: {sorted(set(xs))}"

    def test_sections_present(self, dlg):
        titles = [w.text() for w in dlg.findChildren(QLabel)
                  if w.objectName() == "sectionTitle"]
        assert "Selection" in titles
        assert "Backup" in titles
        assert "Schedule" in titles
        assert "Retention and notes" in titles

    def test_pool_label_capitalized(self, dlg):
        from virtdeck.ui.i18n import tr

        form = dlg.findChildren(QFormLayout)[0]
        labels = []
        for r in range(form.rowCount()):
            item = form.itemAt(r, QFormLayout.ItemRole.LabelRole)
            if item and item.widget():
                labels.append(item.widget().text())
        assert tr("Pool:") in labels
        assert "pool" not in [l for l in labels if l == "pool"]

    def test_enabled_in_header_band(self, dlg):
        form = dlg.findChildren(QFormLayout)[0]
        item = form.itemAt(0, QFormLayout.ItemRole.SpanningRole)
        assert item is not None and item.layout() is not None
        # the Enabled checkbox lives in the header band, not an orphan row
        assert item.layout().indexOf(dlg._enabled_check) >= 0


class TestFormPatternMigrate:
    @pytest.fixture()
    def dlg(self, qtbot):
        from virtdeck.ui.migrate_vm_dialog import MigrateVMDialog

        d = MigrateVMDialog(vm_info={"name": "web-01", "vmid": 100,
                                     "type": "qemu", "node": "pve-alpha"},
                            cluster_nodes=[_node("pve-alpha"),
                                           _node("pve-beta")],
                            current_node="pve-alpha")
        qtbot.addWidget(d)
        d.show()
        return d

    def test_single_form_layout_both_groups(self, dlg):
        """DELIGHT-6: info block and target block share one label
        column — no two vertical rhythms."""
        forms = dlg.findChildren(QFormLayout)
        assert len(forms) == 1
        assert dlg.findChildren(QFormLayout)[0].rowCount() >= 6

    def test_field_edges_aligned(self, dlg):
        from PySide6.QtCore import QPoint

        form = dlg.findChildren(QFormLayout)[0]
        dlg.resize(480, 420)
        combo_x = dlg.target_combo.mapTo(dlg, QPoint(0, 0)).x()
        # every FIELD row (it has a label) sits on one vertical line;
        # section headers span both columns and are skipped
        for r in range(form.rowCount()):
            if form.itemAt(r, QFormLayout.ItemRole.LabelRole) is None:
                continue
            item = form.itemAt(r, QFormLayout.ItemRole.FieldRole)
            w = item.widget() if item else None
            if isinstance(w, QLabel) and w.text():
                assert w.mapTo(dlg, QPoint(0, 0)).x() == combo_x


# ── DELIGHT-2 / A9: the tasks table ─────────────────────────────────


class TestTasksTableReadability:
    def test_error_status_not_truncated(self, qtbot):
        from virtdeck.ui.widgets.cluster_tasks_widget import \
            ClusterTasksWidget

        w = ClusterTasksWidget()
        qtbot.addWidget(w)
        err = ("migration aborted: storage 'local-zfs' is full "
               "(timeout while waiting for free space)")
        w.set_tasks([_task("UPID:pve:err", status=err)])
        assert w.table.item(0, 5).text() == err

    def test_running_is_neutral_not_amber(self, qtbot):
        from virtdeck.ui.widgets.cluster_tasks_widget import \
            ClusterTasksWidget

        w = ClusterTasksWidget()
        qtbot.addWidget(w)
        w.set_tasks([_task("UPID:pve:run", status="RUNNING", endtime=0)])
        cell = w.table.item(0, 1)
        assert cell.text() == "running..."
        assert QColor(cell.foreground().color()) == QColor(Color.TEXT_SEC)


# ── A10: byte columns ───────────────────────────────────────────────


class TestByteColumns:
    def test_one_unit_per_column(self, qtbot):
        from PySide6.QtWidgets import QTableWidget

        t = QTableWidget(3, 1)
        fill_bytes_column(t, 0, [500 * G, 2.5 * 1024 * G, 0])
        units = {t.item(r, 0).text().split()[-1] for r in range(3)}
        assert units == {"TiB"}, units

    def test_numbers_right_aligned_and_sortable(self, qtbot):
        from PySide6.QtWidgets import QTableWidget

        t = QTableWidget(2, 1)
        fill_bytes_column(t, 0, [2 * G, 1 * G])
        it = t.item(0, 0)
        assert it.textAlignment() & Qt.AlignmentFlag.AlignRight
        assert it.data(Qt.ItemDataRole.UserRole) == 2 * G

    def test_none_is_a_dash_not_a_zero(self, qtbot):
        from PySide6.QtWidgets import QTableWidget

        t = QTableWidget(1, 1)
        fill_bytes_column(t, 0, [None])
        assert t.item(0, 0).text() == "—"

    def test_pbs_datastores_use_one_unit(self, qtbot):
        from types import SimpleNamespace

        from virtdeck.ui.pbs_panel import PbsPanel

        p = PbsPanel()
        p.update_nodes_cfg([{"name": "pbs1", "type": "pbs", "skip": False}])
        p.show_server("pbs1")
        stores = [
            SimpleNamespace(name="big", usage=0.4,
                            usage_pct=lambda: 40.0, used_bytes=900 * G,
                            total_bytes=2 * 1024 * G, status_ok=True,
                            path="/srv"),
            SimpleNamespace(name="small", usage=0.1,
                            usage_pct=lambda: 10.0, used_bytes=100 * G,
                            total_bytes=500 * G, status_ok=True,
                            path="/srv2"),
        ]
        p._fill_ds_table(stores)
        used_units = {p._ds_table.item(r, 2).text().split()[-1]
                      for r in range(2)}
        assert used_units == {"GiB"}
        # and numbers are right-aligned
        assert (p._ds_table.item(0, 2).textAlignment()
                & Qt.AlignmentFlag.AlignRight)


# ── U36: HiDPI icons ────────────────────────────────────────────────


class TestDprIcons:
    def test_icon_renders_at_device_pixel_ratio(self, qapp):
        from virtdeck.ui.icons import _HOST, _render_svg_pixmap

        pm = _render_svg_pixmap(
            _HOST.format(c="#000", c2="#111", ok="#222"), 16, dpr=2.0)
        # U36: the bitmap is 2x and tagged — 16 logical px stay 16
        # logical px on a HiDPI screen, no stretching
        assert pm.width() == 32
        assert pm.devicePixelRatio() == 2.0


# ── U37: AccessibleName ─────────────────────────────────────────────


class TestAccessibleNames:
    def test_status_bar_combos_are_named(self, main_window):
        mw = main_window
        assert mw._lang_combo.accessibleName() == "Interface language"
        assert mw._theme_combo.accessibleName() == "Theme"

    def test_toolbar_buttons_are_named(self, main_window):
        # U37: the tool buttons are icon-only — the accessible name
        # lives on the QToolButton (QAction has no accessibleName)
        for action, _kind in main_window._toolbar_icon_actions:
            btn = main_window._toolbar.widgetForAction(action)
            assert btn is not None
            assert btn.accessibleName(), f"no name for {action.text()}"


# ── U21/U23/U24/U4: the form micro-batch ────────────────────────────


class TestAddServerMicro:
    @pytest.fixture()
    def dlg(self, qtbot):
        from virtdeck.ui.add_server_dialog import AddServerDialog

        d = AddServerDialog()
        qtbot.addWidget(d)
        return d

    def test_password_placeholder_is_words_not_bullets(self, dlg):
        # U4: a bullet placeholder reads as "already filled"
        assert dlg.pwd_input.placeholderText() == "enter password"

    def test_pbs_hides_cluster_field_and_separator(self, dlg):
        # U23: the cluster FIELD hides with its label; the token
        # section's trailing separator does not dangle
        dlg.type_combo.setCurrentIndex(1)  # PBS
        assert not dlg.cluster_input.isVisibleTo(dlg)
        assert not dlg._sep_token.isVisibleTo(dlg)
        dlg.type_combo.setCurrentIndex(0)  # PVE
        assert dlg.cluster_input.isVisibleTo(dlg)

    def test_port_99999_rejected(self, dlg):
        # U24: the digit validator alone admits 99999
        dlg.type_combo.setCurrentIndex(1)  # PBS path validates the port
        dlg.port_input.setText("99999")
        assert dlg._port_invalid()
        dlg.host_input.setText("pbs1")
        dlg.pwd_input.setText("secret")
        dlg._on_add()
        assert "65535" in dlg.status_label.text()
        assert not dlg.result()

    def test_enter_submits(self, dlg):
        assert dlg.add_btn.isDefault()


class TestCreateVmNoSilentFallbacks:
    def test_missing_storage_blocks_creation(self, qtbot, monkeypatch,
                                             tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from virtdeck.ui.create_vm_dialog import CreateVmDialog

        d = CreateVmDialog()
        qtbot.addWidget(d)
        d.name_input.setText("web-01")
        d.storage_combo.clear()  # no storage offered by the node
        d._on_create()
        assert not d.result(), "created with a silent local-lvm fallback"
        assert d.storage_combo.styleSheet()  # error border, no dialog

    def test_bad_vlan_blocks_creation(self, qtbot, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        from virtdeck.ui.create_vm_dialog import CreateVmDialog

        d = CreateVmDialog()
        qtbot.addWidget(d)
        d.name_input.setText("web-01")
        if not d.storage_combo.currentData():
            d.storage_combo.addItem("local", "local")
        d.vlan_input.setText("99999")
        d._on_create()
        assert not d.result(), "a broken VLAN tag was silently dropped"
        assert d.vlan_input.styleSheet()


# ── GAP-11: double-click on a task -> open the object ───────────────


class TestTaskNavigation:
    def test_double_click_emits_the_task(self, qtbot):
        from virtdeck.ui.widgets.cluster_tasks_widget import \
            TASK_DATA_ROLE, ClusterTasksWidget

        w = ClusterTasksWidget()
        qtbot.addWidget(w)
        task = _task("UPID:pve:mig", status="RUNNING", endtime=0)
        w.set_tasks([task])
        got = []
        w.navigate_requested.connect(got.append)
        w.table.itemDoubleClicked.emit(w.table.item(0, 0))
        assert got and got[0] is task
        assert w.table.item(0, 0).data(TASK_DATA_ROLE) is task

    def test_mainwindow_navigates_to_the_vm(self, main_window):
        mw = main_window
        nr, vr = NodeRepository(), VmRepository()
        nr.add(_node("pve-alpha"))
        vm = _vm(100, "web-01", "pve-alpha")
        vr.add(vm)
        mw._node_repo, mw._vm_repo = nr, vr
        mw.tree_panel.update_data([nr.all()[0]], [vm], [], final=True,
                                  node_repo=nr, vm_repo=vr)
        task = _task("UPID:pve-a:mig", node="pve-alpha", vmid=100)
        mw._on_task_navigate(task)
        assert mw.tree_panel.get_current_item_key() == ("pve-alpha", 100,
                                                        "pve-alpha")

    def test_host_task_falls_back_to_the_node(self, main_window):
        mw = main_window
        nr = NodeRepository()
        nr.add(_node("pve-alpha"))
        mw._node_repo = nr
        mw.tree_panel.update_data([nr.all()[0]], [], [], final=True,
                                  node_repo=nr, vm_repo=VmRepository())
        task = Task(upid="UPID:pve-a:apt", node="pve-alpha",
                    task_type="aptupdate", status="OK", starttime=1.0,
                    endtime=2.0, user="root@pam", vmid=None,
                    display_name=None, vm_name=None)
        mw._on_task_navigate(task)
        key = mw.tree_panel.get_current_item_key()
        assert key and key[0] == "host"
