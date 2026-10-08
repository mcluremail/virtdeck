from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from .i18n import tr
from .theme import Color


class AclDialog(QDialog):
    """Dialog for adding ACL permissions."""

    def __init__(self, parent=None, roles=None, users=None, groups=None, tokens=None):
        super().__init__(parent)
        self._roles = roles or []
        self._users = users or []
        self._groups = groups or []
        self._tokens = tokens or []
        self.setWindowTitle(tr("Add permissions"))
        self.setMinimumWidth(460)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        form = QFormLayout()
        form.setSpacing(8)

        self._path_edit = QLineEdit("/")
        self._path_edit.setValidator(QRegularExpressionValidator(
            r"^/[A-Za-z0-9/_.\-]*$"
        ))
        form.addRow(tr("Path:"), self._path_edit)

        path_hint = QLabel(tr("e.g. /, /vms, /storage/local, /nodes/pve01"))
        path_hint.setStyleSheet(f"color: {Color.TEXT_SEC}; font-size: 11px;")
        form.addRow("", path_hint)

        self._type_combo = QComboBox()
        self._type_combo.addItem(tr("User"), "user")
        self._type_combo.addItem(tr("Group"), "group")
        self._type_combo.addItem(tr("Token"), "token")
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        form.addRow(tr("Type:"), self._type_combo)

        self._principal_combo = QComboBox()
        form.addRow(tr("Principal:"), self._principal_combo)
        self._on_type_changed()

        self._role_combo = QComboBox()
        for r in self._roles:
            rid = r.get("roleid", "")
            if rid:
                self._role_combo.addItem(rid, rid)
        form.addRow(tr("Role:"), self._role_combo)

        self._propagate_check = QCheckBox(tr("Propagate"))
        self._propagate_check.setChecked(True)
        form.addRow("", self._propagate_check)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._ok_btn = QPushButton(tr("Add"))
        self._ok_btn.setObjectName("accentBtn")
        self._ok_btn.setMinimumWidth(120)
        self._ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.setMinimumWidth(120)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _on_type_changed(self):
        ptype = self._type_combo.currentData()
        self._principal_combo.clear()
        if ptype == "user":
            for u in self._users:
                uid = u.get("userid", "")
                if uid:
                    self._principal_combo.addItem(uid, uid)
        elif ptype == "group":
            for g in self._groups:
                gid = g.get("groupid", "")
                if gid:
                    self._principal_combo.addItem(gid, gid)
        elif ptype == "token":
            for t in self._tokens:
                tid = t.get("full-tokenid", "") or t.get("tokenid", "")
                if tid:
                    self._principal_combo.addItem(tid, tid)

    def get_params(self):
        params = {}
        path = self._path_edit.text().strip()
        if not path:
            return {}
        params["path"] = path
        params["roles"] = self._role_combo.currentData() or ""

        ptype = self._type_combo.currentData()
        principal = self._principal_combo.currentData() or ""
        if ptype == "user":
            params["users"] = principal
        elif ptype == "group":
            params["groups"] = principal
        elif ptype == "token":
            params["tokens"] = principal

        params["propagate"] = 1 if self._propagate_check.isChecked() else 0
        return params
