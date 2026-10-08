"""PbsPanel — right-side panel for PBS servers and datastores (B17 stage 2).

Server view: datastore table (name, usage, used/total, path).
Datastore view: Status (usage + verify), Snapshots (ns filter, forget),
Jobs (sync/verify/prune with "Run now").

All data loads through PbsApiWorker; tags route results back.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThreadPool, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..pbs.workers import PbsApiWorker
from .i18n import tr
from .icons import get_icon
from .theme import Color, enable_column_reorder

VERIFY_COLORS = {
    "ok": Color.STATUS_OK,
    "failed": Color.DANGER,
    "none": Color.TEXT_SEC,
}


def _fmt_size(num) -> str:
    try:
        n = float(num or 0)
    except (TypeError, ValueError):
        return "—"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return f"{n:,.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return "—"


def _usage_color(usage: float) -> str:
    if usage >= 0.9:
        return Color.DANGER
    if usage >= 0.75:
        return Color.WARNING
    return Color.SUCCESS


class PbsPanel(QWidget):
    """PBS server / datastore details (replaces DetailPanel for pbs items)."""

    datastores_loaded = Signal(object, list)  # server_name, list[PbsDatastore]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cfg_by_name: dict[str, dict] = {}
        self._server = ""
        self._store = ""
        self._workers: set = set()
        self._build_ui()
        PbsApiWorker.signals.done.connect(self._on_worker_done)
        PbsApiWorker.signals.failed.connect(self._on_worker_failed)

    # ── UI ───────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        self._title_lbl = QLabel("")
        self._title_lbl.setObjectName("sectionTitle")
        header.addWidget(self._title_lbl)
        header.addStretch()
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(f"color: {Color.TEXT_SEC};")
        header.addWidget(self._status_lbl)
        layout.addLayout(header)

        self._stack = QStackedWidget(self)
        layout.addWidget(self._stack, 1)

        # page 0: server view (datastores table)
        self._ds_table = QTableWidget(0, 5)
        self._ds_table.setHorizontalHeaderLabels(
            [tr("Datastore"), tr("Usage"), tr("Used"), tr("Total"),
             tr("Path")])
        self._ds_table.verticalHeader().setVisible(False)
        self._ds_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._ds_table.setSelectionMode(QTableWidget.SingleSelection)
        self._ds_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._ds_table.itemDoubleClicked.connect(self._on_ds_dblclicked)
        enable_column_reorder(self._ds_table.horizontalHeader())
        self._ds_table.horizontalHeader().setStretchLastSection(True)
        ds_page = QWidget()
        ds_layout = QVBoxLayout(ds_page)
        ds_layout.setContentsMargins(0, 8, 0, 0)
        ds_layout.addWidget(self._ds_table)
        self._stack.addWidget(ds_page)

        # page 1: datastore view (tabs)
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._build_status_tab()
        self._build_snapshots_tab()
        self._build_jobs_tab()
        self._stack.addWidget(self._tabs)

    def _build_status_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(10)

        self._usage_bar = QProgressBar()
        self._usage_bar.setRange(0, 100)
        self._usage_bar.setTextVisible(False)
        self._usage_bar.setFixedHeight(14)
        v.addWidget(self._usage_bar)

        self._usage_lbl = QLabel("")
        self._usage_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self._usage_lbl)

        self._path_lbl = QLabel("")
        self._path_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._path_lbl.setStyleSheet(f"color: {Color.TEXT_SEC};")
        v.addWidget(self._path_lbl)

        btns = QHBoxLayout()
        self._verify_btn = QPushButton(tr("Verify"))
        self._verify_btn.setIcon(get_icon("snapshot"))
        self._verify_btn.clicked.connect(self._on_verify_clicked)
        btns.addWidget(self._verify_btn)
        refresh = QPushButton(tr("Refresh"))
        refresh.setIcon(get_icon("refresh"))
        refresh.clicked.connect(self._load_all)
        btns.addWidget(refresh)
        btns.addStretch()
        v.addLayout(btns)
        v.addStretch()

        self._tabs.addTab(w, tr("Status"))

    def _build_snapshots_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(6)

        top = QHBoxLayout()
        self._ns_lbl = QLabel(tr("Namespace:"))
        top.addWidget(self._ns_lbl)
        self._ns_combo = QComboBox()
        self._ns_combo.setMinimumWidth(140)
        self._ns_combo.currentTextChanged.connect(
            lambda _t: self._load_snapshots())
        top.addWidget(self._ns_combo)
        top.addStretch()
        v.addLayout(top)

        self._snap_table = QTableWidget(0, 5)
        self._snap_table.setHorizontalHeaderLabels(
            [tr("Snapshot"), tr("Owner"), tr("Verify"), tr("Size"),
             tr("Notes")])
        self._snap_table.verticalHeader().setVisible(False)
        self._snap_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._snap_table.setSelectionMode(QTableWidget.SingleSelection)
        self._snap_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._snap_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._snap_table.customContextMenuRequested.connect(
            self._on_snap_menu)
        enable_column_reorder(self._snap_table.horizontalHeader())
        self._snap_table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self._snap_table, 1)
        self._tabs.addTab(w, tr("Snapshots"))

    def _build_jobs_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 8, 0, 0)

        self._jobs_table = QTableWidget(0, 5)
        self._jobs_table.setHorizontalHeaderLabels(
            [tr("Kind"), tr("ID"), tr("Datastore"), tr("Schedule"),
             tr("State")])
        self._jobs_table.verticalHeader().setVisible(False)
        self._jobs_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._jobs_table.setSelectionMode(QTableWidget.SingleSelection)
        self._jobs_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._jobs_table.setContextMenuPolicy(Qt.CustomContextMenu)
        enable_column_reorder(self._jobs_table.horizontalHeader())
        self._jobs_table.horizontalHeader().setStretchLastSection(True)
        self._jobs_table.customContextMenuRequested.connect(self._on_job_menu)
        v.addWidget(self._jobs_table, 1)

        hint = QLabel(tr("Right-click a job to run it now"))
        hint.setStyleSheet(f"color: {Color.TEXT_SEC};")
        v.addWidget(hint)
        self._tabs.addTab(w, tr("Jobs"))

    # ── config / navigation ──────────────────────────────────────

    def update_nodes_cfg(self, nodes_cfg):
        self._cfg_by_name = {
            c.get("name", ""): c for c in nodes_cfg
            if c.get("type") == "pbs" and c.get("name")
        }

    def _cfg(self, server=None):
        return self._cfg_by_name.get(server or self._server)

    def _set_status(self, text, color=Color.TEXT_SEC):
        self._status_lbl.setText(text)
        self._status_lbl.setStyleSheet(f"color: {color};")

    def show_server(self, server_name):
        """Server view: datastores table."""
        if not self._cfg(server_name):
            return
        self._server = server_name
        self._store = ""
        self._title_lbl.setText(f"{server_name} — Proxmox Backup Server")
        self._stack.setCurrentIndex(0)
        self._load_datastores()

    def show_datastore(self, server_name, store):
        """Datastore view: status + snapshots + jobs."""
        if not self._cfg(server_name):
            return
        # Re-showing the same datastore must not yank the user off their tab
        same = (self._server == server_name and self._store == store
                and self._stack.currentIndex() == 1)
        self._server = server_name
        self._store = store
        self._title_lbl.setText(f"{server_name} / {store}")
        self._stack.setCurrentIndex(1)
        if not same:
            self._tabs.setCurrentIndex(0)
        self._ns_lbl.hide()
        self._ns_combo.hide()
        self._ns_combo.blockSignals(True)
        self._ns_combo.clear()
        self._ns_combo.addItem("/", "")
        self._ns_combo.blockSignals(False)
        self._load_all()

    # ── loading ──────────────────────────────────────────────────

    def _start(self, method, *args, tag=None, **kwargs):
        cfg = self._cfg()
        if not cfg:
            return
        worker = PbsApiWorker(cfg, method, *args, tag=tag, **kwargs)
        self._workers.add(worker)
        QThreadPool.globalInstance().start(worker)

    def _load_datastores(self):
        self._start("datastores", tag=("ds", self._server))

    def _load_all(self):
        if not self._store:
            return
        self._start("datastores", tag=("ds", self._server))
        self._load_snapshots()
        self._start("jobs", tag=("jobs", self._server))

    def _load_snapshots(self):
        if not self._store:
            return
        ns = self._ns_combo.currentData() or ""
        self._start("snapshots", self._store, ns=ns,
                    tag=("snap", self._server, self._store, ns))

    def _load_namespaces(self):
        self._start("namespaces", self._store, tag=("ns", self._server,
                                                    self._store))

    # ── worker results ───────────────────────────────────────────

    def _on_worker_done(self, tag, result):
        try:
            kind = tag[0]
            if kind == "ds":
                if tag[1] == self._server:
                    self.datastores_loaded.emit(tag[1], result)
                    if self._stack.currentIndex() == 0:
                        self._fill_ds_table(result)
                    else:
                        ds = next((d for d in result
                                   if d.name == self._store), None)
                        if ds:
                            self._fill_status(ds)
            elif kind == "snap":
                _, server, store, ns = tag
                if server == self._server and store == self._store \
                        and ns == (self._ns_combo.currentData() or ""):
                    self._fill_snapshots(result)
            elif kind == "ns":
                _, server, store = tag
                if server == self._server and store == self._store:
                    self._ns_combo.blockSignals(True)
                    current = self._ns_combo.currentData() or ""
                    self._ns_combo.clear()
                    self._ns_combo.addItem("/", "")
                    for name in result:
                        self._ns_combo.addItem(name, name)
                    idx = self._ns_combo.findData(current)
                    self._ns_combo.setCurrentIndex(max(idx, 0))
                    self._ns_combo.blockSignals(False)
                    # Root-only datastore: the selector is pointless noise
                    visible = bool(result)
                    self._ns_lbl.setVisible(visible)
                    self._ns_combo.setVisible(visible)
            elif kind == "jobs":
                if tag[1] == self._server:
                    self._fill_jobs(result)
            elif kind == "run":
                self._set_status(tr("Job started"), Color.STATUS_OK)
                self._start("jobs", tag=("jobs", self._server))
            elif kind == "forget":
                self._set_status(tr("Snapshot deleted"), Color.STATUS_OK)
                self._load_snapshots()
            elif kind == "verify":
                self._set_status(tr("Verify started"), Color.STATUS_OK)
        except RuntimeError:
            pass

    def _on_worker_failed(self, tag, error):
        try:
            self._set_status(error, Color.STATUS_ERR)
        except RuntimeError:
            pass

    # ── server view ──────────────────────────────────────────────

    def _fill_ds_table(self, stores):
        self._ds_table.setRowCount(0)
        for ds in sorted(stores, key=lambda d: d.name.lower()):
            row = self._ds_table.rowCount()
            self._ds_table.insertRow(row)
            name = QTableWidgetItem(ds.name)
            name.setIcon(get_icon("backup"))
            self._ds_table.setItem(row, 0, name)
            usage_item = QTableWidgetItem(f"{ds.usage_pct()}%")
            usage_item.setForeground(QBrush(QColor(_usage_color(ds.usage))))
            self._ds_table.setItem(row, 1, usage_item)
            self._ds_table.setItem(row, 2, QTableWidgetItem(
                _fmt_size(ds.used_bytes)))
            self._ds_table.setItem(row, 3, QTableWidgetItem(
                _fmt_size(ds.total_bytes)))
            self._ds_table.setItem(row, 4, QTableWidgetItem(ds.path))
        self._ds_table.resizeColumnsToContents()

    def _on_ds_dblclicked(self, item, _col):
        row = item.row()
        name_item = self._ds_table.item(row, 0)
        if name_item:
            self.show_datastore(self._server, name_item.text())

    # ── datastore view ───────────────────────────────────────────

    def _fill_status(self, ds):
        self._usage_bar.setValue(ds.usage_pct())
        self._usage_bar.setStyleSheet(
            f"QProgressBar::chunk {{ background: {_usage_color(ds.usage)}; }}")
        self._usage_lbl.setText(
            tr("{}% used — {} of {}").format(
                ds.usage_pct(), _fmt_size(ds.used_bytes),
                _fmt_size(ds.total_bytes)))
        self._path_lbl.setText(ds.path or "—")

    def _fill_snapshots(self, snaps):
        self._snap_table.setRowCount(0)
        for s in sorted(snaps, key=lambda x: (x.backup_type, x.backup_id,
                                              -(x.backup_time.timestamp()
                                                if x.backup_time else 0))):
            row = self._snap_table.rowCount()
            self._snap_table.insertRow(row)
            name_txt = f"{s.group}/{s.backup_time:%Y-%m-%d %H:%M}" \
                if s.backup_time else s.group
            name = QTableWidgetItem(name_txt)
            name.setData(Qt.UserRole, s)
            self._snap_table.setItem(row, 0, name)
            self._snap_table.setItem(row, 1, QTableWidgetItem(s.owner))
            verify = QTableWidgetItem(s.verify)
            verify.setForeground(QBrush(QColor(VERIFY_COLORS.get(
                s.verify, Color.TEXT_SEC))))
            self._snap_table.setItem(row, 2, verify)
            self._snap_table.setItem(row, 3, QTableWidgetItem(
                _fmt_size(s.size_bytes)))
            self._snap_table.setItem(row, 4, QTableWidgetItem(s.comment))
        self._snap_table.resizeColumnsToContents()
        if self._ns_combo.count() <= 1:
            self._load_namespaces()

    def _fill_jobs(self, jobs):
        self._jobs_table.setRowCount(0)
        kind_labels = {"sync": tr("Sync"), "verify": tr("Verify"),
                       "prune": tr("Prune")}
        for j in sorted(jobs, key=lambda x: (x.kind, x.id)):
            row = self._jobs_table.rowCount()
            self._jobs_table.insertRow(row)
            self._jobs_table.setItem(row, 0, QTableWidgetItem(
                kind_labels.get(j.kind, j.kind)))
            self._jobs_table.item(row, 0).setData(Qt.UserRole, j.kind)
            self._jobs_table.setItem(row, 1, QTableWidgetItem(j.id))
            self._jobs_table.setItem(row, 2, QTableWidgetItem(j.store))
            self._jobs_table.setItem(row, 3, QTableWidgetItem(j.schedule))
            state = tr("Disabled") if j.disabled else tr("Enabled")
            self._jobs_table.setItem(row, 4, QTableWidgetItem(state))
        self._jobs_table.resizeColumnsToContents()

    # ── actions ──────────────────────────────────────────────────

    def _on_verify_clicked(self):
        if not self._store:
            return
        self._start("verify_datastore", self._store,
                    tag=("verify", self._server, self._store))
        self._set_status(tr("Verify started..."))

    def _on_snap_menu(self, pos):
        row = self._snap_table.indexAt(pos).row()
        if row < 0:
            return
        item = self._snap_table.item(row, 0)
        snap = item.data(Qt.UserRole) if item else None
        if snap is None:
            return
        menu = QMenu(self)
        act_del = menu.addAction(get_icon("remove"), tr("Delete"))
        act = menu.exec(self._snap_table.viewport().mapToGlobal(pos))
        if act == act_del:
            self._forget_snapshot(snap)

    def _forget_snapshot(self, snap):
        self._start("forget_snapshot", snap,
                    tag=("forget", self._server, self._store))
        self._set_status(tr("Deleting snapshot..."))

    def _on_job_menu(self, pos):
        row = self._jobs_table.indexAt(pos).row()
        if row < 0:
            return
        kind_item = self._jobs_table.item(row, 0)
        id_item = self._jobs_table.item(row, 1)
        if not (kind_item and id_item):
            return
        kind = str(kind_item.data(Qt.UserRole) or kind_item.text().lower())
        menu = QMenu(self)
        act_run = menu.addAction(get_icon("start"), tr("Run now"))
        act = menu.exec(self._jobs_table.viewport().mapToGlobal(pos))
        if act == act_run:
            self._start("run_job", kind, id_item.text(),
                        tag=("run", self._server))
            self._set_status(tr("Starting job..."))
