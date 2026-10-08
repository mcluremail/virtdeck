from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..detail_panel._constants import _progress_style
from ..detail_panel._table_utils import set_empty_placeholder
from ..hover import enable_row_hover
from ..i18n import tr
from ..icons import get_icon
from ..theme import enable_column_reorder, enable_table_autofit
from .metric_card import MetricCard


class VmPoolWidget(QWidget):
    navigate_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._summary_cards: dict[str, MetricCard] = {}

        summary_layout = QHBoxLayout()
        summary_layout.setContentsMargins(0, 0, 0, 6)
        summary_layout.setSpacing(10)
        for key, title in (
            ("vms", tr("VMs")),
            ("cpu", tr("CPU")),
            ("ram", tr("Memory")),
            ("disk", tr("Disk")),
        ):
            card = MetricCard(title, show_progress=(key in ("cpu", "ram", "disk")))
            summary_layout.addWidget(card)
            self._summary_cards[key] = card
        summary_widget = QWidget()
        summary_widget.setLayout(summary_layout)

        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            tr("Name"), tr("Type"), tr("Disk %"), tr("RAM %"),
            tr("CPU %"), tr("Uptime")
        ])
        enable_table_autofit(self.table, [0, 1, 2, 3, 4], max_width=480)
        # Uptime is a filler column (Interactive + stretchLastSection).
        self.table.horizontalHeader().setStretchLastSection(True)

        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        enable_column_reorder(self.table.horizontalHeader())
        self.table.horizontalHeader().setStyleSheet("QHeaderView::section { padding-left: 4px; }")
        self.table.setAlternatingRowColors(True)
        enable_row_hover(self.table)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(summary_widget)
        layout.addWidget(self.table)

    def set_pool_vms(self, vms):
        if not vms:
            set_empty_placeholder(self.table, 6)
            self._update_summary([])
            return
        self.table.setRowCount(len(vms))
        for i, vm in enumerate(vms):
            name_item = QTableWidgetItem(str(vm.name or ""))
            name_item.setIcon(get_icon("vm", vm.status_value))
            host_name = vm.host_name or ""
            node = vm.node or ""
            vmid = vm.vmid
            if host_name and vmid is not None:
                try:
                    name_item.setData(Qt.UserRole, (host_name, int(vmid), node))
                except (ValueError, TypeError):
                    pass
            self.table.setItem(i, 0, name_item)
            self.table.setItem(i, 1, QTableWidgetItem(vm.vm_type.value))

            maxdisk = vm.maxdisk_bytes or 0
            disk = vm.disk_bytes or 0
            vm_type = vm.vm_type.value
            if vm_type == "lxc" and disk and maxdisk:
                disk_pct = int(max(0, min(100, (disk / maxdisk) * 100)))
                self._set_progress(i, 2, disk_pct)
            elif maxdisk:
                disk_gb = round(maxdisk / (1024**3), 1)
                disk_item = QTableWidgetItem(f"{disk_gb} GiB")
                disk_item.setFlags(Qt.ItemIsEnabled)
                self.table.setItem(i, 2, disk_item)

            maxmem = vm.maxmem_bytes or 0
            mem = vm.mem_bytes or 0
            mem_pct = int(max(0, min(100, (mem / maxmem) * 100))) if maxmem > 0 else 0
            self._set_progress(i, 3, mem_pct)

            cpu_fraction = vm.cpu_fraction or 0
            cpu_pct = int(round(cpu_fraction * 100)) if isinstance(cpu_fraction, (int, float)) else 0
            self._set_progress(i, 4, cpu_pct)

            uptime_sec = vm.uptime_seconds or 0
            uptime_str = self._fmt_uptime(uptime_sec) if uptime_sec else ''
            self.table.setItem(i, 5, QTableWidgetItem(uptime_str))

        self.table.resizeRowsToContents()
        for r in range(self.table.rowCount()):
            if self.table.rowHeight(r) > 24:
                self.table.setRowHeight(r, 24)

        self._update_summary(vms)

    def _update_summary(self, vms):
        total = len(vms)
        running = sum(1 for v in vms if v.status_value == "running")
        self._summary_cards["vms"].set_value(f"{running}/{total}")
        self._summary_cards["vms"].set_subtitle(
            f"{total - running} {tr('stopped')}" if total != running else "")
        self._summary_cards["vms"].set_progress(
            int(running / total * 100) if total else 0)

        cpu_sum = sum(v.cpu_fraction or 0 for v in vms)
        cpu_pct = round(cpu_sum / total * 100, 1) if total else 0
        self._summary_cards["cpu"].set_value(f"{cpu_pct}%")
        self._summary_cards["cpu"].set_progress(cpu_pct)

        mem_total = sum(v.maxmem_bytes or 0 for v in vms)
        mem_used = sum(v.mem_bytes or 0 for v in vms)
        mem_pct = round(mem_used / mem_total * 100, 1) if mem_total else 0
        mem_gb = round(mem_used / (1024**3), 1) if mem_used else 0
        maxmem_gb = round(mem_total / (1024**3), 1) if mem_total else 0
        self._summary_cards["ram"].set_value(f"{mem_gb}/{maxmem_gb} GiB")
        self._summary_cards["ram"].set_progress(mem_pct)

        disk_total = sum(v.maxdisk_bytes or 0 for v in vms)
        disk_used = sum(v.disk_bytes or 0 for v in vms)
        disk_pct = round(disk_used / disk_total * 100, 1) if disk_total else 0
        disk_gb = round(disk_used / (1024**3), 1) if disk_used else 0
        maxdisk_gb = round(disk_total / (1024**3), 1) if disk_total else 0
        self._summary_cards["disk"].set_value(f"{disk_gb}/{maxdisk_gb} GiB")
        self._summary_cards["disk"].set_progress(disk_pct)

    def _set_progress(self, row, col, pct):
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(pct)
        bar.setFormat(f"{pct}%")
        bar.setStyleSheet(_progress_style(pct))
        self.table.setCellWidget(row, col, bar)
        di = QTableWidgetItem("")
        di.setFlags(Qt.ItemIsEnabled)
        self.table.setItem(row, col, di)

    @staticmethod
    def _fmt_uptime(seconds):
        if not seconds or seconds <= 0:
            return ""
        days, rem = divmod(int(seconds), 86400)
        hours, rem = divmod(rem, 3600)
        mins, secs = divmod(rem, 60)
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if mins:
            parts.append(f"{mins}m")
        if secs or not parts:
            parts.append(f"{secs}s")
        return " ".join(parts)

    def _on_cell_double_clicked(self, row, _col):
        item = self.table.item(row, 0)
        if not item:
            return
        key = item.data(Qt.UserRole)
        if isinstance(key, tuple) and len(key) == 3:
            self.navigate_requested.emit(key)
