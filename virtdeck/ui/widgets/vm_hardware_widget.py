from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..detail_panel._table_utils import set_empty_placeholder
from ..hover import enable_row_hover
from ..i18n import tr
from ..icons import get_icon
from ..theme import Color, enable_column_reorder, enable_table_autofit
from ..vm_config_display import (
    HW_DEFAULTS,
    get_editor_spec,
    get_hardware_rows,
    is_cdrom_key,
    is_disk_key,
    is_net_key,
    is_pci_key,
    is_removable_key,
    is_serial_key,
    is_tpm_key,
    is_usb_key,
)
from ..vm_config_editor_dialog import VmConfigEditorDialog
from ..vm_device_editors import (
    VmAddDiskDialog,
    VmAddEfiDialog,
    VmAddPciDialog,
    VmAddSerialDialog,
    VmAddTpmDialog,
    VmAddUsbDialog,
    VmCdromEditorDialog,
    VmDiskEditorDialog,
    VmNetworkEditorDialog,
    VmRemoveDeviceDialog,
)

_KEY_ROLE = Qt.UserRole + 100
_READONLY_ROLE = Qt.UserRole + 101
_SECTION_ROLE = Qt.UserRole + 102

_SECTION_BG = "transparent"
_SECTION_FG = f"{Color.TEXT_DIM}"

_ADD_TYPES = [
    ("disk", tr("Add: Hard Disk")),
    ("cdrom", tr("Add: CD/DVD Drive")),
    ("net", tr("Add: Network Device")),
    ("usb", tr("Add: USB Device")),
    ("pci", tr("Add: PCI Device")),
    ("serial", tr("Add: Serial Port")),
    ("efidisk", tr("Add: EFI Disk")),
    ("tpmstate", tr("Add: TPM")),
]


def _next_free_slot(config_data, prefix, max_count):
    used = set()
    for k in (config_data or {}):
        pfx = k.rstrip("0123456789")
        if pfx == prefix:
            num_str = k[len(pfx):]
            if num_str.isdigit():
                used.add(int(num_str))
    for i in range(max_count):
        if i not in used:
            return i
    return None


class VmHardwareWidget(QWidget):
    config_changed = Signal(str, str, object)
    remove_device = Signal(str, str, str, object)
    disk_resize = Signal(str, str, str, str)     # host, vmid, disk, size
    disk_move = Signal(str, str, str, str, bool)  # host, vmid, disk, storage, delete

    _EDITABLE_WHEN_RUNNING = ("ide2", "net0", "net1", "net2", "net3")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config_data = {}
        self._host_name = ""
        self._vmid = 0
        self._node = ""
        self._iso_list = []
        self._storage_list = []
        self._vm_status = "stopped"

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
        self.table.currentItemChanged.connect(self._on_selection_changed)

        self._add_btn = QToolButton()
        self._add_btn.setText(tr("Add"))
        self._add_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        add_icon = get_icon("add")
        if add_icon:
            self._add_btn.setIcon(add_icon)
        self._add_menu = QMenu()
        for type_key, type_label in _ADD_TYPES:
            self._add_menu.addAction(type_label, lambda t=type_key: self._on_add_device(t))
        self._add_btn.setMenu(self._add_menu)
        self._add_btn.setPopupMode(QToolButton.InstantPopup)

        self._edit_btn = QPushButton(tr("Edit"))
        self._edit_btn.setEnabled(False)
        self._edit_btn.clicked.connect(self._on_edit_clicked)

        self._remove_btn = QPushButton(tr("Remove"))
        self._remove_btn.setEnabled(False)
        remove_icon = get_icon("remove")
        if remove_icon:
            self._remove_btn.setIcon(remove_icon)
        self._remove_btn.clicked.connect(self._on_remove_clicked)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        toolbar.addWidget(self._add_btn)
        toolbar.addWidget(self._edit_btn)
        toolbar.addWidget(self._remove_btn)
        toolbar.addStretch()

        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(self.table)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

    def set_context(self, host_name, vmid, node):
        self._host_name = host_name
        self._vmid = vmid
        self._node = node

    def set_vm_status(self, status):
        self._vm_status = status or "stopped"

    def set_iso_list(self, iso_set):
        self._iso_list = iso_set

    def set_storage_list(self, storages):
        self._storage_list = storages or []

    def set_hardware_data(self, config_data, detail_data=None):
        self._config_data = config_data or {}
        self.table.setRowCount(0)
        rows = get_hardware_rows(config_data, detail_data)
        if not rows:
            set_empty_placeholder(self.table, 2)
            self._update_buttons(None)
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
                icon = None
                raw_val = self._config_data.get(key)
                if is_disk_key(key, raw_val):
                    icon = get_icon("disk")
                elif is_net_key(key):
                    icon = get_icon("network")
                elif is_cdrom_key(key, raw_val):
                    icon = get_icon("iso")
                elif is_tpm_key(key):
                    icon = get_icon("tpm")
                elif is_usb_key(key):
                    icon = get_icon("usb")
                elif is_pci_key(key):
                    icon = get_icon("pci")
                elif is_serial_key(key):
                    icon = get_icon("serial")
                elif section == "identity":
                    icon = get_icon("vm")
                elif section in ("cpu", "memory"):
                    icon = get_icon("hardware")
                elif section == "system":
                    icon = get_icon("options")
                if icon:
                    item = QTableWidgetItem(icon, label)
                else:
                    item = QTableWidgetItem(label)
                item.setData(_KEY_ROLE, key)
                ft, _, _ = get_editor_spec(key)
                if ft == "readonly":
                    item.setData(_READONLY_ROLE, True)
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
        self._update_buttons(self.table.currentItem())

    def _on_selection_changed(self, current, _previous):
        self._update_buttons(current)

    def _update_buttons(self, item):
        if not item:
            self._edit_btn.setEnabled(False)
            self._remove_btn.setEnabled(False)
            self._edit_btn.setToolTip("")
            self._remove_btn.setToolTip("")
            return
        key = item.data(_KEY_ROLE)
        if not key or item.data(_SECTION_ROLE):
            self._edit_btn.setEnabled(False)
            self._remove_btn.setEnabled(False)
            self._edit_btn.setToolTip("")
            self._remove_btn.setToolTip("")
            return
        raw_val = self._config_data.get(key)
        is_running = self._vm_status == "running"
        can_edit = not item.data(_READONLY_ROLE)
        if can_edit and is_running and key not in self._EDITABLE_WHEN_RUNNING \
                and not is_cdrom_key(key, raw_val):
            can_edit = False
            self._edit_btn.setToolTip(tr("Stop the VM to edit"))
        else:
            self._edit_btn.setToolTip("")
        self._edit_btn.setEnabled(can_edit)
        can_remove = is_removable_key(key, raw_val)
        if can_remove and is_running and key not in self._EDITABLE_WHEN_RUNNING \
                and not is_cdrom_key(key, raw_val):
            hotplug = str(self._config_data.get("hotplug", ""))
            if not self._is_hotplug_allowed(key, raw_val, hotplug):
                can_remove = False
                self._remove_btn.setToolTip(tr("Stop the VM to remove"))
            else:
                self._remove_btn.setToolTip("")
        else:
            self._remove_btn.setToolTip("")
        self._remove_btn.setEnabled(can_remove)

    def _is_hotplug_allowed(self, key, value, hotplug_str):
        if hotplug_str in ("1", "all"):
            return True
        if hotplug_str == "0" or not hotplug_str:
            return False
        parts = set(hotplug_str.split(","))
        if is_net_key(key) and "network" in parts:
            return True
        if is_disk_key(key, value) and "disk" in parts:
            return True
        if is_usb_key(key) and "usb" in parts:
            return True
        return False

    def _on_edit_clicked(self):
        item = self.table.currentItem()
        if not item:
            return
        row = self.table.currentRow()
        if row >= 0:
            self._on_double_click(row, 0)

    def _on_add_device(self, type_key):
        if not (self._host_name and self._vmid):
            return
        is_running = self._vm_status == "running"
        if is_running and type_key not in ("cdrom",):
            hotplug = str(self._config_data.get("hotplug", ""))
            allow = False
            if hotplug in ("1", "all"):
                allow = True
            elif hotplug and hotplug != "0":
                parts = set(hotplug.split(","))
                if type_key == "net" and "network" in parts:
                    allow = True
                elif type_key == "disk" and "disk" in parts:
                    allow = True
                elif type_key == "usb" and "usb" in parts:
                    allow = True
            if not allow:
                QMessageBox.information(self, tr("Cannot add on a running VM"),
                                        tr("Stop the VM to add devices"))
                return

        if type_key == "disk":
            bus_prefixes = [("scsi", 31), ("virtio", 16), ("sata", 6), ("ide", 4)]
            for prefix, max_n in bus_prefixes:
                slot = _next_free_slot(self._config_data, prefix, max_n)
                if slot is not None:
                    break
            else:
                QMessageBox.warning(self, tr("No free slots"), tr("No free slots for {type}").format(type="disk"))
                return
            key = f"{prefix}{slot}"
            dlg = VmAddDiskDialog(key, self._storage_list, self)
            if dlg.exec() != QDialog.Accepted:
                return
            _, value = dlg.get_raw_value()
            self.config_changed.emit(self._host_name, str(self._vmid), {key: value})
            return

        if type_key == "cdrom":
            slot = _next_free_slot(self._config_data, "ide", 4)
            if slot is None or slot == 2:
                slot = _next_free_slot(self._config_data, "sata", 6)
                if slot is not None:
                    key = f"sata{slot}"
                else:
                    QMessageBox.warning(self, tr("No free slots"), tr("No free slots for CD/DVD"))
                    return
            else:
                key = f"ide{slot}"
            dlg = VmCdromEditorDialog(key, tr("Optical drive"), "none", self._iso_list, self)
            if dlg.exec() != QDialog.Accepted:
                return
            _, value = dlg.get_raw_value()
            if value is None:
                self.config_changed.emit(self._host_name, str(self._vmid), {key: "none"})
            else:
                self.config_changed.emit(self._host_name, str(self._vmid), {key: value})
            return

        if type_key == "net":
            slot = _next_free_slot(self._config_data, "net", 32)
            if slot is None:
                QMessageBox.warning(self, tr("No free slots"), tr("No free slots for {type}").format(type="net"))
                return
            key = f"net{slot}"
            dlg = VmNetworkEditorDialog(key, tr("Network"), "", running=is_running, parent=self)
            if dlg.exec() != QDialog.Accepted:
                return
            _, value = dlg.get_raw_value()
            self.config_changed.emit(self._host_name, str(self._vmid), {key: value})
            return

        if type_key == "usb":
            slot = _next_free_slot(self._config_data, "usb", 5)
            if slot is None:
                QMessageBox.warning(self, tr("No free slots"), tr("No free slots for {type}").format(type="usb"))
                return
            key = f"usb{slot}"
            dlg = VmAddUsbDialog(key, self)
            if dlg.exec() != QDialog.Accepted:
                return
            _, value = dlg.get_raw_value()
            self.config_changed.emit(self._host_name, str(self._vmid), {key: value})
            return

        if type_key == "pci":
            slot = _next_free_slot(self._config_data, "hostpci", 16)
            if slot is None:
                QMessageBox.warning(self, tr("No free slots"), tr("No free slots for {type}").format(type="pci"))
                return
            key = f"hostpci{slot}"
            dlg = VmAddPciDialog(key, self)
            if dlg.exec() != QDialog.Accepted:
                return
            _, value = dlg.get_raw_value()
            self.config_changed.emit(self._host_name, str(self._vmid), {key: value})
            return

        if type_key == "serial":
            slot = _next_free_slot(self._config_data, "serial", 4)
            if slot is None:
                QMessageBox.warning(self, tr("No free slots"), tr("No free slots for {type}").format(type="serial"))
                return
            key = f"serial{slot}"
            dlg = VmAddSerialDialog(key, self)
            if dlg.exec() != QDialog.Accepted:
                return
            _, value = dlg.get_raw_value()
            self.config_changed.emit(self._host_name, str(self._vmid), {key: value})
            return

        if type_key == "efidisk":
            slot = _next_free_slot(self._config_data, "efidisk", 1)
            if slot is None:
                QMessageBox.warning(self, tr("No free slots"), tr("No free slots for {type}").format(type="efidisk"))
                return
            key = f"efidisk{slot}"
            dlg = VmAddEfiDialog(key, self._storage_list, self)
            if dlg.exec() != QDialog.Accepted:
                return
            _, value = dlg.get_raw_value()
            self.config_changed.emit(self._host_name, str(self._vmid), {key: value})
            return

        if type_key == "tpmstate":
            slot = _next_free_slot(self._config_data, "tpmstate", 1)
            if slot is None:
                QMessageBox.warning(self, tr("No free slots"), tr("No free slots for {type}").format(type="tpmstate"))
                return
            key = f"tpmstate{slot}"
            dlg = VmAddTpmDialog(key, self._storage_list, self)
            if dlg.exec() != QDialog.Accepted:
                return
            _, value = dlg.get_raw_value()
            self.config_changed.emit(self._host_name, str(self._vmid), {key: value})
            return

    def _on_remove_clicked(self):
        item = self.table.currentItem()
        if not item:
            return
        key = item.data(_KEY_ROLE)
        if not key or not is_removable_key(key, self._config_data.get(key)):
            return
        label = item.text()
        raw_val = self._config_data.get(key)
        is_disk = is_disk_key(key, raw_val)

        dlg = VmRemoveDeviceDialog(key, label, is_disk, self)
        if dlg.exec() != QDialog.Accepted:
            return

        destroy = dlg.destroy if is_disk else False
        if destroy and raw_val:
            self.remove_device.emit(self._host_name, str(self._vmid), key, raw_val)
        else:
            self.config_changed.emit(self._host_name, str(self._vmid), {"delete": key})

    def _on_double_click(self, row, col):
        if not (self._host_name and self._vmid):
            return
        item = self.table.item(row, 0)
        if not item or item.data(_READONLY_ROLE) or item.data(_SECTION_ROLE):
            return
        raw_key = item.data(_KEY_ROLE)
        if not raw_key:
            return

        is_running = self._vm_status == "running"
        current_value = self._config_data.get(raw_key)
        if is_running and raw_key not in self._EDITABLE_WHEN_RUNNING \
                and not is_cdrom_key(raw_key, current_value):
            QMessageBox.information(self, tr("Cannot be changed on a running VM"),
                                    tr("Stop the VM to edit"))
            return

        label = item.text()

        if is_net_key(raw_key):
            dlg = VmNetworkEditorDialog(raw_key, label, current_value,
                                        running=is_running, parent=self)
            if dlg.exec() != VmNetworkEditorDialog.Accepted:
                return
            key, value = dlg.get_raw_value()
            if value is not None:
                self.config_changed.emit(self._host_name, str(self._vmid), {key: value})
            return

        if is_cdrom_key(raw_key, current_value):
            dlg = VmCdromEditorDialog(raw_key, label, current_value,
                                      self._iso_list, self)
            if dlg.exec() != VmCdromEditorDialog.Accepted:
                return
            key, value = dlg.get_raw_value()
            if value is None:
                self.config_changed.emit(self._host_name, str(self._vmid),
                                         {key: "none"})
            else:
                self.config_changed.emit(self._host_name, str(self._vmid),
                                         {key: value})
            return

        if is_disk_key(raw_key, current_value):
            # Rebuild raw value for the disk editor
            raw_str = str(current_value) if current_value is not None else ""
            dlg = VmDiskEditorDialog(raw_key, label, raw_str, self._storage_list, self)
            result = dlg.exec()
            if result == VmDiskEditorDialog.RESIZE_RESULT:
                params = dlg.get_resize_params()
                if params:
                    disk, size = params
                    self.disk_resize.emit(self._host_name, str(self._vmid), disk, size)
                return
            if result == VmDiskEditorDialog.MOVE_RESULT:
                params = dlg.get_move_params()
                if params:
                    disk, storage, delete = params
                    self.disk_move.emit(self._host_name, str(self._vmid), disk, storage, delete)
                return
            if result != VmDiskEditorDialog.Accepted:
                return
            key, value = dlg.get_raw_value()
            if value is not None:
                self.config_changed.emit(self._host_name, str(self._vmid), {key: value})
            return

        ft, choices, choice_labels = get_editor_spec(raw_key)
        if ft == "readonly":
            return
        if current_value is None:
            current_value = HW_DEFAULTS.get(raw_key, "")
        dlg = VmConfigEditorDialog(raw_key, label, ft, current_value, choices,
                                   choice_labels, self)
        if dlg.exec() != VmConfigEditorDialog.Accepted:
            return
        key, value = dlg.get_raw_value()
        if value is None:
            return
        self.config_changed.emit(self._host_name, str(self._vmid), {key: value})
