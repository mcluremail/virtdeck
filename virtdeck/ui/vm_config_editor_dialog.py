from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from .i18n import tr
from .theme import Color


class VmConfigEditorDialog(QDialog):
    """Modal dialog for editing a single VM parameter."""
    def __init__(self, key, label, field_type, current_value, choices=None,
                 choice_labels=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Edit: ") + label)
        self.setMinimumWidth(450)
        self.setMinimumHeight(130)

        self._key = key
        self._field_type = field_type

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"<b>{label}</b>")
        layout.addWidget(header)

        form = QFormLayout()

        if field_type == "bool":
            self._editor = QCheckBox(tr("Enabled"))
            self._editor.setChecked(current_value in (1, "1", True))
            form.addRow(tr("Value:"), self._editor)

        elif field_type == "int":
            self._editor = QSpinBox()
            # PVE int params (e.g. memory in MiB on large hosts) exceed the
            # old 0..999999 range and would be silently clamped on save.
            self._editor.setRange(0, 2147483647)
            try:
                self._editor.setValue(int(current_value) if current_value is not None else 0)
            except (ValueError, TypeError):
                self._editor.setValue(0)
            suffix = tr(" MB") if key == "memory" else ""
            if suffix:
                self._editor.setSuffix(suffix)
            form.addRow(tr("Value:"), self._editor)

        elif field_type == "choice":
            self._editor = QComboBox()
            selected_data = None
            for c in (choices or []):
                human = (choice_labels or {}).get(c, str(c))
                self._editor.addItem(human, c)
                if current_value is not None and str(c) == str(current_value):
                    selected_data = c
            if selected_data is not None:
                idx = self._editor.findData(selected_data)
                if idx >= 0:
                    self._editor.setCurrentIndex(idx)
            else:
                if current_value is not None:
                    self._editor.addItem(str(current_value), current_value)
                    self._editor.setCurrentIndex(self._editor.count() - 1)
            form.addRow(tr("Value:"), self._editor)

        elif field_type == "string":
            self._editor = QLineEdit(str(current_value) if current_value is not None else "")
            form.addRow(tr("Value:"), self._editor)
            if key.rstrip("0123456789") in ("net", "ide", "sata", "scsi", "virtio"):
                if key.rstrip("0123456789") not in ("ide",) or key != "ide2":
                    hint = QLabel(tr("Format: model=MAC,bridge=vmbr0,tag=10"))
                    hint.setStyleSheet(f"color: {Color.TEXT_SEC}; font-size: 11px;")
                    form.addRow("", hint)
            elif key.rstrip("0123456789") == "efidisk":
                hint = QLabel(tr("Format: storage:size,format=qcow2"))
                hint.setStyleSheet(f"color: {Color.TEXT_SEC}; font-size: 11px;")
                form.addRow("", hint)

        elif field_type == "readonly":
            self._editor = QLabel(str(current_value) if current_value is not None else "")
            self._editor.setTextInteractionFlags(Qt.TextSelectableByMouse)
            form.addRow(tr("Read only:"), self._editor)
            warning = QLabel(tr("This parameter cannot be changed via API"))
            warning.setStyleSheet(f"color: {Color.WARNING}; font-size: 11px;")
            form.addRow(warning)

        else:
            self._editor = QLineEdit(str(current_value) if current_value is not None else "")
            form.addRow(tr("Value:"), self._editor)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._ok_btn = QPushButton(tr("Save"))
        self._ok_btn.setObjectName("accentBtn")
        self._ok_btn.setMinimumWidth(120)
        self._ok_btn.clicked.connect(self._on_ok)
        btn_layout.addWidget(self._ok_btn)

        self._cancel_btn = QPushButton(tr("Cancel"))
        self._cancel_btn.setMinimumWidth(120)
        self._cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._cancel_btn)

        layout.addLayout(btn_layout)

        if field_type == "bool":
            self._ok_btn.setFocus()
        else:
            self._editor.setFocus()

    def _on_ok(self):
        val = self.get_raw_value()
        if val == "" and self._field_type in ("string", "int"):
            msg = QMessageBox(QMessageBox.Question, tr("Empty value"),
                              tr("Are you sure you want to set an empty value?"),
                              parent=self)
            yes = msg.addButton(tr("Yes"), QMessageBox.YesRole)
            msg.addButton(tr("No"), QMessageBox.NoRole)
            msg.setDefaultButton(yes)
            msg.exec()
            if msg.clickedButton() != yes:
                return
        self.accept()

    def get_raw_value(self):
        ft = self._field_type
        if ft == "bool":
            return (self._key, 1 if self._editor.isChecked() else 0)
        elif ft == "int":
            return (self._key, self._editor.value())
        elif ft == "choice":
            return (self._key, self._editor.currentData())
        elif ft == "string":
            return (self._key, self._editor.text().strip())
        elif ft == "readonly":
            return (self._key, None)
        return (self._key, self._editor.text().strip())
