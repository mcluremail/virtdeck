from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from .i18n import tr
from .theme import Color


class StorageMoveDialog(QDialog):
    """Move or copy a volume to another storage."""

    def __init__(self, volid, storages, is_disk, parent=None, mode="move"):
        super().__init__(parent)
        self._mode = mode if mode in ("move", "copy") else "move"
        title = tr("Copy volume") if self._mode == "copy" else tr("Move volume")
        self.setWindowTitle(title)
        self.setMinimumWidth(450)
        self._volid = volid
        self._is_disk = is_disk

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"<b>{title}</b>")
        layout.addWidget(header)

        vol_label = QLabel(f"{tr('Volume:')} {volid}")
        vol_label.setStyleSheet(f"color: {Color.TEXT_SEC}; font-size: 12px;")
        vol_label.setWordWrap(True)
        layout.addWidget(vol_label)

        form = QFormLayout()
        form.setSpacing(8)

        self._target_combo = QComboBox()
        self._target_combo.setEditable(True)
        for s in storages:
            name = s.storage or ""
            if name:
                self._target_combo.addItem(name, name)
        form.addRow(tr("Target storage:"), self._target_combo)

        self._vmid_spin = QSpinBox()
        self._vmid_spin.setRange(0, 999999999)
        self._vmid_spin.setSpecialValueText(tr("Not set"))
        if is_disk:
            form.addRow(tr("Target VM:"), self._vmid_spin)
        else:
            self._vmid_spin.setVisible(False)

        self._delete_check = QCheckBox(tr("Delete source after move"))
        if self._mode == "copy":
            self._delete_check.setVisible(False)
        form.addRow("", self._delete_check)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton(title)
        ok_btn.setObjectName("accentBtn")
        ok_btn.setFixedWidth(120)
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.setFixedWidth(120)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def get_params(self):
        return {
            "target_storage": self._target_combo.currentText().strip(),
            "target_vmid": self._vmid_spin.value() if self._is_disk else 0,
            "delete_source": (self._mode == "move") and self._delete_check.isChecked(),
        }


def confirm_file_delete(volid, parent=None):
    """Confirm deletion of a storage file."""
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Question)
    msg.setWindowTitle(tr("Remove file"))
    msg.setText(tr("Remove file?"))
    msg.setInformativeText(
        tr("This will permanently delete {volid} from storage.").format(volid=volid)
    )
    msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    msg.setDefaultButton(QMessageBox.No)
    return msg.exec() == QMessageBox.Yes
