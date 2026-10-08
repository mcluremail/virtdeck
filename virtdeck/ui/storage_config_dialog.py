"""StorageConfigDialog — create/edit a cluster storage definition (B4).

Talks to /storage via StorageConfigSaveWorker in mainwindow.
Type-specific fields are kept minimal: the most common PVE storage
plugins and their key options.
"""

import re

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .i18n import tr

CONTENT_TYPES = ["images", "rootdir", "vztmpl", "iso", "backup", "snippets", "import"]

STORAGE_TYPES = [
    "dir", "nfs", "cifs", "zfspool", "lvm", "lvmthin", "rbd", "btrfs", "pbs",
]

# Plugin -> extra form fields: (param name, label, is_password)
_TYPE_FIELDS = {
    "dir": [("path", "Path", False)],
    "btrfs": [("path", "Path", False)],
    "nfs": [("server", "Server", False), ("export", "Export", False)],
    "cifs": [("server", "Server", False), ("share", "Share", False),
             ("username", "Username", False), ("password", "Password", True)],
    "zfspool": [("pool", "Pool", False)],
    "lvm": [("vgname", "VG name", False)],
    "lvmthin": [("vgname", "VG name", False), ("thinpool", "Thin pool", False)],
    "rbd": [("pool", "Pool", False), ("monhost", "Monitors", False),
            ("username", "Username", False)],
    "pbs": [("server", "Server", False), ("datastore", "Datastore", False),
            ("username", "Username", False), ("password", "Password", True),
            ("fingerprint", "Fingerprint", False)],
}


class StorageConfigDialog(QDialog):
    """Create or edit one /storage definition."""

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        # config=None → create; dict → edit (id/type stay fixed)
        self._config = dict(config or {})
        self._editing = bool(self._config)
        self.setWindowTitle(tr("Edit storage…") if self._editing
                            else tr("Create storage…"))
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"<b>{self.windowTitle()}</b>")
        layout.addWidget(header)

        form = QFormLayout()
        form.setSpacing(8)

        self._id_edit = QLineEdit(self._config.get("storage", ""))
        if self._editing:
            self._id_edit.setEnabled(False)
        form.addRow(tr("Storage ID") + ":", self._id_edit)

        self._type_combo = QComboBox()
        for t in STORAGE_TYPES:
            self._type_combo.addItem(t, t)
        cur_type = self._config.get("type", "dir")
        idx = self._type_combo.findData(cur_type)
        self._type_combo.setCurrentIndex(idx if idx >= 0 else 0)
        if self._editing:
            self._type_combo.setEnabled(False)
        self._type_combo.currentIndexChanged.connect(self._rebuild_type_fields)
        form.addRow(tr("Type") + ":", self._type_combo)

        # Content types (checkable grid)
        content_box = QGroupBox(tr("Content"))
        content_grid = QGridLayout(content_box)
        content_grid.setContentsMargins(8, 4, 8, 4)
        self._content_checks = {}
        enabled = set((self._config.get("content") or "").split(","))
        for i, ct in enumerate(CONTENT_TYPES):
            cb = QCheckBox(ct)
            cb.setChecked(ct in enabled)
            self._content_checks[ct] = cb
            content_grid.addWidget(cb, i // 4, i % 4)
        form.addRow(content_box)

        # Nodes: empty → all nodes
        nodes_val = self._config.get("nodes") or ""
        self._nodes_edit = QLineEdit(nodes_val if isinstance(nodes_val, str) else "")
        self._nodes_edit.setPlaceholderText(tr("empty = all nodes"))
        form.addRow(tr("Nodes") + ":", self._nodes_edit)

        self._enable_check = QCheckBox(tr("Enable"))
        self._enable_check.setChecked(str(self._config.get("enable", "1")) not in ("0", "False"))
        form.addRow("", self._enable_check)

        # Type-specific fields
        self._type_form = QFormLayout()
        self._type_form.setSpacing(8)
        # Common form and type-specific fields go into a scroll area: rbd/ceph
        # forms have so many fields that in short windows and locales with long
        # labels the content does not fit (buttons stay outside, always visible)
        body = QWidget(self)
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(12)
        body_lay.addLayout(form)
        body_lay.addLayout(self._type_form)
        body_lay.addStretch(1)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        self._rebuild_type_fields()

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton(tr("Save"))
        ok_btn.setObjectName("accentBtn")
        ok_btn.setMinimumWidth(120)
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.setMinimumWidth(120)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _rebuild_type_fields(self):
        while self._type_form.count():
            item = self._type_form.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._type_edits = {}
        t = self._type_combo.currentData() or "dir"
        for param, label, is_pwd in _TYPE_FIELDS.get(t, []):
            edit = QLineEdit(self._config.get(param, ""))
            if is_pwd:
                edit.setEchoMode(QLineEdit.Password)
            self._type_edits[param] = edit
            self._type_form.addRow(tr(label) + ":", edit)

    def _validate(self):
        sid = self._id_edit.text().strip()
        if not sid:
            return tr("Storage ID is required")
        if not self._editing:
            if not re.fullmatch(r"[A-Za-z0-9_.\-]+", sid):
                return tr("Storage ID: invalid characters")
        if self._type_combo.currentData() in ("dir", "btrfs") \
                and not self._type_edits.get("path", QLineEdit()).text().strip():
            return tr("Path is required")
        if self._type_combo.currentData() == "nfs" and \
                not (self._type_edits.get("server", QLineEdit()).text().strip()
                     and self._type_edits.get("export", QLineEdit()).text().strip()):
            return tr("Server and Export are required")
        return ""

    def accept(self):
        err = self._validate()
        if err:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, self.windowTitle(), err)
            return
        super().accept()

    def get_params(self):
        """API params dict (without storage id — see get_storage_id)."""
        params = {}
        content = [ct for ct, cb in self._content_checks.items() if cb.isChecked()]
        if content:
            params["content"] = ",".join(content)
        nodes = self._nodes_edit.text().strip()
        if nodes:
            params["nodes"] = nodes
        params["enable"] = 1 if self._enable_check.isChecked() else 0
        for param, edit in self._type_edits.items():
            val = edit.text().strip()
            if val:
                params[param] = val
        return params

    def get_storage_id(self):
        return self._id_edit.text().strip()

    def get_storage_type(self):
        return self._type_combo.currentData() or "dir"
