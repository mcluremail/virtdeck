from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from .i18n import tr


class GroupDialog(QDialog):
    """Dialog for creating or editing a user group."""

    def __init__(self, parent=None, group=None):
        super().__init__(parent)
        self._group = group or {}
        self._is_edit = bool(group)
        self.setWindowTitle(tr("Edit group") if self._is_edit else tr("Add group"))
        self.setMinimumWidth(380)
        self._build_ui()
        if self._is_edit:
            self._fill_from_group()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        form = QFormLayout()
        form.setSpacing(8)

        if self._is_edit:
            self._groupid_edit = QLineEdit(self._group.get("groupid", ""))
            self._groupid_edit.setReadOnly(True)
        else:
            self._groupid_edit = QLineEdit()
            self._groupid_edit.setPlaceholderText("e.g. admins")
            self._groupid_edit.setValidator(QRegularExpressionValidator(
                r"^[A-Za-z0-9_\-]{1,64}$"
            ))
        form.addRow(tr("Group ID:"), self._groupid_edit)

        self._comment_edit = QLineEdit()
        self._comment_edit.setMaxLength(255)
        form.addRow(tr("Comment:"), self._comment_edit)

        if self._is_edit:
            members = self._group.get("users", "") or self._group.get("members", "")
            if isinstance(members, list):
                members = ", ".join(members)
            members_label = QLabel(members or tr("No members"))
            members_label.setWordWrap(True)
            form.addRow(tr("Members:"), members_label)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
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

    def _fill_from_group(self):
        self._comment_edit.setText(self._group.get("comment", "") or "")

    def get_params(self):
        params = {}
        if not self._is_edit:
            gid = self._groupid_edit.text().strip()
            if not gid:
                return {}
            params["groupid"] = gid
        comment = self._comment_edit.text().strip()
        if comment:
            params["comment"] = comment
        return params
