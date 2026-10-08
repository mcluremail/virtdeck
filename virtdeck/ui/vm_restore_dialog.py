from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from .i18n import tr
from .theme import Color


class VmRestoreDialog(QDialog):
    """Dialog for restoring a VM from a backup archive."""

    def __init__(self, parent=None, volid=None, vm_type="qemu",
                 storages=None, next_vmid=None):
        super().__init__(parent)
        self._volid = volid or ""
        self._vm_type = vm_type
        self._storages = storages or []
        self._next_vmid = next_vmid
        self.setWindowTitle(tr("Restore VM"))
        self.setMinimumWidth(450)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"<b>{tr('Restore from backup')}</b>")
        layout.addWidget(header)

        vol_label = QLabel(f"{tr('Archive:')} {self._volid}")
        vol_label.setStyleSheet(f"color: {Color.TEXT_SEC}; font-size: 11px;")
        vol_label.setWordWrap(True)
        layout.addWidget(vol_label)

        form = QFormLayout()
        form.setSpacing(8)

        self._vmid_spin = QSpinBox()
        self._vmid_spin.setRange(100, 999999999)
        if self._next_vmid:
            self._vmid_spin.setValue(self._next_vmid)
        else:
            self._vmid_spin.setValue(100)
        form.addRow(tr("New VMID:"), self._vmid_spin)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText(tr("Optional"))
        form.addRow(tr("Name:"), self._name_edit)

        self._storage_combo = QComboBox()
        image_storages = [
            s for s in self._storages
            if "images" in s.content_list
        ]
        self._storage_combo.addItem(tr("Default"), "")
        for s in image_storages:
            name = s.storage or ""
            if name:
                self._storage_combo.addItem(name, name)
        form.addRow(tr("Target storage:"), self._storage_combo)

        self._force_check = QCheckBox(tr("Force overwrite"))
        self._force_check.setToolTip(
            tr("Overwrite if VMID already exists")
        )
        form.addRow("", self._force_check)

        self._unique_check = QCheckBox(tr("Unique MAC addresses"))
        self._unique_check.setChecked(True)
        form.addRow("", self._unique_check)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton(tr("Restore"))
        ok_btn.setObjectName("accentBtn")
        ok_btn.setMinimumWidth(120)
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.setMinimumWidth(120)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def get_params(self):
        return {
            "vmid": self._vmid_spin.value(),
            "storage": self._storage_combo.currentData() or "",
            "name": self._name_edit.text().strip(),
            "force": self._force_check.isChecked(),
            "unique": self._unique_check.isChecked(),
        }
