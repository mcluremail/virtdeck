import json
from datetime import datetime, timezone

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...config import load_ui_state, save_ui_state
from ...domain.task import Task
from ..hover import enable_row_hover
from ..i18n import tr
from ..theme import Color, enable_column_reorder, enable_table_autofit

TASK_COL_WIDTHS_KEY = "task_col_widths"


TASK_TYPE_LABELS = {
    # VM
    "qemstart": tr("Start VM"),
    "qmstart": tr("Start VM"),
    "qemstop": tr("Stop VM"),
    "qmstop": tr("Stop VM"),
    "qemshutdown": tr("Shutdown VM"),
    "qmshutdown": tr("Shutdown VM"),
    "qemreboot": tr("Reboot VM"),
    "qmreboot": tr("Reboot VM"),
    "qemreset": tr("Reset VM"),
    "qmreset": tr("Reset VM"),
    "qemsuspend": tr("Suspend VM"),
    "qmgestsuspend": tr("Suspend VM"),
    "qmresume": tr("Resume VM"),
    "qmgestscreenshot": tr("VM Screenshot"),
    "qmgstdstva": tr("VM Task"),
    "spiceproxy": tr("SPICE Console"),
    "vncproxy": tr("VNC Console"),
    "console": tr("Console"),
    # LXC
    "lxc-start": tr("Start Container"),
    "lxc-stop": tr("Stop Container"),
    "lxc-shutdown": tr("Shutdown Container"),
    "lxc-reboot": tr("Reboot Container"),
    "lxc-suspend": tr("Suspend Container"),
    "lxc-resume": tr("Resume Container"),
    "vzstart": tr("Start Container"),
    "vzstop": tr("Stop Container"),
    "vzreboot": tr("Reboot Container"),
    # VM/Container management
    "create": tr("Create"),
    "destroy": tr("Destroy"),
    "clone": tr("Clone"),
    "qmigrate": tr("Migrate"),
    "resize": tr("Resize Disk"),
    "qmmove": tr("Move Disk"),
    "move": tr("Move"),
    "diskread": tr("Disk Read"),
    "diskwrite": tr("Disk Write"),
    "imgdel": tr("Delete Image"),
    "imgcopy": tr("Copy Image"),
    # Snapshots
    "snapshot": tr("Create Snapshot"),
    "snapdestroy": tr("Delete Snapshot"),
    "snaprollback": tr("Rollback to Snapshot"),
    "snapremove": tr("Delete Snapshot"),
    # Backups and restore
    "vzdump": tr("Backup"),
    "restore": tr("Restore"),
    "verify": tr("Verify Backups"),
    "pull": tr("Import Backup"),
    # Storage
    "dfs-migrate": tr("Migrate Storage"),
    "dfs-del": tr("Delete from Storage"),
    # Network
    "sdn-apply": tr("Apply SDN"),
    # Updates
    "pveupdate": tr("Update PVE"),
    "pveproxy": tr("Update Proxy"),
    "apt": tr("APT Operation"),
    # HA
    "ha-manager": tr("HA Manager"),
    "ha-crm": tr("HA CRM"),
    # Security and ACME
    "acmedns": tr("ACME DNS Challenge"),
    "pvefw-logger": tr("PVE Firewall"),
    # Replication
    "repl": tr("Replication"),
    # Ceph
    "ceph-apply": tr("Apply Ceph"),
    "ceph-destroy": tr("Destroy Ceph"),
    "ceph-create-fs": tr("Create Ceph FS"),
    "ceph-install": tr("Install Ceph"),
}

TIMESTAMP_FMT = "%d.%m.%y %H:%M"


class NumericTableItem(QTableWidgetItem):
    def __lt__(self, other):
        if not isinstance(other, QTableWidgetItem):
            return super().__lt__(other)
        a = self.data(Qt.UserRole)
        b = other.data(Qt.UserRole)
        if a is not None and b is not None:
            try:
                return float(a) < float(b)
            except (ValueError, TypeError):
                pass
        return super().__lt__(other)


class ClusterTasksWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_tasks = []
        self._sort_initialized = False
        self.table = QTableWidget()
        self.table.verticalHeader().hide()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            tr("Start time"), tr("End time"), tr("Host"), tr("User"), tr("Description"), tr("Status")
        ])

        h = self.table.horizontalHeader()
        h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h.setStyleSheet("QHeaderView::section { padding-left: 4px; }")
        h.setSectionResizeMode(QHeaderView.Interactive)
        h.setSectionResizeMode(0, QHeaderView.Interactive)
        h.setSectionResizeMode(1, QHeaderView.Interactive)
        # All columns resize by mouse; Status (last) is a filler column,
        # so the table still always fills the panel width.
        h.setSectionResizeMode(5, QHeaderView.Interactive)
        enable_column_reorder(h)
        enable_table_autofit(self.table, [2, 3, 4], max_width=480)
        h.setStretchLastSection(True)

        self.table.setColumnWidth(0, 155)
        self.table.setColumnWidth(1, 155)
        self.table.setColumnWidth(5, 180)

        # Restore column widths (changes saved via sectionResized)
        self._restore_column_widths()
        # Debounced save: sectionResized fires per pixel while dragging and
        # each save_ui_state is a SQLite round-trip on the main thread —
        # persisting directly here froze the UI (B17 follow-up).
        self._col_save_timer = QTimer(self)
        self._col_save_timer.setSingleShot(True)
        self._col_save_timer.setInterval(800)
        self._col_save_timer.timeout.connect(self._save_column_widths)
        h.sectionResized.connect(self._col_save_timer.start)

        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        enable_row_hover(self.table)
        h.sortIndicatorChanged.connect(self._on_sort_changed)

        # Filter bar — compact, right-aligned
        filter_bar = QHBoxLayout()
        filter_bar.setContentsMargins(8, 6, 8, 6)
        filter_bar.setSpacing(6)
        filter_bar.addStretch()

        self._progress_items = {}
        self._progress_rows = {}
        self._filter_input = QLineEdit()
        self._filter_input.setPlaceholderText(tr("Filter..."))
        self._filter_input.setClearButtonEnabled(True)
        self._filter_input.setMaximumWidth(200)
        self._filter_input.textChanged.connect(self._apply_filter)
        filter_bar.addWidget(self._filter_input)

        self._status_filter = QComboBox()
        # ru "Running" is wider than the default 90px — clipped when collapsed
        self._status_filter.setMaximumWidth(140)
        self._status_filter.addItem(tr("All"), "all")
        self._status_filter.addItem(tr("OK"), "OK")
        self._status_filter.addItem(tr("Errors"), "error")
        self._status_filter.addItem(tr("Running"), "RUNNING")
        self._status_filter.currentIndexChanged.connect(self._apply_filter)
        filter_bar.addWidget(self._status_filter)

        filter_widget = QWidget()
        filter_widget.setLayout(filter_bar)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.table, 1)
        layout.addWidget(filter_widget)

    def set_tasks(self, tasks: list[Task]):
        self._all_tasks = tasks
        # Re-apply the active filter instead of dumping everything into the
        # table; also re-inserts any in-flight progress rows.
        self._apply_filter()

    def _populate_table(self, tasks: list[Task]):
        sort_col = self.table.horizontalHeader().sortIndicatorSection()
        sort_order = self.table.horizontalHeader().sortIndicatorOrder()

        # Sort data before inserting — avoids O(n log n) Python __lt__ calls
        # during sortItems which freezes the UI on 400+ rows
        tasks = self._sort_tasks(tasks, sort_col, sort_order)

        # Block model signals — otherwise ResizeToContents and sorting
        # react to every setItem, causing O(n²) with 500+ rows
        self.table.setUpdatesEnabled(False)
        self.table.model().blockSignals(True)
        self.table.setRowCount(len(tasks))

        for i, task in enumerate(tasks):
            start_ts = task.starttime
            if start_ts:
                try:
                    start_dt = datetime.fromtimestamp(float(start_ts), tz=timezone.utc)
                    start_str = start_dt.strftime(TIMESTAMP_FMT)
                except (ValueError, TypeError):
                    start_str = str(start_ts)
            else:
                start_str = ''
            item0 = NumericTableItem(start_str)
            if start_ts:
                item0.setData(Qt.UserRole, float(start_ts))
            self.table.setItem(i, 0, item0)

            end_ts = task.endtime
            if end_ts:
                try:
                    end_dt = datetime.fromtimestamp(float(end_ts), tz=timezone.utc)
                    end_str = end_dt.strftime(TIMESTAMP_FMT)
                except (ValueError, TypeError):
                    end_str = str(end_ts)
            else:
                end_str = ''
            item1 = NumericTableItem(end_str)
            if end_ts:
                item1.setData(Qt.UserRole, float(end_ts))
            if not end_str:
                item1.setForeground(QColor(Color.STATUS_WARN))
                item1.setText(tr("running..."))
            self.table.setItem(i, 1, item1)

            host_display = task.display_name or task.node or '—'
            self.table.setItem(i, 2, QTableWidgetItem(host_display))

            self.table.setItem(i, 3, QTableWidgetItem(task.user))

            label = TASK_TYPE_LABELS.get(task.task_type, task.task_type)
            vmid = task.vmid
            vm_name = task.vm_name or ''
            if vmid and vm_name:
                desc = f"{label} {vm_name} ({vmid})"
            elif vmid:
                desc = f"{label} {vmid}"
            else:
                desc = label
            item4 = QTableWidgetItem(desc)
            font = item4.font()
            font.setBold(True)
            item4.setFont(font)
            self.table.setItem(i, 4, item4)

            status = task.status
            item5 = QTableWidgetItem(status[:30] + '…' if len(status) > 30 else status)
            item5.setToolTip(status if len(status) > 30 else '')
            if status == 'OK':
                item5.setForeground(QColor(Color.STATUS_OK))
            elif status == 'RUNNING':
                item5.setForeground(QColor(Color.STATUS_WARN))
            else:
                item5.setForeground(QColor(Color.STATUS_ERR))
            self.table.setItem(i, 5, item5)

        self.table.resizeRowsToContents()
        for r in range(self.table.rowCount()):
            if self.table.rowHeight(r) > 22:
                self.table.setRowHeight(r, 22)

        self.table.model().blockSignals(False)
        self.table.setUpdatesEnabled(True)

        # Re-insert in-flight progress rows on top: a timer-driven set_tasks
        # must not wipe the progress indicator of a running backup/restore.
        for key, description in self._progress_items.items():
            self._insert_progress_row(key, description)

        # Set sort indicator visual only — do NOT enable sorting
        # (setSortingEnabled(True) triggers sortItems with Python __lt__
        # which freezes on 400+ rows; data is already sorted in Python)
        if not self._sort_initialized:
            self._sort_initialized = True
            self.table.horizontalHeader().setSortIndicator(0, Qt.DescendingOrder)
        else:
            self.table.horizontalHeader().setSortIndicator(sort_col, sort_order)

    def _sort_tasks(self, tasks: list[Task], col, order) -> list[Task]:
        """Sort task list in Python before inserting — avoids slow sortItems()."""
        if not tasks:
            return tasks
        reverse = (order == Qt.DescendingOrder)
        if col == 0:
            key = lambda t: float(t.starttime or 0)
        elif col == 1:
            key = lambda t: float(t.endtime or 0)
        elif col == 2:
            key = lambda t: (t.display_name or t.node or '').lower()
        elif col == 3:
            key = lambda t: (t.user or '').lower()
        elif col == 4:
            key = lambda t: (t.task_type or '').lower()
        elif col == 5:
            key = lambda t: (t.status or '').lower()
        else:
            return tasks
        try:
            return sorted(tasks, key=key, reverse=reverse)
        except (TypeError, ValueError):
            return tasks

    def set_placeholder(self, text=None):
        if text is None:
            text = tr("Loading tasks...")
        self._all_tasks = []
        self.table.setUpdatesEnabled(False)
        self.table.model().blockSignals(True)
        self.table.setRowCount(0)
        self.table.setRowCount(1)
        item = QTableWidgetItem(text)
        item.setForeground(QColor(Color.TEXT_SEC))
        self.table.setItem(0, 4, item)
        self.table.model().blockSignals(False)
        self.table.setUpdatesEnabled(True)

    # --- Progress bar row for upload/transfer operations ---

    def add_progress_row(self, key, description):
        """Insert a row at top showing a progress bar in the Status column."""
        self.table.insertRow(0)
        now_str = datetime.now().strftime(TIMESTAMP_FMT)
        item0 = QTableWidgetItem(now_str)
        item0.setForeground(QColor(Color.STATUS_WARN))
        self.table.setItem(0, 0, item0)
        item1 = QTableWidgetItem(tr("running..."))
        item1.setForeground(QColor(Color.STATUS_WARN))
        self.table.setItem(0, 1, item1)
        self.table.setItem(0, 2, QTableWidgetItem(""))
        self.table.setItem(0, 3, QTableWidgetItem(""))
        item4 = QTableWidgetItem(description)
        font = item4.font()
        font.setBold(True)
        item4.setFont(font)
        self.table.setItem(0, 4, item4)
        self._make_progress_bar(0)
        self.table.setRowHeight(0, 22)
        self._progress_items[key] = description
        self._progress_rows[key] = 0

    def _make_progress_bar(self, row):
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setFixedHeight(16)
        bar.setStyleSheet(
            f"QProgressBar {{ border: 1px solid {Color.BORDER_LIGHT}; border-radius: 3px;"
            f" text-align: center; font-size: 11px; }}"
            f"QProgressBar::chunk {{ background: {Color.STATUS_WARN}; border-radius: 2px; }}"
        )
        self.table.setCellWidget(row, 5, bar)

    def _insert_progress_row(self, key, description):
        self.table.insertRow(0)
        now_str = datetime.now().strftime(TIMESTAMP_FMT)
        item0 = QTableWidgetItem(now_str)
        item0.setForeground(QColor(Color.STATUS_WARN))
        self.table.setItem(0, 0, item0)
        item1 = QTableWidgetItem(tr("running..."))
        item1.setForeground(QColor(Color.STATUS_WARN))
        self.table.setItem(0, 1, item1)
        self.table.setItem(0, 2, QTableWidgetItem(""))
        self.table.setItem(0, 3, QTableWidgetItem(""))
        item4 = QTableWidgetItem(description)
        font = item4.font()
        font.setBold(True)
        item4.setFont(font)
        self.table.setItem(0, 4, item4)
        self._make_progress_bar(0)
        self.table.setRowHeight(0, 22)
        self._progress_rows[key] = 0

    def update_progress_row(self, key, percent):
        rows = getattr(self, "_progress_rows", {})
        if key not in rows:
            return
        row = rows[key]
        bar = self.table.cellWidget(row, 5)
        if isinstance(bar, QProgressBar):
            bar.setValue(percent)

    def finish_progress_row(self, key, success, message=""):
        rows = getattr(self, "_progress_rows", {})
        if key not in rows:
            return
        row = rows[key]
        self._progress_items.pop(key, None)
        bar = self.table.cellWidget(row, 5)
        if isinstance(bar, QProgressBar):
            self.table.removeCellWidget(row, 5)
        if success:
            now_str = datetime.now().strftime(TIMESTAMP_FMT)
            self.table.setItem(row, 1, QTableWidgetItem(now_str))
            item5 = QTableWidgetItem("OK")
            item5.setForeground(QColor(Color.STATUS_OK))
            self.table.setItem(row, 5, item5)
        else:
            item5 = QTableWidgetItem(tr("Error"))
            item5.setForeground(QColor(Color.STATUS_ERR))
            self.table.setItem(row, 5, item5)
        if message:
            self.table.setItem(row, 4, QTableWidgetItem(message))
        del rows[key]

    def _on_sort_changed(self, col, order):
        """User clicked column header — re-sort data in Python."""
        self._populate_table(self._all_tasks)

    def _save_column_widths(self):
        widths = [self.table.columnWidth(c) for c in range(self.table.columnCount())]
        save_ui_state(TASK_COL_WIDTHS_KEY, json.dumps(widths))

    def _restore_column_widths(self):
        raw = load_ui_state(TASK_COL_WIDTHS_KEY)
        if not raw:
            return
        try:
            widths = json.loads(raw)
            if isinstance(widths, list) and len(widths) == self.table.columnCount():
                for c, w in enumerate(widths):
                    if c in (4, 5):
                        # 4 — Description: auto-sized to content;
                        # 5 — Status: filler column (stretchLastSection).
                        continue
                    self.table.setColumnWidth(c, w)
        except (TypeError, ValueError):
            pass

    def _apply_filter(self):
        text = self._filter_input.text().strip().lower()
        status_filter = self._status_filter.currentData() or "all"
        if not text and status_filter == "all":
            self._populate_table(self._all_tasks)
            return
        filtered = []
        for task in self._all_tasks:
            status = task.status
            if status_filter == "OK" and status != "OK":
                continue
            if status_filter == "error" and status == "OK":
                continue
            if status_filter == "RUNNING" and status != "RUNNING":
                continue
            if text:
                node = (task.node or "").lower()
                user = (task.user or "").lower()
                ttype = (task.task_type or "").lower()
                vm_name = (task.vm_name or "").lower()
                upid = (task.upid or "").lower()
                haystack = f"{node} {user} {ttype} {vm_name} {upid} {status.lower()}"
                if text not in haystack:
                    continue
            filtered.append(task)
        self._populate_table(filtered)
