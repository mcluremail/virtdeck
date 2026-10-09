from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
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

        info_group = QGroupBox(tr("VM info"))
        info_grid = QGridLayout(info_group)
        vm_name = self._vm_info.get("name", "")
        vmid = self._vm_info.get("vmid", "")
        vm_type = self._vm_info.get("type", "qemu")
        node = self._vm_info.get("node", self._current_node)

        info_grid.addWidget(QLabel(tr("Name:")), 0, 0)
        info_grid.addWidget(QLabel(vm_name), 0, 1)
        info_grid.addWidget(QLabel("VMID:"), 1, 0)
        info_grid.addWidget(QLabel(str(vmid)), 1, 1)
        info_grid.addWidget(QLabel(tr("Type:")), 2, 0)
        type_label = "QEMU" if vm_type == "qemu" else "LXC"
        info_grid.addWidget(QLabel(type_label), 2, 1)
        info_grid.addWidget(QLabel(tr("Source node:")), 3, 0)
        info_grid.addWidget(QLabel(node), 3, 1)
        layout.addWidget(info_group)

        target_group = QGroupBox(tr("Migration target"))
        target_grid = QGridLayout(target_group)

        target_grid.addWidget(QLabel(tr("Target node:")), 0, 0)
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
        target_grid.addWidget(self.target_combo, 0, 1)

        self.with_local_disks_cb = QCheckBox(tr("Migrate local disks"))
        self.with_local_disks_cb.setChecked(True)
        target_grid.addWidget(self.with_local_disks_cb, 1, 0, 1, 2)

        if vm_type == "lxc" and self._vm_info.get("running"):
            # restart migration semantics (PVE 7/8/9): the CT is stopped
            # on the source and rebooted on the target node
            warn = QLabel(tr("Restart migration: the container will be "
                             "rebooted on the target node"))
            warn.setStyleSheet(f"color: {Color.STATUS_WARN}; font-size: 11px;")
            warn.setWordWrap(True)
            target_grid.addWidget(warn, 2, 0, 1, 2)

        layout.addWidget(target_group)

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
