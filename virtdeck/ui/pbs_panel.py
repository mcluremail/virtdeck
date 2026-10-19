"""PbsPanel — right-side panel for PBS servers and datastores (B17 stage 2).

Server view: datastore table (name, usage, used/total, path).
Datastore view: Status (usage + verify), Snapshots (ns filter, forget),
Jobs (sync/verify/prune with "Run now").

All data loads through PbsApiWorker; tags route results back.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QCoreApplication, Qt, QThreadPool, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QStackedLayout,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..pbs.workers import TRACKER_TERMINAL, PbsApiWorker, PbsTaskTracker
from .i18n import tr, tr_dict
from .icons import get_icon
from .theme import Color, enable_column_reorder, fill_bytes_column, token_name, usage_color
from .widgets.empty_state import EmptyState

# A7/Д4: colors resolve at RENDER time, not at import time — frozen
# dicts kept the light-theme values after a theme switch.
VERIFY_TOKENS = {
    "ok": "STATUS_OK",
    "failed": "DANGER",
    "none": "TEXT_SEC",
}


def _verify_color(verify: str) -> str:
    return getattr(Color, VERIFY_TOKENS.get(verify, "TEXT_SEC"))

# Cap on concurrent PBS requests started by this panel (audit 6.3.2a D9):
# workers used to start unbounded via QThreadPool directly.
_MAX_PBS_WORKERS = 16

# Separate, smaller cap for task trackers (audit 6.3.3 D16): each tracker
# is long-lived (polls one UPID until a terminal outcome), so they do not
# share the short-request budget — but they are still bounded, and hitting
# the cap is reported honestly instead of failing the task.
_MAX_PBS_TRACKERS = 8

# Tracker state → (i18n label, color-token name).  Terminal states come
# from PbsTaskTracker (success/failed/unknown/timeout); "starting" is
# the panel-side state between a confirmed UPID and the first status
# read.  Tokens resolve at render time (A7/Д4: no frozen colors).
# U31: tr_dict — labels re-translate on language change.
_TRACKER_STATE_STYLE = tr_dict(lambda: {
    "starting": (tr("Starting"), "TEXT_SEC"),
    "running": (tr("Running"), "TEXT_SEC"),
    "success": (tr("Success"), "STATUS_OK"),
    "failed": (tr("Failed"), "DANGER"),
    "unknown": (tr("Unknown outcome"), "WARNING"),
    "timeout": (tr("Watch timed out"), "WARNING"),
})


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
    """A8: shared usage contract (usage is 0..1 here)."""
    return usage_color(usage * 100.0)


class PbsPanel(QWidget):
    """PBS server / datastore details (replaces DetailPanel for pbs items)."""

    datastores_loaded = Signal(object, list)  # server_name, list[PbsDatastore]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cfg_by_name: dict[str, dict] = {}
        self._server = ""
        self._store = ""
        self._jobs_note = ""  # D10: last partial-jobs note, to clear it later
        self._workers: set = set()
        # Task tracking (audit 6.3.3 D16): (server, upid) -> (tracker,
        # stop_event).  _ops holds the display entries (newest first),
        # per server, so finished results stay readable after the
        # tracker worker is gone.
        self._trackers: dict = {}
        self._ops: list[dict] = []
        self._build_ui()
        self.destroyed.connect(lambda *_: self._stop_all_trackers())
        # audit D1: on application quit the panel may be destroyed too
        # late — Qt waits for the global thread pool's threads (a
        # tracker sleeps up to one poll interval between ticks). Stop
        # the watches proactively.
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._stop_all_trackers)

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

        # Operations strip (audit 6.3.3 D16): active and recently
        # finished PBS task watches, filtered by the current server.
        # Hidden while there is nothing to show.
        self._ops_table = QTableWidget(0, 3)
        self._ops_table.setHorizontalHeaderLabels(
            [tr("Operation"), tr("State"), tr("Detail")])
        self._ops_table.verticalHeader().setVisible(False)
        self._ops_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._ops_table.setSelectionMode(QTableWidget.SingleSelection)
        self._ops_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._ops_table.setMaximumHeight(110)
        self._ops_table.horizontalHeader().setStretchLastSection(True)
        self._ops_table.setVisible(False)
        layout.addWidget(self._ops_table)

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
        # U7/Д6: before a server is picked the panel is a hint with the
        # next step, not a bare frame with orphaned column headers
        self._ds_stack = QStackedLayout(self._ds_table)
        self._ds_stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        self._empty = EmptyState(
            "storage",
            tr("Select a backup server"),
            tr("Pick a PBS server in the navigation tree to browse "
               "its datastores"))
        self._empty.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._ds_stack.addWidget(self._empty)
        self._title_lbl.setText(tr("Backup server"))
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
        self._jobs_hint = hint
        v.addWidget(hint)
        self._tabs.addTab(w, tr("Jobs"))

    # ── config / navigation ──────────────────────────────────────

    def reapply_theme(self):
        """Recolor inline-styled surfaces after a theme change (A7/Д4).

        Status labels, the usage bar and the cached QColor brushes of
        the tables used to hold the old theme until the next data
        arrival ("Updated just now" measured at 1.6:1 on graphite).
        """
        self._path_lbl.setStyleSheet(f"color: {Color.TEXT_SEC};")
        self._jobs_hint.setStyleSheet(f"color: {Color.TEXT_SEC};")
        self._empty.reapply()
        status_token = getattr(self, "_status_color_token", None)
        if status_token:
            self._status_lbl.setStyleSheet(
                f"color: {getattr(Color, status_token)};")
        elif getattr(self, "_status_color", None) is not None:
            # non-token color — best effort, frozen value
            self._status_lbl.setStyleSheet(
                f"color: {self._status_color};")
        last_stores = getattr(self, "_last_stores", None)
        if last_stores is not None:
            self._fill_ds_table(last_stores)
        last_ds = getattr(self, "_last_ds", None)
        if last_ds is not None:
            self._fill_status(last_ds)
        # Cached brushes: ops strip (tracker states) and the snapshot
        # verify column re-resolve their colors from the live facade.
        self._render_ops()
        try:
            for row in range(self._snap_table.rowCount()):
                item = self._snap_table.item(row, 2)
                if item is not None:
                    item.setForeground(QBrush(QColor(
                        _verify_color(item.text()))))
        except RuntimeError:
            pass

    def update_nodes_cfg(self, nodes_cfg):
        self._cfg_by_name = {
            c.get("name", ""): c for c in nodes_cfg
            if c.get("type") == "pbs" and c.get("name")
        }

    def _cfg(self, server=None):
        return self._cfg_by_name.get(server or self._server)

    def _set_status(self, text, color=Color.TEXT_SEC):
        self._status_lbl.setText(text)
        # A7/Д4: keep the token NAME — the frozen value would go stale
        # with the old theme on reapply_theme().
        self._status_color_token = token_name(color)
        self._status_color = color
        self._status_lbl.setStyleSheet(f"color: {color};")

    def show_server(self, server_name):
        """Server view: datastores table."""
        if not self._cfg(server_name):
            return
        self._server = server_name
        self._store = ""
        self._empty.setVisible(False)
        self._title_lbl.setText(f"{server_name} — Proxmox Backup Server")
        self._render_ops()
        if self._cfg(server_name).get("_ambiguous"):
            # Stage 5.1.2 §3.1: conflicting connections are not refreshed.
            self._set_status(tr(
                "Name conflict — resolve it before this server is used"),
                Color.STATUS_ERR)
            return
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
        self._render_ops()
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
        if len(self._workers) >= _MAX_PBS_WORKERS:
            self._set_status(
                tr("Too many concurrent operations. Please wait and try again."),
                Color.STATUS_ERR)
            return
        worker = PbsApiWorker(cfg, method, *args, tag=tag, **kwargs)
        self._workers.add(worker)
        # Per-instance signals (audit 6.3.2a D9): connects happen before
        # start, and finished -> discard removes the worker from tracking
        # on success, error and any exception (finished fires in finally).
        worker.signals.done.connect(self._on_worker_done)
        worker.signals.failed.connect(self._on_worker_failed)
        worker.signals.finished.connect(
            lambda w=worker: self._workers.discard(w))
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
                    jobs, failed_kinds = result  # D10: (jobs, failed_kinds)
                    self._fill_jobs(jobs, failed_kinds)
            elif kind == "run":
                if tag[1] != self._server:
                    return  # stale result for another server (§6.9)
                if isinstance(result, str) and result.strip():
                    # result is the confirmed UPID (audit 6.3.3 D16):
                    # the start really happened — now watch its outcome
                    self._start_tracker(
                        tag[1], result.strip(),
                        tr("Run job {kind}/{id}").format(
                            kind=tag[2], id=tag[3]))
                    self._set_status(tr("Job started"), Color.STATUS_OK)
                    self._start("jobs", tag=("jobs", self._server))
                else:
                    self._set_status(
                        tr("Job start could not be confirmed — no task "
                           "id in the response"), Color.WARNING)
            elif kind == "forget":
                self._set_status(tr("Snapshot deleted"), Color.STATUS_OK)
                self._load_snapshots()
            elif kind == "verify":
                if tag[1] != self._server:
                    return  # stale result for another server (§6.9)
                if isinstance(result, str) and result.strip():
                    self._start_tracker(
                        tag[1], result.strip(),
                        tr("Verify datastore {store}").format(
                            store=tag[2]))
                    self._set_status(tr("Verify started"), Color.STATUS_OK)
                else:
                    self._set_status(
                        tr("Job start could not be confirmed — no task "
                           "id in the response"), Color.WARNING)
        except RuntimeError:
            pass

    def _on_worker_failed(self, tag, error):
        try:
            self._set_status(error, Color.STATUS_ERR)
        except RuntimeError:
            pass

    # ── task tracking (audit 6.3.3 D16) ──────────────────────────

    def _start_tracker(self, server: str, upid: str, op_label: str) -> None:
        """Watch one UPID in the background; register a display row.

        One tracker per (server, upid); bounded by _MAX_PBS_TRACKERS —
        hitting the cap means the result will not be watched (reported
        honestly), never that the task failed.
        """
        key = (server, upid)
        if key in self._trackers:
            self._set_status(tr("This task is already being tracked"),
                             Color.WARNING)
            return
        if len(self._trackers) >= _MAX_PBS_TRACKERS:
            self._set_status(
                tr("Tracking limit reached — the result will not be "
                   "watched; check the server"), Color.STATUS_ERR)
            return
        cfg = self._cfg(server)
        if not cfg:
            return
        stop = threading.Event()
        tracker = PbsTaskTracker(cfg, upid, tag=key, stop_event=stop)
        self._trackers[key] = (tracker, stop)
        self._ops_add(key, op_label)
        # Connects happen before start (audit 6.3.2a D9): a fast
        # completion cannot race the wiring; per-instance signals keep
        # finished->discard from leaking closed widgets.
        tracker.signals.update.connect(self._on_tracker_update)
        tracker.signals.finished.connect(
            lambda k=key, t=tracker: self._on_tracker_finished(k, t))
        QThreadPool.globalInstance().start(tracker)

    def _on_tracker_update(self, key, payload):
        try:
            server, _upid = key
            state, detail = payload
            entry = self._ops_update(key, state, detail)
            if server != self._server:
                return  # another server's watcher must not touch this UI
            label, color = _TRACKER_STATE_STYLE.get(
                state, (state, Color.TEXT_SEC))
            if entry is not None:
                self._render_ops()
            if state == "success":
                self._set_status(tr("Task finished successfully"),
                                 Color.STATUS_OK)
            elif state == "failed":
                self._set_status(
                    tr("Task failed: {detail}").format(detail=detail),
                    Color.STATUS_ERR)
            elif state == "unknown":
                self._set_status(
                    tr("Task outcome unknown: {detail}").format(
                        detail=detail), Color.WARNING)
            elif state == "timeout":
                self._set_status(
                    tr("Task watch timed out — it may still be running "
                       "on the server"), Color.WARNING)
        except RuntimeError:
            pass

    def _on_tracker_finished(self, key, tracker):
        try:
            known = self._trackers.get(key)
            if known is not None and known[0] is tracker:
                del self._trackers[key]
        except RuntimeError:
            pass

    def _stop_all_trackers(self, *_args) -> None:
        """End all watches promptly (panel is being destroyed)."""
        for _tracker, stop in self._trackers.values():
            stop.set()

    # ── operations strip ─────────────────────────────────────────

    def _ops_add(self, key, op_label: str) -> None:
        self._ops.insert(0, {
            "key": key, "op": op_label, "state": "starting", "detail": "",
        })
        self._render_ops()

    def _ops_update(self, key, state: str, detail: str) -> dict | None:
        for entry in self._ops:
            if entry["key"] == key:
                entry["state"] = state
                entry["detail"] = detail
                if state in TRACKER_TERMINAL:
                    self._ops_prune()
                self._render_ops()
                return entry
        return None

    def _ops_prune(self) -> None:
        """Keep the last few finished results per server readable."""
        kept: dict[str, int] = {}
        kept_entries: list[dict] = []
        for entry in self._ops:
            if entry["state"] in TRACKER_TERMINAL:
                server = entry["key"][0]
                kept[server] = kept.get(server, 0) + 1
                if kept[server] > 8:
                    continue  # drop the oldest finished result
            kept_entries.append(entry)
        self._ops = kept_entries

    def _render_ops(self) -> None:
        try:
            rows = [e for e in self._ops if e["key"][0] == self._server]
            self._ops_table.setRowCount(0)
            for entry in rows:
                row = self._ops_table.rowCount()
                self._ops_table.insertRow(row)
                self._ops_table.setItem(row, 0, QTableWidgetItem(
                    entry["op"]))
                label, token = _TRACKER_STATE_STYLE.get(
                    entry["state"], (tr(str(entry["state"])), "TEXT_SEC"))
                state_item = QTableWidgetItem(label)
                state_item.setForeground(QBrush(QColor(getattr(Color, token))))
                self._ops_table.setItem(row, 1, state_item)
                self._ops_table.setItem(row, 2, QTableWidgetItem(
                    entry["detail"]))
            self._ops_table.resizeColumnsToContents()
            self._ops_table.setVisible(bool(rows))
        except RuntimeError:
            pass

    # ── server view ──────────────────────────────────────────────

    def _fill_ds_table(self, stores):
        self._last_stores = stores  # A7/Д4: for reapply_theme
        self._ds_table.setRowCount(0)
        ordered = sorted(stores, key=lambda d: d.name.lower())
        for ds in ordered:
            row = self._ds_table.rowCount()
            self._ds_table.insertRow(row)
            name = QTableWidgetItem(ds.name)
            name.setIcon(get_icon("backup"))
            self._ds_table.setItem(row, 0, name)
            if ds.status_ok:
                usage_item = QTableWidgetItem(f"{ds.usage_pct()}%")
                usage_item.setForeground(QBrush(QColor(_usage_color(ds.usage))))
            else:
                # status call failed — dashes, not fake zeros (audit D1)
                usage_item = QTableWidgetItem("—")
                usage_item.setForeground(QBrush(QColor(Color.TEXT_SEC)))
                usage_item.setToolTip(tr("Usage data unavailable"))
            self._ds_table.setItem(row, 1, usage_item)
            self._ds_table.setItem(row, 4, QTableWidgetItem(ds.path))
        # A10: one unit per column (no GiB/TiB jumps cell by cell),
        # right-aligned numbers; None -> dash for failed status calls
        fill_bytes_column(
            self._ds_table, 2,
            [ds.used_bytes if ds.status_ok else None for ds in ordered])
        fill_bytes_column(
            self._ds_table, 3,
            [ds.total_bytes if ds.status_ok else None for ds in ordered])
        self._ds_table.resizeColumnsToContents()

    def _on_ds_dblclicked(self, item):
        # QTableWidget.itemDoubleClicked emits ONE argument (the item) —
        # unlike QTreeWidget's (item, column). The extra parameter turned
        # every datastore double-click into a TypeError (live test,
        # 2026-10-19).
        row = item.row()
        name_item = self._ds_table.item(row, 0)
        if name_item:
            self.show_datastore(self._server, name_item.text())

    # ── datastore view ───────────────────────────────────────────

    def _fill_status(self, ds):
        self._last_ds = ds  # A7/Д4: for reapply_theme
        if ds.status_ok:
            self._usage_bar.setValue(ds.usage_pct())
            self._usage_bar.setStyleSheet(
                f"QProgressBar::chunk {{ background: {_usage_color(ds.usage)}; }}")
            self._usage_lbl.setText(
                tr("{}% used — {} of {}").format(
                    ds.usage_pct(), _fmt_size(ds.used_bytes),
                    _fmt_size(ds.total_bytes)))
        else:
            # status call failed — do not show fake zeros (audit D1)
            self._usage_bar.setValue(0)
            self._usage_bar.setStyleSheet(
                f"QProgressBar::chunk {{ background: {Color.TEXT_SEC}; }}")
            self._usage_lbl.setText(tr("Usage data unavailable"))
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
            verify.setForeground(QBrush(QColor(_verify_color(s.verify))))
            self._snap_table.setItem(row, 2, verify)
            self._snap_table.setItem(row, 3, QTableWidgetItem(
                _fmt_size(s.size_bytes)))
            self._snap_table.setItem(row, 4, QTableWidgetItem(s.comment))
        self._snap_table.resizeColumnsToContents()
        if self._ns_combo.count() <= 1:
            self._load_namespaces()

    def _fill_jobs(self, jobs, failed_kinds=()):
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
        # audit 6.3.2b D10: a partly unreadable job list must not look
        # like a confident "no jobs"; the note clears on a full success
        note = ""
        if failed_kinds:
            note = tr("Some job types could not be read: {kinds}").format(
                kinds=", ".join(failed_kinds))
            self._set_status(note, Color.WARNING)
        elif self._jobs_note and self._status_lbl.text() == self._jobs_note:
            self._set_status("")
        self._jobs_note = note

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
            # tag carries (server, kind, id): the tracker row needs the
            # operation label, and stale results must be server-filtered
            self._start("run_job", kind, id_item.text(),
                        tag=("run", self._server, kind, id_item.text()))
            self._set_status(tr("Starting job..."))
