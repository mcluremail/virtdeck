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


class VzdumpDialog(QDialog):
    """Dialog for running vzdump (on-demand backup) on a VM."""

    def __init__(self, parent=None, vmid=None, storages=None):
        super().__init__(parent)
        self._vmid = vmid
        self._storages = storages or []
        self.setWindowTitle(tr("Backup now"))
        self.setMinimumWidth(420)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"<b>{tr('Backup VM {vmid}').format(vmid=self._vmid)}</b>")
        layout.addWidget(header)

        form = QFormLayout()
        form.setSpacing(8)

        self._storage_combo = QComboBox()
        backup_storages = [
            s for s in self._storages
            if "backup" in s.content_list
        ]
        if not backup_storages:
            hint = QLabel(tr("No backup storage available"))
            hint.setStyleSheet(f"color: {Color.STATUS_ERR};")
            form.addRow(tr("Backup storage:"), hint)
            self._storage_combo = None
        else:
            for s in backup_storages:
                name = s.storage or ""
                if name:
                    self._storage_combo.addItem(name, name)
            form.addRow(tr("Backup storage:"), self._storage_combo)

        self._mode_combo = QComboBox()
        self._mode_combo.addItem(tr("Snapshot"), "snapshot")
        self._mode_combo.addItem(tr("Suspend"), "suspend")
        self._mode_combo.addItem(tr("Stop"), "stop")
        form.addRow(tr("Backup mode:"), self._mode_combo)

        self._compress_combo = QComboBox()
        self._compress_combo.addItem(tr("None"), "0")
        self._compress_combo.addItem("gzip", "gzip")
        self._compress_combo.addItem("lzo", "lzo")
        self._compress_combo.addItem("zstd", "zstd")
        idx = self._compress_combo.findData("zstd")
        if idx >= 0:
            self._compress_combo.setCurrentIndex(idx)
        form.addRow(tr("Compression:"), self._compress_combo)

        self._notes_edit = QLineEdit()
        self._notes_edit.setPlaceholderText(tr("Optional notes"))
        self._notes_edit.setMaxLength(255)
        form.addRow(tr("Notes:"), self._notes_edit)

        self._remove_check = QCheckBox(tr("Remove old backups"))
        form.addRow("", self._remove_check)

        self._bwlimit_spin = QSpinBox()
        self._bwlimit_spin.setRange(0, 999999)
        self._bwlimit_spin.setSpecialValueText(tr("No limit"))
        self._bwlimit_spin.setValue(0)
        form.addRow(tr("Bandwidth limit (MB/s):"), self._bwlimit_spin)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton(tr("Backup"))
        ok_btn.setObjectName("accentBtn")
        ok_btn.setMinimumWidth(120)
        ok_btn.setEnabled(bool(backup_storages))
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.setMinimumWidth(120)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def get_params(self):
        if self._storage_combo is None:
            return None
        return {
            "storage": self._storage_combo.currentData(),
            "mode": self._mode_combo.currentData(),
            "compress": self._compress_combo.currentData(),
            "notes": self._notes_edit.text().strip(),
            "remove": self._remove_check.isChecked(),
            "bwlimit": self._bwlimit_spin.value(),
        }
