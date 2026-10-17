from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from .i18n import tr
from .theme import Color


class MigrateVMDialog(QDialog):
    def __init__(self, parent=None, vm_info=None, cluster_nodes=None, current_node=""):
        super().__init__(parent)
        self._vm_info = vm_info or {}
        self._cluster_nodes = cluster_nodes or []
        self._current_node = current_node
        self.setWindowTitle(tr("Migrate VM"))
        self.setMinimumWidth(400)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        # Д8/DELIGHT-6: ONE QFormLayout for the whole dialog — the info
        # block and the target block shared a label column, killing the
        # two competing vertical rhythms.
        from .widgets.form_pattern import add_section
        form = QFormLayout()
        form.setSpacing(8)
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        layout.addLayout(form)

        vm_name = self._vm_info.get("name", "")
        vmid = self._vm_info.get("vmid", "")
        vm_type = self._vm_info.get("type", "qemu")
        node = self._vm_info.get("node", self._current_node)

        add_section(form, "VM info")
        form.addRow(tr("Name:"), QLabel(vm_name))
        form.addRow("VMID:", QLabel(str(vmid)))
        type_label = "QEMU" if vm_type == "qemu" else "LXC"
        form.addRow(tr("Type:"), QLabel(type_label))
        form.addRow(tr("Source node:"), QLabel(node))

        add_section(form, "Migration target")
        self.target_combo = QComboBox()
        for n in self._cluster_nodes:
            n_name = n.node or ""
            n_status = n.status_value or ""
            if n_name and n_name != self._current_node:
                label = n_name
                if n_status == "online":
                    label += f"  ({tr('online')})"
                elif n_status:
                    label += f"  ({n_status})"
                self.target_combo.addItem(label, n_name)
        form.addRow(tr("Target node:"), self.target_combo)

        self.with_local_disks_cb = QCheckBox(tr("Migrate local disks"))
        self.with_local_disks_cb.setChecked(True)
        form.addRow("", self.with_local_disks_cb)

        if vm_type == "lxc" and self._vm_info.get("running"):
            # restart migration semantics (PVE 7/8/9): the CT is stopped
            # on the source and rebooted on the target node
            warn = QLabel(tr("Restart migration: the container will be "
                             "rebooted on the target node"))
            warn.setStyleSheet(f"color: {Color.STATUS_WARN}; font-size: 12px;")
            warn.setWordWrap(True)
            form.addRow("", warn)

        btn_layout = QHBoxLayout()
        self.migrate_btn = QPushButton(tr("Migrate"))
        self.migrate_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(self.migrate_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        if self.target_combo.count() == 0:
            self.migrate_btn.setEnabled(False)

    def get_target(self):
        return self.target_combo.currentData()

    def get_with_local_disks(self):
        return self.with_local_disks_cb.isChecked()
