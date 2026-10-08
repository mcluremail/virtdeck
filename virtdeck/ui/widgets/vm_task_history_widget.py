from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from ..hover import enable_row_hover
from ..i18n import tr
from ..theme import Color, enable_column_reorder, enable_table_autofit


class VmTaskHistoryWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.table = QTableWidget()
        self.table.verticalHeader().hide()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            tr("Start time"), tr("End time"), tr("Status"),
            tr("User"), tr("Description")
        ])
        enable_table_autofit(self.table, [0, 1, 2, 3])
        # Description is a filler column (Interactive + stretchLastSection).
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.horizontalHeader().setStyleSheet("QHeaderView::section { padding-left: 4px; }")
        enable_column_reorder(self.table.horizontalHeader())

        self.table.setWordWrap(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        enable_row_hover(self.table)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.setContentsMargins(0, 0, 0, 0)

    def set_tasks(self, tasks):
        self.table.setRowCount(len(tasks))
        for i, task in enumerate(tasks):
            start_ts = task.starttime
            if start_ts:
                try:
                    start_dt = datetime.fromtimestamp(float(start_ts))
                    start_str = start_dt.strftime('%Y-%m-%d %H:%M:%S')
                except (ValueError, TypeError):
                    start_str = str(start_ts)
            else:
                start_str = ''
            self.table.setItem(i, 0, QTableWidgetItem(start_str))

            end_ts = task.endtime
            if end_ts:
                try:
                    end_dt = datetime.fromtimestamp(float(end_ts))
                    end_str = end_dt.strftime('%Y-%m-%d %H:%M:%S')
                except (ValueError, TypeError):
                    end_str = str(end_ts)
            else:
                end_str = ''
            end_item = QTableWidgetItem(end_str)
            if not end_str:
                end_item.setForeground(QColor(Color.STATUS_WARN))
                end_item.setText(tr("running..."))
            self.table.setItem(i, 1, end_item)

            status = task.status
            status_item = QTableWidgetItem()
            if status == 'OK':
                status_item.setText("● " + tr("OK"))
                status_item.setForeground(QColor(Color.STATUS_OK))
            elif status == 'RUNNING':
                status_item.setText("● " + tr("running..."))
                status_item.setForeground(QColor(Color.STATUS_WARN))
            else:
                status_item.setText("● " + status)
                status_item.setForeground(QColor(Color.STATUS_ERR))
            self.table.setItem(i, 2, status_item)

            user = task.user
            self.table.setItem(i, 3, QTableWidgetItem(user))

            task_type = task.task_type
            node = task.node or ''
            vmid = task.vmid or ''
            upid = task.upid

            if vmid and node:
                desc = f"{task_type}: VM {vmid} on {node}"
            elif vmid:
                desc = f"{task_type}: VM {vmid}"
            elif node:
                desc = f"{task_type} on {node}"
            elif upid:
                desc = f"{task_type} ({upid})"
            else:
                desc = task_type

            self.table.setItem(i, 4, QTableWidgetItem(desc))

        self.table.resizeRowsToContents()
        for r in range(self.table.rowCount()):
            if self.table.rowHeight(r) > 22:
                self.table.setRowHeight(r, 22)
