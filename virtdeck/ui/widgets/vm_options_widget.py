from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from ..detail_panel._table_utils import set_empty_placeholder
from ..hover import enable_row_hover
from ..i18n import tr
from ..theme import Color, enable_column_reorder, enable_table_autofit
from ..vm_config_display import OPT_DEFAULTS, get_editor_spec, get_options_rows
from ..vm_config_editor_dialog import VmConfigEditorDialog
from ..vm_device_editors import VmBootdiskEditorDialog, VmBootEditorDialog, VmStartupEditorDialog

_KEY_ROLE = Qt.UserRole + 100
_READONLY_ROLE = Qt.UserRole + 101
_SECTION_ROLE = Qt.UserRole + 102

_SECTION_BG = "transparent"
_SECTION_FG = f"{Color.TEXT_DIM}"


class VmOptionsWidget(QWidget):
    config_changed = Signal(str, str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config_data = {}
        self._host_name = ""
        self._vmid = 0
        self._node = ""

        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels([tr("Parameter"), tr("Value")])
        enable_table_autofit(self.table, [0])
        # Value is a filler (Interactive + stretchLastSection: resizable by mouse).
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        enable_column_reorder(self.table.horizontalHeader())
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.setStyleSheet(
            f"QTableWidget {{ border: none; background: transparent; }}"
            f"QTableWidget::item {{ padding: 6px 8px; border-bottom: 1px solid {Color.BORDER_LIGHT}; }}"
        )
        enable_row_hover(self.table)
        self.table.cellDoubleClicked.connect(self._on_double_click)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.setContentsMargins(0, 0, 0, 0)

    def set_context(self, host_name, vmid, node):
        self._host_name = host_name
        self._vmid = vmid
        self._node = node

    def set_options_data(self, config_data):
        self._config_data = config_data or {}
        self.table.setRowCount(0)
        rows = get_options_rows(config_data)
        if not rows:
            set_empty_placeholder(self.table, 2)
            return
        for row_data in rows:
            key, label, value, section = row_data
            i = self.table.rowCount()
            self.table.insertRow(i)
            if key == "__section__":
                item = QTableWidgetItem(label.upper())
                item.setData(_SECTION_ROLE, True)
                f = QFont()
                f.setBold(True)
                f.setPointSize(9)
                item.setFont(f)
                item.setForeground(QColor(_SECTION_FG))
                item.setBackground(QColor(_SECTION_BG))
                item.setFlags(item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)
                self.table.setItem(i, 0, item)
                val_item = QTableWidgetItem("")
                val_item.setBackground(QColor(_SECTION_BG))
                val_item.setFlags(Qt.NoItemFlags)
                self.table.setItem(i, 1, val_item)
                self.table.setRowHeight(i, 28)
            else:
                item = QTableWidgetItem(label)
                item.setData(_KEY_ROLE, key)
                self.table.setItem(i, 0, item)
                val_item = QTableWidgetItem(value)
                f = QFont()
                f.setWeight(QFont.DemiBold)
                val_item.setFont(f)
                self.table.setItem(i, 1, val_item)
        self.table.resizeRowsToContents()
        for r in range(self.table.rowCount()):
            if self.table.rowHeight(r) > 28:
                self.table.setRowHeight(r, 28)

    def _on_double_click(self, row, col):
        if not (self._host_name and self._vmid):
            return
        item = self.table.item(row, 0)
        if not item or item.data(_SECTION_ROLE):
            return
        raw_key = item.data(_KEY_ROLE)
        if not raw_key:
            return

        if raw_key == "boot":
            current_value = self._config_data.get(raw_key)
            label = item.text()
            dlg = VmBootEditorDialog(raw_key, label, current_value,
                                     self._config_data, self)
            if dlg.exec() != VmBootEditorDialog.Accepted:
                return
            key, value = dlg.get_raw_value()
            if value is not None:
                self.config_changed.emit(self._host_name, str(self._vmid), {key: value})
            return

        if raw_key == "bootdisk":
            current_value = self._config_data.get(raw_key)
            label = item.text()
            dlg = VmBootdiskEditorDialog(raw_key, label, current_value,
                                         self._config_data, self)
            if dlg.exec() != VmBootdiskEditorDialog.Accepted:
                return
            key, value = dlg.get_raw_value()
            if value is not None:
                self.config_changed.emit(self._host_name, str(self._vmid), {key: value})
            return

        if raw_key == "startup":
            current_value = self._config_data.get(raw_key)
            label = item.text()
            dlg = VmStartupEditorDialog(raw_key, label, current_value, self)
            if dlg.exec() != VmStartupEditorDialog.Accepted:
                return
            key, value = dlg.get_raw_value()
            self.config_changed.emit(self._host_name, str(self._vmid), {key: value})
            return

        ft, choices, choice_labels = get_editor_spec(raw_key)
        if ft == "readonly":
            return
        current_value = self._config_data.get(raw_key)
        if current_value is None:
            current_value = OPT_DEFAULTS.get(raw_key, "")
        label = item.text()
        dlg = VmConfigEditorDialog(raw_key, label, ft, current_value, choices,
                                   choice_labels, self)
        if dlg.exec() != VmConfigEditorDialog.Accepted:
            return
        key, value = dlg.get_raw_value()
        if value is None:
            return
        self.config_changed.emit(self._host_name, str(self._vmid), {key: value})
