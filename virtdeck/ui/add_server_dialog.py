from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..backend import TokenCreationWorker
from ..pbs.workers import PbsApiWorker
from .i18n import tr
from .theme import Color


def _section_title(text):
    lbl = QLabel(text)
    lbl.setObjectName("sectionTitle")
    return lbl


def _section_sep():
    sep = QFrame()
    sep.setObjectName("sectionSep")
    sep.setFrameShape(QFrame.HLine)
    sep.setFixedHeight(1)
    return sep


class AddServerDialog(QDialog):

    def __init__(self, parent=None, context=""):
        super().__init__(parent)
        self._context = context
        title_suffix = {"cluster": tr(" to cluster"), "standalone": tr(" as standalone host")}.get(context, "")
        self.setWindowTitle(tr("Add Server") + title_suffix)
        # height by content, but no higher than a soft minimum: on screens
        # with 660px scaling the minimum was not enough, the layout shrank
        # below layout-minimum and widgets overlapped; body is in a scroll
        # area now
        self.setMinimumSize(520, 480)
        self._token_data = None
        self._cluster_info = None
        self._active_workers = set()
        self._build_ui()
        self._apply_context()
        self._on_type_changed()

    def closeEvent(self, event):
        for w in list(self._active_workers):
            try:
                w.signals.token_ready.disconnect()
                w.signals.token_error.disconnect()
            except (RuntimeError, TypeError):
                pass
        self._active_workers.clear()
        super().closeEvent(event)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # body in a scroll area: three sections do not fit in short windows
        # and locales with long labels (2026-10-08 audit, user report)
        body = QWidget(self)
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(16)

        body_lay.addWidget(_section_title(tr("Connection")))

        conn_grid = QGridLayout()
        conn_grid.setHorizontalSpacing(12)
        conn_grid.setVerticalSpacing(10)

        type_lbl = QLabel(tr("Type:"))
        type_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        conn_grid.addWidget(type_lbl, 0, 0)
        self.type_combo = QComboBox()
        self.type_combo.addItem("Proxmox VE", "pve")
        self.type_combo.addItem("Proxmox Backup Server", "pbs")
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        conn_grid.addWidget(self.type_combo, 0, 1)

        host_lbl = QLabel(tr("Host:"))
        host_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        conn_grid.addWidget(host_lbl, 1, 0)
        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("pve01.example.com")
        self.host_input.setValidator(QRegularExpressionValidator(
            r"^[A-Za-z0-9._:\-]{1,255}$"
        ))
        conn_grid.addWidget(self.host_input, 1, 1)

        port_lbl = QLabel(tr("Port:"))
        port_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        conn_grid.addWidget(port_lbl, 2, 0)
        self.port_input = QLineEdit("8006")
        self.port_input.setValidator(QRegularExpressionValidator(r"\d{1,5}"))
        conn_grid.addWidget(self.port_input, 2, 1)

        user_lbl = QLabel(tr("User:"))
        user_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        conn_grid.addWidget(user_lbl, 3, 0)
        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("username@realm (root@pam, user@ipa...)")
        conn_grid.addWidget(self.user_input, 3, 1)

        pwd_lbl = QLabel(tr("Password:"))
        pwd_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        conn_grid.addWidget(pwd_lbl, 4, 0)
        self.pwd_input = QLineEdit()
        self.pwd_input.setEchoMode(QLineEdit.Password)
        self.pwd_input.setPlaceholderText("••••••••")
        conn_grid.addWidget(self.pwd_input, 4, 1)

        info_label = QLabel(tr("An API token will be created for the specified user"))
        info_label.setStyleSheet(f"color: {Color.TEXT_SEC}; font-size: 12px;")
        conn_grid.addWidget(info_label, 5, 0, 1, 2)

        self.trust_ssl_cb = QCheckBox(tr("Trust SSL certificate"))
        self.trust_ssl_cb.setChecked(False)
        self.trust_ssl_cb.setToolTip(tr("Accept self-signed certificates. Check only for internal PVE hosts with self-signed certs."))
        conn_grid.addWidget(self.trust_ssl_cb, 6, 0, 1, 2)

        proxy_lbl = QLabel(tr("Proxy:"))
        proxy_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        conn_grid.addWidget(proxy_lbl, 7, 0)
        self.proxy_input = QLineEdit()
        self.proxy_input.setPlaceholderText(tr("http://host:port — empty uses system proxy settings"))
        conn_grid.addWidget(self.proxy_input, 7, 1)

        self.auth_btn = QPushButton(tr("Get token"))
        conn_grid.addWidget(self.auth_btn, 8, 0, 1, 2)
        self.auth_btn.clicked.connect(self._on_auth)

        conn_grid.setColumnStretch(1, 1)
        body_lay.addLayout(conn_grid)
        body_lay.addWidget(_section_sep())

        token_title = _section_title(tr("Token"))
        body_lay.addWidget(token_title)
        self._token_title = token_title

        token_grid = QGridLayout()
        token_grid.setHorizontalSpacing(12)
        token_grid.setVerticalSpacing(10)

        tn_lbl = QLabel(tr("Token name:"))
        tn_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        token_grid.addWidget(tn_lbl, 0, 0)
        self.token_name_label = QLabel("—")
        self.token_name_label.setStyleSheet("font-family: monospace;")
        token_grid.addWidget(self.token_name_label, 0, 1)

        tv_lbl = QLabel(tr("Value:"))
        tv_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        token_grid.addWidget(tv_lbl, 1, 0)
        self._token_value_real = ""
        self.token_value_label = QLabel("—")
        self.token_value_label.setStyleSheet(f"font-family: monospace; color: {Color.STATUS_OK};")
        token_grid.addWidget(self.token_value_label, 1, 1)

        self._token_show_btn = QPushButton(tr("Show"))
        self._token_show_btn.setCheckable(True)
        self._token_show_btn.clicked.connect(self._toggle_token_visibility)
        self._token_show_btn.setVisible(False)
        token_grid.addWidget(self._token_show_btn, 1, 2)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {Color.TEXT_SEC};")
        token_grid.addWidget(self.status_label, 2, 0, 1, 2)

        token_grid.setColumnStretch(1, 1)
        body_lay.addLayout(token_grid)
        self._token_grid = token_grid
        body_lay.addWidget(_section_sep())

        body_lay.addWidget(_section_title(tr("Node settings")))

        node_grid = QGridLayout()
        node_grid.setHorizontalSpacing(12)
        node_grid.setVerticalSpacing(10)

        name_lbl = QLabel(tr("Name:"))
        name_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        node_grid.addWidget(name_lbl, 0, 0)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(tr("auto (first part of hostname)"))
        node_grid.addWidget(self.name_input, 0, 1)

        cl_lbl = QLabel(tr("Cluster:"))
        cl_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        node_grid.addWidget(cl_lbl, 1, 0)
        self.cluster_input = QLineEdit()
        self.cluster_input.setPlaceholderText(tr("auto (detected from server)"))
        node_grid.addWidget(self.cluster_input, 1, 1)

        node_grid.setColumnStretch(1, 1)
        body_lay.addLayout(node_grid)
        body_lay.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)

        # PVE-only widgets hidden in PBS mode (token flow + cluster row)
        self._pve_only_labels = [info_label, tn_lbl, tv_lbl, cl_lbl]
        self._pve_only_widgets = [self.token_name_label, self.token_value_label,
                                  self._token_show_btn]

        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton(tr("Add"))
        self.add_btn.setObjectName("accentBtn")
        self.add_btn.setEnabled(False)
        self.add_btn.clicked.connect(self._on_add)
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _apply_context(self):
        ctx = self._context
        if ctx == "cluster":
            self.cluster_input.setPlaceholderText(tr("cluster name (required for clusters)"))
        elif ctx == "standalone":
            self.cluster_input.setPlaceholderText(tr("leave empty — standalone host"))

    # ── PBS mode ─────────────────────────────────────────────────

    def _is_pbs(self):
        return self.type_combo.currentData() == "pbs"

    def _on_type_changed(self):
        pbs = self._is_pbs()
        # Port is always visible: default 8006 (PVE) <-> 8007 (PBS). A custom
        # port (not one of the defaults) is not overwritten on type switch.
        current = self.port_input.text().strip()
        if current in ("", "8006", "8007"):
            self.port_input.setText("8007" if pbs else "8006")
        # PVE-only widgets: token flow + cluster assignment
        self._token_title.setVisible(not pbs)
        for w in (self.auth_btn, *self._pve_only_labels, *self._pve_only_widgets):
            w.setVisible(not pbs)
        self.user_input.setPlaceholderText(
            "user@realm (root@pam) or user@pbs!tokenid" if pbs
            else "username@realm (root@pam, user@ipa...)")
        # PVE: Add is enabled only after a token has been created; PBS: always
        self.add_btn.setEnabled(pbs or self._token_data is not None)
        self._set_status("")

    def _on_add(self):
        if not self._is_pbs():
            self.accept()
            return
        host = self.host_input.text().strip()
        password = self.pwd_input.text()
        if not host or not password:
            self._set_status(tr("Enter host and password"), Color.STATUS_ERR)
            return
        self.add_btn.setEnabled(False)
        self._set_status(tr("Checking connection..."), Color.TEXT_SEC)
        cfg = self.get_config()
        self._validate_worker = PbsApiWorker(cfg, "datastores", tag="validate")
        self._validate_worker.signals.done.connect(self._on_validate_done)
        self._validate_worker.signals.failed.connect(self._on_validate_failed)
        QThreadPool.globalInstance().start(self._validate_worker)

    def _on_validate_done(self, tag, _result):
        if tag != "validate" or not self.isVisible():
            return
        self._set_status(tr("Connected"), Color.STATUS_OK)
        self.accept()

    def _on_validate_failed(self, tag, error):
        if tag != "validate" or not self.isVisible():
            return
        self._set_status(error, Color.STATUS_ERR)
        self.add_btn.setEnabled(True)

    def _on_auth(self):
        host = self.host_input.text().strip()
        user = self.user_input.text().strip()
        password = self.pwd_input.text()

        if not host:
            self._set_status(tr("Enter host"), Color.STATUS_ERR)
            return
        if not user:
            self._set_status(tr("Enter user"), Color.STATUS_ERR)
            return
        if not password:
            self._set_status(tr("Enter password"), Color.STATUS_ERR)
            return

        self.auth_btn.setEnabled(False)
        self.auth_btn.setText(tr("Connecting..."))
        self._set_status(tr("Connecting and creating token..."), Color.TEXT_SEC)

        worker = TokenCreationWorker(host, user, password,
                                     trust_ssl=self.trust_ssl_cb.isChecked(),
                                     proxy=self.proxy_input.text().strip() or None)
        self._active_workers.add(worker)
        worker.signals.token_ready.connect(self._on_token_ready)
        worker.signals.token_error.connect(self._on_token_error)
        def _cleanup(w=worker):
            self._active_workers.discard(w)
        worker.signals.finished.connect(_cleanup)
        QThreadPool.globalInstance().start(worker)

    def _on_token_ready(self, result):
        self._token_data = result
        self._cluster_info = result.get("cluster")
        self.token_name_label.setText(result["token_name"])
        self._token_value_real = result["token_value"]
        self.token_value_label.setText("•" * 8)
        self._token_show_btn.setVisible(True)
        self._token_show_btn.setChecked(False)
        status = tr("Token created")
        cluster = self._cluster_info or {}
        if cluster.get("nodes", 0) > 1:
            name = cluster.get("name") or self.host_input.text().strip()
            status += " · " + tr("Cluster detected: {name} ({count} nodes)").format(
                name=name, count=cluster["nodes"])
            if not self.cluster_input.text().strip():
                self.cluster_input.setText(name)
        self._set_status(status, Color.STATUS_OK)
        self.auth_btn.setEnabled(True)
        self.auth_btn.setText(tr("Update token"))
        self.add_btn.setEnabled(True)
        self.pwd_input.clear()

        if not self.name_input.text().strip():
            self.name_input.setText(self.host_input.text().strip())

    def _toggle_token_visibility(self):
        if self._token_show_btn.isChecked():
            self.token_value_label.setText(self._token_value_real)
            self._token_show_btn.setText(tr("Hide"))
        else:
            self.token_value_label.setText("•" * 8)
            self._token_show_btn.setText(tr("Show"))

    def _on_token_error(self, error):
        self._set_status(error, Color.STATUS_ERR)
        self.auth_btn.setEnabled(True)
        self.auth_btn.setText(tr("Get token"))
        self._token_data = None
        self.add_btn.setEnabled(False)

    def _set_status(self, text, color=Color.TEXT_SEC):
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color};")

    def get_config(self):
        host = self.host_input.text().strip()
        name = self.name_input.text().strip() or host
        cluster_text = self.cluster_input.text().strip()
        proxy = self.proxy_input.text().strip()

        if self._is_pbs():
            cfg = {
                "name": name,
                "type": "pbs",
                "host": host,
                "port": int(self.port_input.text().strip() or "8007"),
                "user": self.user_input.text().strip() or "root@pam",
                "token_name": "",
                "token_value": self.pwd_input.text(),
                "trust_ssl": self.trust_ssl_cb.isChecked(),
            }
            if proxy:
                cfg["proxy"] = proxy
            return cfg

        cfg = {
            "name": name,
            "host": host,
            "user": self._token_data["user"],
            "token_name": self._token_data["token_name"],
            "token_value": self._token_data["token_value"],
            "trust_ssl": self.trust_ssl_cb.isChecked(),
        }
        if proxy:
            cfg["proxy"] = proxy

        cluster = self._cluster_info or {}
        if cluster.get("nodes", 0) > 1:
            # Cluster detected automatically via /cluster/status.
            cfg["cluster_rep"] = True
            cfg["cluster"] = cluster_text or cluster.get("name") or name
        else:
            cfg["cluster"] = cluster_text if cluster_text else False

        return cfg
