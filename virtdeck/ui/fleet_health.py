"""Fleet Health (M4.5): summary report across all fleet clusters.

"The whole fleet at a glance": backup compliance, version drift,
storage runway and (on demand) snapshot sprawl. The report shows
"what is red where": row color by severity; double-click on a guest —
navigate to the object in the tree. A partial collection does not empty
the report: a "data as of HH:MM" badge on a cluster whose sources did
not all collect.
"""

from __future__ import annotations

import threading
from datetime import datetime

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ..backend.fleet import ClusterBundle, FleetHealthWorker
from ..domain.fleet import GuestBackupState
from ..fleet.collector import TASK_HISTORY_LIMIT
from ..fleet.drift import detect_drift
from ..fleet.runway import SPARSE
from .api.fleet import scan_fleet_snapshots
from .i18n import tr
from .icons import get_icon
from .theme import Color, enable_column_reorder, enable_table_autofit

KEY_ROLE = Qt.UserRole + 1

COMPLIANCE_STALE_DAYS = 14
RUNWAY_WARN_DAYS = 30
RUNWAY_DANGER_DAYS = 7
SPRAWL_DANGER_DAYS = 90

# row severity: 2 — red, 1 — yellow, 0 — neutral
_SEV_RED, _SEV_WARN, _SEV_PLAIN = 2, 1, 0

_SECTIONS = (
    ("compliance", "Backup compliance"),
    ("drift", "Version drift"),
    ("runway", "Storage runway"),
    ("sprawl", "Snapshot sprawl"),
)


class _ScanSignals(QObject):
    scans_done = Signal()
    progress = Signal(int, int)


class FleetHealthDialog(QDialog):
    """Fleet-wide summary report; emits the tree key of a chosen object."""

    object_selected = Signal(tuple)

    def __init__(self, targets, parent=None, pbs_cfgs=None):
        super().__init__(parent)
        self._targets = list(targets)
        self._pbs_cfgs = list(pbs_cfgs or [])
        self._bundles: list[ClusterBundle] = []
        self._scans: dict[str, object] = {}
        self._worker: FleetHealthWorker | None = None
        self._scan_thread: threading.Thread | None = None
        self._scan_signals = _ScanSignals()
        self._scan_signals.scans_done.connect(self._on_scan_done)
        self._scan_signals.progress.connect(self._on_scan_progress)
        self._build_ui()
        self._load()

    # ── UI ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self.setWindowTitle(tr("Fleet Health"))
        self.setMinimumSize(760, 520)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(16, 16, 16, 12)

        buttons = QHBoxLayout()
        self._refresh_btn = QPushButton(get_icon("refresh"), tr("Refresh"))
        self._refresh_btn.clicked.connect(self._load)
        buttons.addWidget(self._refresh_btn)
        self._scan_btn = QPushButton(get_icon("snapshot"),
                                     tr("Scan snapshots"))
        self._scan_btn.clicked.connect(self._scan_snapshots)
        buttons.addWidget(self._scan_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(4)
        self._tree.setHeaderLabels([tr("Cluster"), tr("Object"),
                                    tr("Issue"), tr("Detail")])
        self._tree.setAllColumnsShowFocus(True)
        self._tree.itemDoubleClicked.connect(self._activate_item)
        self._tree.itemActivated.connect(self._activate_item)
        layout.addWidget(self._tree, 1)

        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {Color.TEXT_SEC};")
        layout.addWidget(self._status)

        enable_column_reorder(self._tree.header())
        enable_table_autofit(self._tree, [0, 1, 2], max_width=360)
        self._tree.header().setStretchLastSection(True)

    # ── Report loading ──────────────────────────────────────────────

    def _load(self) -> None:
        if self._worker is not None:
            return  # collection already running
        self._refresh_btn.setEnabled(False)
        self._scan_btn.setEnabled(False)
        self._status.setText(tr("Loading fleet data..."))
        self._worker = FleetHealthWorker(self._targets,
                                         pbs_cfgs=self._pbs_cfgs)
        self._worker.finished_all.connect(self._on_load_finished)
        self._worker.start()

    def _on_load_finished(self, bundles: list) -> None:
        self._bundles = sorted(bundles, key=lambda b: b.report.cluster)
        self._worker = None
        self._refresh_btn.setEnabled(True)
        self._scan_btn.setEnabled(True)
        self._render()

    # ── Snapshot sprawl on demand ───────────────────────────────────

    def _scan_snapshots(self) -> None:
        if self._scan_thread is not None or not self._bundles:
            return
        self._scan_btn.setEnabled(False)
        self._refresh_btn.setEnabled(False)
        self._status.setText(tr("Scanning snapshots..."))
        self._scan_thread = threading.Thread(
            target=self._scan_worker, daemon=True)
        self._scan_thread.start()

    def _scan_worker(self) -> None:
        self._scans = scan_fleet_snapshots(
            self._targets, self._bundles,
            on_progress=lambda done, total:
                self._scan_signals.progress.emit(done, total))
        self._scan_signals.scans_done.emit()

    def _on_scan_progress(self, done: int, total: int) -> None:
        if self._scan_thread is not None:
            self._status.setText(tr("Scanning... {}/{}").format(done, total))

    def _on_scan_done(self) -> None:
        self._scan_thread = None
        if self._worker is None:
            self._refresh_btn.setEnabled(True)
            self._scan_btn.setEnabled(True)
            self._render()

    # ── Rendering ───────────────────────────────────────────────────

    def _render(self) -> None:
        self._tree.clear()
        total_issues = 0
        for bundle in self._bundles:
            _item, issues = self._render_cluster(bundle)
            total_issues += issues
        # honesty first: "no issues" on a broken collection would be a lie
        incomplete = sum(1 for b in self._bundles if not b.report.complete)
        if total_issues:
            status = tr("{} issues on {} clusters").format(
                total_issues, len(self._bundles))
        else:
            status = tr("No issues found")
        if incomplete:
            status += "  ·  " + tr("{} with incomplete data").format(
                incomplete)
        self._status.setText(status)

    def _render_cluster(self, bundle: ClusterBundle) \
            -> tuple[QTreeWidgetItem, int]:
        report = bundle.report
        if report.complete:
            status = "OK"
        elif report.coverage is None:
            status = "error"  # main collection never happened
        else:
            status = "warning"
        label = bundle.display or report.cluster
        cluster_item = QTreeWidgetItem([label, "", "", ""])
        if not report.complete:
            if report.generated_at == 0:
                # provider never answered — a formatted epoch (1970) lies
                label += "  ·  " + tr("Data unavailable")
            else:
                label += "  ·  " + tr("Data from {}").format(
                    _fmt_time(report.generated_at))
            # incomplete data — signal color, not a quiet grey
            cluster_item.setText(0, label)
            cluster_item.setForeground(0, QColor(Color.WARNING))
        cluster_item.setIcon(0, get_icon("cluster", status=status))

        if report.tasks_truncated:
            # an honest caveat, not an issue: old "ok" tasks may be cut
            # off, "never backed up" can be an artifact of the limit
            cluster_item.addChild(self._issue_row(
                "", tr("Task history truncated"),
                tr("Only the newest {} tasks are analyzed — older "
                   "successful backups may be missing").format(
                    TASK_HISTORY_LIMIT),
                _SEV_PLAIN, key=None, icon="history"))

        sections = {
            "compliance": self._compliance_rows(bundle),
            "drift": self._drift_rows(bundle),
            "runway": self._runway_rows(bundle),
            "sprawl": self._sprawl_rows(report.cluster),
        }
        issues = 0
        section_items = []
        for section_key, title in _SECTIONS:
            rows = sections[section_key]
            if not rows:
                continue
            section_item = QTreeWidgetItem([tr(title), "", "", ""])
            font = section_item.font(0)
            font.setBold(True)
            section_item.setFont(0, font)
            section_item.setForeground(0, QColor(Color.TEXT_SEC))
            section_item.setFirstColumnSpanned(True)
            cluster_item.addChild(section_item)
            for row, _sev in rows:
                section_item.addChild(row)
            section_items.append(section_item)
            issues += sum(1 for _r, sev in rows if sev >= 1)
        self._tree.addTopLevelItem(cluster_item)
        cluster_item.setExpanded(True)
        # section expansion — only after insertion into the tree: before
        # insert, Qt does not persist setExpanded and rows would stay hidden
        for section_item in section_items:
            section_item.setExpanded(True)
        return cluster_item, issues

    def _compliance_rows(self, bundle: ClusterBundle) -> list:
        report = bundle.report
        if report.coverage is None:
            return []
        rows: list = []
        for guest in sorted(report.guests, key=lambda g: g.vmid):
            if guest.template:
                continue
            state = report.backup_states.get(guest.vmid,
                                             GuestBackupState(vmid=guest.vmid))
            key = (report.cluster, guest.vmid, guest.node)
            label = _guest_label(guest)
            if guest.vmid in report.coverage.uncovered:
                rows.append((self._issue_row(label,
                    tr("Not covered by any backup job"), "",
                    _SEV_RED, key), _SEV_RED))
                continue
            if not state.ever_backed_up:
                rows.append((self._issue_row(label, tr("Never backed up"),
                    "", _SEV_RED, key), _SEV_RED))
                continue
            if state.task_last_failed is not None and (
                    state.last_successful is None
                    or state.task_last_failed > state.last_successful):
                rows.append((self._issue_row(label, tr("Last backup failed"),
                    "", _SEV_RED, key), _SEV_RED))
                continue
            age = (report.generated_at
                   - (state.last_successful or 0)) / 86400
            if age > COMPLIANCE_STALE_DAYS:
                rows.append((self._issue_row(label,
                    tr("Last backup is {} days old").format(int(age)),
                    "", _SEV_WARN, key), _SEV_WARN))
        return rows

    def _drift_rows(self, bundle: ClusterBundle) -> list:
        """All cluster nodes with their versions: ok — neutral, lagging
        ones colored. That way versions are always visible, not only
        when there are problems."""
        report = bundle.report
        rows: list = []
        for drift in detect_drift(report.node_versions):
            key = ("host", drift.node, report.cluster)
            if drift.level == "ok":
                issue, sev = tr("Up to date"), _SEV_PLAIN
            elif drift.level == "major":
                issue, sev = tr("Behind by major version"), _SEV_RED
            elif drift.level == "minor":
                issue, sev = tr("Behind by minor version"), _SEV_WARN
            elif drift.level == "unknown":
                issue, sev = tr("Version unknown"), _SEV_WARN
            else:
                issue, sev = tr("Outdated patch level"), _SEV_PLAIN
            rows.append((self._issue_row(drift.node, issue,
                _version_label(drift.version), sev, key, icon="host"), sev))
        return rows

    def _runway_rows(self, bundle: ClusterBundle) -> list:
        rows: list = []
        for est in bundle.runway:
            if est.days_left is None:
                continue
            if est.days_left < RUNWAY_DANGER_DAYS:
                sev = _SEV_RED
            elif est.days_left < RUNWAY_WARN_DAYS:
                sev = _SEV_WARN
            else:
                continue
            if est.quality == SPARSE:
                # no CI — a bare day count reads as false precision (B24)
                detail = tr("~{} days left (sparse history — rough estimate)") \
                    .format(int(est.days_left))
            elif est.days_left_low is not None \
                    and est.days_left_high is not None:
                detail = tr("~{}–{} days left").format(
                    int(est.days_left_low), int(est.days_left_high))
            else:
                # ok-quality forecasts always carry a CI; defensive fallback
                detail = tr("~{} days left").format(int(est.days_left))
            key = ("host", est.node, bundle.report.cluster)
            rows.append((self._issue_row(f"{est.storage} ({est.node})",
                tr("Storage filling up"), detail, sev, key, icon="storage"),
                sev))
        return rows

    def _sprawl_rows(self, cluster: str) -> list:
        scan = self._scans.get(cluster)
        if scan is None:
            return []
        rows: list = []
        for row in scan.guests:
            if not row.has_stale:
                continue
            age = _days_ago(row.oldest_time, scan.generated_at)
            if row.zombie_names:
                detail, sev = tr("Unknown snapshot age"), _SEV_RED
                # no timestamp → no age to format ("oldest None days" lies)
                issue = tr("{} snapshots, unknown age").format(row.count)
            else:
                detail = tr("Oldest {} days").format(age)
                sev = _SEV_RED if age > SPRAWL_DANGER_DAYS else _SEV_WARN
                issue = tr("{} snapshots, oldest {} days").format(
                    row.count, age)
            key = (cluster, row.vmid, row.node)
            rows.append((self._issue_row(_vmid_label(row), issue,
                                         detail, sev, key, icon="snapshot"),
                         sev))
        return rows

    def _issue_row(self, obj: str, issue: str, detail: str,
                   sev: int, key, icon: str = "vm") -> QTreeWidgetItem:
        # column 0 empty: the cluster name is already on the parent tree node
        item = QTreeWidgetItem(["", obj, issue, detail])
        item.setIcon(1, get_icon(icon))
        if key is not None:
            item.setData(0, KEY_ROLE, key)
        self._style_row(item, sev)
        return item

    def _style_row(self, item: QTreeWidgetItem, sev: int) -> None:
        if sev == _SEV_RED:
            color = QColor(Color.DANGER)
        elif sev == _SEV_WARN:
            color = QColor(Color.WARNING)
        else:
            return
        item.setForeground(2, color)
        item.setForeground(3, color)

    # ── Navigation ──────────────────────────────────────────────────

    def _activate_item(self, item, _column: int = 0) -> None:
        key = item.data(0, KEY_ROLE)
        if key is None:
            return
        self.object_selected.emit(key)
        self.accept()


def _guest_label(guest) -> str:
    return f"{guest.name or guest.vmid} ({guest.vmid})"


def _vmid_label(row) -> str:
    return f"{row.name or row.vmid} ({row.vmid})"


def _version_label(raw: str) -> str:
    """'pve-manager/8.2.4/1ac2f4b' → '8.2.4' (like _fmt_pveversion)."""
    parts = str(raw).split("/")
    return parts[1] if len(parts) > 1 else str(raw)


def _days_ago(ts: int | None, now: int) -> int | None:
    if ts is None:
        return None
    return int((now - ts) / 86400)


def _fmt_time(ts: int) -> str:
    dt = datetime.fromtimestamp(ts)
    today = datetime.now().date() == dt.date()
    return dt.strftime("%H:%M") if today \
        else dt.strftime("%Y-%m-%d %H:%M")
