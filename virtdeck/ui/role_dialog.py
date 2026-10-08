from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QCheckBox,
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
)

from .i18n import tr
from .theme import Color

_PVE_PRIVILEGES = [
    "Datastore.Allocate", "Datastore.AllocateSpace", "Datastore.AllocateTemplate",
    "Datastore.Audit", "Group.Allocate", "Mapping.Audit", "Mapping.Modify",
    "Mapping.Use", "Permissions.Modify", "Pool.Allocate", "Pool.Audit",
    "Realm.Allocate", "Realm.AllocateUser", "SDN.Allocate", "SDN.Audit",
    "SDN.Use", "Sys.AccessNetwork", "Sys.Audit", "Sys.Console", "Sys.Modify",
    "Sys.Incoming", "Sys.PowerMgmt", "Sys.Syslog", "User.Modify",
    "VM.Allocate", "VM.Audit", "VM.Backup", "VM.Clone", "VM.Config.CDROM",
    "VM.Config.CPU", "VM.Config.Cloudinit", "VM.Config.Disk",
    "VM.Config.HWType", "VM.Config.Memory", "VM.Config.Network",
    "VM.Config.Options", "VM.Console", "VM.GuestAgent.Audit",
    "VM.GuestAgent.FileRead", "VM.GuestAgent.FileSystemMgmt",
    "VM.GuestAgent.FileWrite", "VM.GuestAgent.Unrestricted",
    "VM.Migrate", "VM.PowerMgmt", "VM.Replicate", "VM.Snapshot",
    "VM.Snapshot.Rollback",
]


class RoleDialog(QDialog):
    """Dialog for creating or editing a role.

    Built-in roles (special=1) are read-only — checkboxes are disabled.
    """

    def __init__(self, parent=None, role=None, role_privs=None):
        super().__init__(parent)
        self._role = role or {}
        self._role_privs = role_privs or {}
        self._is_edit = bool(role)
        self._is_special = bool(self._role.get("special"))
        title = tr("View role") if self._is_special else (
            tr("Edit role") if self._is_edit else tr("Add role")
        )
        self.setWindowTitle(title)
        self.setMinimumWidth(560)
        self._build_ui()
        if self._is_edit:
            self._fill_from_role()
        self._adjust_size()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        form = QFormLayout()
        form.setSpacing(8)

        if self._is_edit:
            self._roleid_edit = QLineEdit(self._role.get("roleid", ""))
            self._roleid_edit.setReadOnly(True)
        else:
            self._roleid_edit = QLineEdit()
            self._roleid_edit.setPlaceholderText("e.g. MyCustomRole")
            self._roleid_edit.setValidator(QRegularExpressionValidator(
                r"^[A-Za-z0-9_]{1,64}$"
            ))
        form.addRow(tr("Role ID:"), self._roleid_edit)

        if self._is_special:
            special_label = QLabel(tr("Built-in role (read-only)"))
            special_label.setStyleSheet(f"color: {Color.TEXT_SEC};")
            form.addRow("", special_label)

        layout.addLayout(form)

        priv_group = QGroupBox(tr("Privileges"))
        priv_layout = QGridLayout(priv_group)
        priv_layout.setSpacing(6)
        self._priv_checks = {}
        cols = 2
        for i, priv in enumerate(_PVE_PRIVILEGES):
            cb = QCheckBox(priv)
            if self._is_special:
                cb.setEnabled(False)
            self._priv_checks[priv] = cb
            priv_layout.addWidget(cb, i // cols, i % cols)

        priv_scroll = QScrollArea()
        priv_scroll.setWidgetResizable(True)
        priv_scroll.setWidget(priv_group)
        priv_scroll.setFrameShape(QScrollArea.NoFrame)
        priv_scroll.setMinimumHeight(200)
        layout.addWidget(priv_scroll)

        if not self._is_special:
            sel_layout = QHBoxLayout()
            select_all_btn = QPushButton(tr("Select all"))
            select_all_btn.clicked.connect(self._select_all)
            deselect_all_btn = QPushButton(tr("Deselect all"))
            deselect_all_btn.clicked.connect(self._deselect_all)
            sel_layout.addWidget(select_all_btn)
            sel_layout.addWidget(deselect_all_btn)
            sel_layout.addStretch()
            layout.addLayout(sel_layout)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        if self._is_special:
            close_btn = QPushButton(tr("Close"))
            close_btn.setObjectName("accentBtn")
            close_btn.setMinimumWidth(120)
            close_btn.clicked.connect(self.accept)
            btn_layout.addWidget(close_btn)
        else:
            self._ok_btn = QPushButton(tr("Save"))
            self._ok_btn.setObjectName("accentBtn")
            self._ok_btn.setMinimumWidth(120)
            self._ok_btn.clicked.connect(self.accept)
            cancel_btn = QPushButton(tr("Cancel"))
            cancel_btn.setMinimumWidth(120)
            cancel_btn.clicked.connect(self.reject)
            btn_layout.addWidget(self._ok_btn)
            btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _adjust_size(self):
        w = max(self.minimumWidth(), self.sizeHint().width())
        h = self.layout().sizeHint().height()
        screen = self.screen()
        if screen:
            avail = screen.availableGeometry()
            max_h = int(avail.height() * 0.85)
            h = min(h, max_h)
        self.resize(w, h)

    def _select_all(self):
        for cb in self._priv_checks.values():
            cb.setChecked(True)

    def _deselect_all(self):
        for cb in self._priv_checks.values():
            cb.setChecked(False)

    def _fill_from_role(self):
        if self._role_privs:
            for priv, enabled in self._role_privs.items():
                cb = self._priv_checks.get(priv)
                if cb:
                    cb.setChecked(bool(enabled))
        else:
            privs = self._role.get("privs") or []
            if isinstance(privs, str):
                privs = privs.split(",")
            for priv in privs:
                priv = priv.strip() if isinstance(priv, str) else priv
                if priv:
                    cb = self._priv_checks.get(priv)
                    if cb:
                        cb.setChecked(True)

    def get_params(self):
        if self._is_special:
            return {}
        params = {}
        if not self._is_edit:
            rid = self._roleid_edit.text().strip()
            if not rid:
                return {}
            params["roleid"] = rid
        privs = [p for p, cb in self._priv_checks.items() if cb.isChecked()]
        params["privs"] = ",".join(privs)
        return params
