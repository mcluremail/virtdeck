import re

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from .i18n import tr
from .theme import Color

NET_MODELS = ["virtio", "e1000", "rtl8139", "vmxnet3"]

DISK_CACHE = [
    ("none", tr("None")),
    ("writeback", tr("Write back")),
    ("writethrough", tr("Write through")),
    ("directsync", tr("Direct sync")),
    ("unsafe", tr("Unsafe")),
]


def _parse_net(val):
    """Parse netX string -> dict of components."""
    if not val or str(val).strip() in ("", "None"):
        return {"model": "virtio", "mac": "", "bridge": "vmbr0", "tag": "", "queues": "", "extra": []}
    val = str(val)
    parts = val.split(",")
    result = {"model": "virtio", "mac": "", "bridge": "vmbr0", "tag": "", "queues": "", "extra": []}
    first = parts[0]
    if "=" in first:
        result["model"], result["mac"] = first.split("=", 1)
    else:
        result["model"] = first
    for p in parts[1:]:
        if p.startswith("bridge="):
            result["bridge"] = p.split("=", 1)[1]
        elif p.startswith("tag="):
            result["tag"] = p.split("=", 1)[1]
        elif p.startswith("queues="):
            result["queues"] = p.split("=", 1)[1]
        else:
            # Preserve options the editor has no field for (firewall=1,
            # link_down=1, rate=..., mtu=..., trunks=...) so saving the
            # dialog doesn't silently strip them.
            result["extra"].append(p)
    return result


def _build_net(model, mac, bridge, tag, queues, extra=()):
    parts = [f"{model}={mac}" if mac else model]
    if bridge:
        parts.append(f"bridge={bridge}")
    if tag:
        parts.append(f"tag={tag}")
    if queues:
        parts.append(f"queues={queues}")
    parts.extend(extra)
    return ",".join(parts)


def _parse_disk(val):
    if not val or str(val).strip() in ("", "None"):
        return {"storage": "", "volume": "", "size": "", "format": "", "cache": "none", "extra": []}
    parts = str(val).split(",")
    result = {"storage": "", "volume": "", "size": "", "format": "", "cache": "none", "extra": []}
    first = parts[0]
    if ":" in first:
        result["storage"] = first.split(":")[0]
        result["volume"] = first.split(":", 1)[1]
    for p in parts[1:]:
        if p.startswith("cache="):
            result["cache"] = p.split("=", 1)[1]
        elif p.startswith("format="):
            result["format"] = p.split("=", 1)[1]
        elif p.startswith("size="):
            result["size"] = p.split("=", 1)[1]
        else:
            result["extra"].append(p)
    return result


def _parse_cdrom(val):
    """Parse ide2/sata cdrom string -> dict."""
    result = {"type": "none", "volid": ""}
    if not val or str(val).strip() == "none":
        return result
    if val == "/dev/cdrom,media=cdrom":
        result["type"] = "physical"
        return result
    parts = str(val).split(",")
    result["volid"] = parts[0]
    result["type"] = "iso"
    return result


class VmNetworkEditorDialog(QDialog):
    def __init__(self, key, label, current_value, running=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Edit: ") + label)
        self.setMinimumWidth(500)
        self._key = key
        self._parsed = _parse_net(current_value)
        self._running = running

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"<b>{label}</b>")
        layout.addWidget(header)

        if running:
            warn = QLabel(tr("On a running VM only the VLAN tag can be changed"))
            warn.setStyleSheet(f"color: {Color.WARNING}; font-size: 11px;")
            warn.setWordWrap(True)
            layout.addWidget(warn)

        form = QFormLayout()
        form.setSpacing(8)

        self._model_combo = QComboBox()
        for m in NET_MODELS:
            self._model_combo.addItem(m, m)
        idx = self._model_combo.findData(self._parsed["model"])
        if idx >= 0:
            self._model_combo.setCurrentIndex(idx)
        self._model_combo.setEnabled(not running)
        form.addRow(tr("Model:"), self._model_combo)

        self._mac_edit = QLineEdit(self._parsed["mac"])
        self._mac_edit.setPlaceholderText(tr("leave empty for auto-assign"))
        self._mac_edit.setReadOnly(True)
        form.addRow(tr("MAC:"), self._mac_edit)

        self._bridge_combo = QComboBox()
        self._bridge_combo.setEditable(True)
        default_bridges = ["vmbr0", "vmbr1", "vmbr2", "vmbr3", "vmbr99"]
        for b in default_bridges:
            self._bridge_combo.addItem(b, b)
        bridge_val = self._parsed["bridge"]
        idx = self._bridge_combo.findData(bridge_val)
        if idx >= 0:
            self._bridge_combo.setCurrentIndex(idx)
        else:
            self._bridge_combo.setEditText(bridge_val)
        self._bridge_combo.setEnabled(not running)
        form.addRow(tr("Bridge:"), self._bridge_combo)

        self._vlan_spin = QSpinBox()
        self._vlan_spin.setRange(0, 4094)
        self._vlan_spin.setSpecialValueText(tr("None"))
        try:
            self._vlan_spin.setValue(int(self._parsed["tag"]) if self._parsed["tag"] else 0)
        except ValueError:
            self._vlan_spin.setValue(0)
        form.addRow(tr("VLAN tag:"), self._vlan_spin)

        self._queues_spin = QSpinBox()
        self._queues_spin.setRange(0, 64)
        self._queues_spin.setSpecialValueText(tr("Auto"))
        try:
            self._queues_spin.setValue(int(self._parsed["queues"]) if self._parsed["queues"] else 0)
        except ValueError:
            self._queues_spin.setValue(0)
        form.addRow(tr("Queues:"), self._queues_spin)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._ok_btn = QPushButton(tr("Save"))
        self._ok_btn.setObjectName("accentBtn")
        self._ok_btn.setMinimumWidth(120)
        self._ok_btn.clicked.connect(self._on_ok)
        btn_layout.addWidget(self._ok_btn)
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.setMinimumWidth(120)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _on_ok(self):
        self.accept()

    def get_raw_value(self):
        model = self._model_combo.currentData()
        mac = self._mac_edit.text().strip()
        bridge = self._bridge_combo.currentText().strip()
        tag = self._vlan_spin.value()
        queues = self._queues_spin.value()
        net_val = _build_net(model, mac, bridge,
                             str(tag) if tag > 0 else "",
                             str(queues) if queues > 0 else "",
                             extra=self._parsed.get("extra", []))
        return (self._key, net_val)


class VmCdromEditorDialog(QDialog):
    """CDROM editor (ide2 or any sata/ide with media=cdrom)."""
    def __init__(self, key, label, current_value, iso_list=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Edit: ") + label)
        self.setMinimumWidth(500)
        self._key = key
        self._parsed = _parse_cdrom(current_value)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"<b>{label} — {tr('Optical drive')}</b>")
        layout.addWidget(header)

        current_label = QLabel()
        if self._parsed["type"] == "physical":
            current_label.setText(tr("Current:") + f" <b>{tr('Physical drive')}</b>")
        elif self._parsed["type"] == "iso":
            current_label.setText(tr("Current:") + f" <b>{self._parsed['volid']}</b>")
        else:
            current_label.setText(tr("Current:") + f" <b>{tr('No media')}</b>")
        layout.addWidget(current_label)

        form = QFormLayout()
        form.setSpacing(8)

        self._iso_combo = QComboBox()
        self._iso_combo.setEditable(True)
        self._iso_combo.addItem(tr("No media —"), "__none__")
        self._iso_combo.addItem(tr("Physical drive (CD/DVD)"), "__cdrom__")
        if iso_list:
            for volid in iso_list:
                fname = volid.split("/")[-1] if "/" in volid else volid
                self._iso_combo.addItem(f"{fname}  ({volid})", volid)
        if self._parsed["volid"]:
            idx = self._iso_combo.findData(self._parsed["volid"])
            if idx >= 0:
                self._iso_combo.setCurrentIndex(idx)
            else:
                self._iso_combo.addItem(str(self._parsed["volid"]), self._parsed["volid"])
                self._iso_combo.setCurrentIndex(self._iso_combo.count() - 1)
        form.addRow(tr("Select ISO:"), self._iso_combo)

        layout.addLayout(form)

        info = QLabel(tr("ISO images are loaded from node storage"))
        info.setStyleSheet(f"color: {Color.TEXT_SEC}; font-size: 11px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        btn_layout = QHBoxLayout()
        eject_btn = QPushButton(tr("Eject"))
        eject_btn.clicked.connect(self._on_eject)
        btn_layout.addWidget(eject_btn)
        btn_layout.addStretch()
        self._ok_btn = QPushButton(tr("Save"))
        self._ok_btn.setObjectName("accentBtn")
        self._ok_btn.setMinimumWidth(120)
        self._ok_btn.clicked.connect(self._on_ok)
        btn_layout.addWidget(self._ok_btn)
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.setMinimumWidth(120)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _on_eject(self):
        self._iso_combo.setCurrentIndex(0)

    def _on_ok(self):
        self.accept()

    def get_raw_value(self):
        data = self._iso_combo.currentData()
        if data == "__none__":
            return (self._key, None)
        elif data == "__cdrom__":
            return (self._key, "/dev/cdrom,media=cdrom")
        elif data:
            return (self._key, f"{data},media=cdrom")
        return (self._key, None)


class VmDiskEditorDialog(QDialog):
    """Disk parameter editor (virtio0, scsi0, ...)."""

    RESIZE_RESULT = 10
    MOVE_RESULT = 11

    def __init__(self, key, label, current_value, storages=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Edit: ") + label)
        self.setMinimumWidth(450)
        self._key = key
        self._parsed = _parse_disk(current_value)
        self._storages = storages or []
        self._resize_params = None
        self._move_params = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"<b>{label}</b>")
        layout.addWidget(header)

        form = QFormLayout()
        form.setSpacing(8)

        storage_edit = QLineEdit(self._parsed["storage"])
        storage_edit.setReadOnly(True)
        form.addRow(tr("Storage:"), storage_edit)

        if self._parsed["volume"]:
            volume_edit = QLineEdit(self._parsed["volume"])
            volume_edit.setReadOnly(True)
            form.addRow(tr("Volume:"), volume_edit)

        size_edit = QLineEdit(self._parsed["size"])
        size_edit.setReadOnly(True)
        form.addRow(tr("Size:"), size_edit)

        fmt_edit = QLineEdit(self._parsed["format"])
        fmt_edit.setReadOnly(True)
        if not self._parsed["format"]:
            fmt_edit.setPlaceholderText("qcow2 (default)")
        form.addRow(tr("Format:"), fmt_edit)

        self._cache_combo = QComboBox()
        for val, label_text in DISK_CACHE:
            self._cache_combo.addItem(label_text, val)
        idx = self._cache_combo.findData(self._parsed["cache"])
        if idx >= 0:
            self._cache_combo.setCurrentIndex(idx)
        form.addRow(tr("Cache:"), self._cache_combo)

        layout.addLayout(form)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        resize_btn = QPushButton(tr("Resize Disk"))
        resize_btn.clicked.connect(self._on_resize)
        action_row.addWidget(resize_btn)
        move_btn = QPushButton(tr("Move Disk"))
        move_btn.clicked.connect(self._on_move)
        action_row.addWidget(move_btn)
        action_row.addStretch()
        layout.addLayout(action_row)

        info = QLabel(tr("Cache can be changed here. Use Resize or Move for size/storage."))
        info.setStyleSheet(f"color: {Color.TEXT_SEC}; font-size: 11px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._ok_btn = QPushButton(tr("Save"))
        self._ok_btn.setObjectName("accentBtn")
        self._ok_btn.setMinimumWidth(120)
        self._ok_btn.clicked.connect(self._on_ok)
        btn_layout.addWidget(self._ok_btn)
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.setMinimumWidth(120)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _on_resize(self):
        raw_val = self._parsed.get("storage", "") + ":" + self._parsed.get("volume", "")
        if self._parsed.get("size"):
            raw_val += f",size={self._parsed['size']}"
        dlg = VmDiskResizeDialog(self._key, self._key, raw_val, self)
        if dlg.exec() == VmDiskResizeDialog.Accepted:
            self._resize_params = dlg.get_resize_params()
            self.done(self.RESIZE_RESULT)

    def _on_move(self):
        raw_val = self._parsed.get("storage", "") + ":" + self._parsed.get("volume", "")
        dlg = VmDiskMoveDialog(self._key, self._key, raw_val, self._storages, self)
        if dlg.exec() == VmDiskMoveDialog.Accepted:
            self._move_params = dlg.get_move_params()
            self.done(self.MOVE_RESULT)

    def get_resize_params(self):
        return self._resize_params

    def get_move_params(self):
        return self._move_params

    def _on_ok(self):
        self.accept()

    def get_raw_value(self):
        cache = self._cache_combo.currentData()
        if cache == self._parsed["cache"]:
            return (self._key, None)
        new_val = f"{self._parsed['storage']}:{self._parsed['size']}"
        parts = []
        if self._parsed["format"]:
            parts.append(f"format={self._parsed['format']}")
        if cache and cache != "none":
            parts.append(f"cache={cache}")
        parts.extend(self._parsed.get("extra", []))
        if parts:
            new_val += "," + ",".join(parts)
        return (self._key, new_val)


class VmDiskResizeDialog(QDialog):
    """Resize a VM disk — grow only, shrink requires VM stop + special flags."""

    def __init__(self, key, label, current_value, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Resize Disk"))
        self.setMinimumWidth(450)
        self._key = key
        self._parsed = _parse_disk(current_value)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"<b>{label}</b>")
        layout.addWidget(header)

        form = QFormLayout()
        form.setSpacing(8)

        storage_edit = QLineEdit(self._parsed["storage"])
        storage_edit.setReadOnly(True)
        form.addRow(tr("Storage:"), storage_edit)

        cur_size = self._parsed["size"]
        size_edit = QLineEdit(cur_size)
        size_edit.setReadOnly(True)
        form.addRow(tr("Current size:"), size_edit)

        self._add_spin = QSpinBox()
        self._add_spin.setRange(1, 1048576)
        self._add_spin.setValue(10)
        self._add_spin.setSuffix(" GB")
        form.addRow(tr("Add space:"), self._add_spin)

        layout.addLayout(form)

        info = QLabel(tr("Disk can only be enlarged. To shrink, stop the VM and use the PVE CLI."))
        info.setStyleSheet(f"color: {Color.TEXT_SEC}; font-size: 11px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton(tr("Resize"))
        ok_btn.setObjectName("accentBtn")
        ok_btn.setMinimumWidth(120)
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.setMinimumWidth(120)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def get_resize_params(self):
        gb = self._add_spin.value()
        return (self._key, f"+{gb}G")


class VmDiskMoveDialog(QDialog):
    """Move a VM disk to another storage."""

    def __init__(self, key, label, current_value, storages, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Move Disk"))
        self.setMinimumWidth(450)
        self._key = key
        self._parsed = _parse_disk(current_value)
        self._storages = storages or []

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"<b>{label}</b>")
        layout.addWidget(header)

        form = QFormLayout()
        form.setSpacing(8)

        cur_storage = QLineEdit(self._parsed["storage"])
        cur_storage.setReadOnly(True)
        form.addRow(tr("Current storage:"), cur_storage)

        self._storage_combo = QComboBox()
        for s in self._storages:
            name = s.storage or ""
            if name and name != self._parsed["storage"]:
                self._storage_combo.addItem(name, name)
        form.addRow(tr("Target storage:"), self._storage_combo)

        self._delete_check = QCheckBox(tr("Delete source disk after move"))
        self._delete_check.setChecked(True)
        form.addRow("", self._delete_check)

        layout.addLayout(form)

        if self._storage_combo.count() == 0:
            warn = QLabel(tr("No other storage available on this node."))
            warn.setStyleSheet(f"color: {Color.TEXT_SEC}; font-size: 11px;")
            warn.setWordWrap(True)
            layout.addWidget(warn)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._ok_btn = QPushButton(tr("Move"))
        self._ok_btn.setObjectName("accentBtn")
        self._ok_btn.setMinimumWidth(120)
        self._ok_btn.clicked.connect(self._on_ok)
        btn_layout.addWidget(self._ok_btn)
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.setMinimumWidth(120)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        if self._storage_combo.count() == 0:
            self._ok_btn.setEnabled(False)

    def _on_ok(self):
        if not self._storage_combo.currentData():
            return
        self.accept()

    def get_move_params(self):
        return (
            self._key,
            self._storage_combo.currentData(),
            self._delete_check.isChecked(),
        )


class VmBootEditorDialog(QDialog):
    # Bootable device keys look like "ide2"/"scsi0"/"net0"; a plain
    # startswith match would also catch config keys like "scsihw".
    _DEVICE_RE = re.compile(r"(ide|sata|scsi|virtio|net)\d+$")

    def __init__(self, key, label, current_value, config_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Edit: ") + label)
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
        self._key = key
        self._config_data = config_data or {}

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"<b>{label}</b>")
        layout.addWidget(header)

        info = QLabel(tr("Move devices between available and boot order"))
        info.setStyleSheet(f"color: {Color.TEXT_SEC}; font-size: 11px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        avail_label = QLabel(tr("Available devices:"))
        avail_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(avail_label)
        self._avail = QListWidget()
        self._avail.itemDoubleClicked.connect(self._to_order)
        layout.addWidget(self._avail)

        move_row = QHBoxLayout()
        to_order_btn = QPushButton(">")
        to_order_btn.setFixedWidth(40)
        to_order_btn.clicked.connect(self._add_selected)
        move_row.addWidget(to_order_btn)
        to_avail_btn = QPushButton("<")
        to_avail_btn.setFixedWidth(40)
        to_avail_btn.clicked.connect(self._remove_selected)
        move_row.addWidget(to_avail_btn)
        move_row.addStretch()
        layout.addLayout(move_row)

        order_label = QLabel(tr("Boot order:"))
        order_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(order_label)
        self._order = QListWidget()
        self._order.itemDoubleClicked.connect(self._to_avail)
        layout.addWidget(self._order)

        order_btn_row = QHBoxLayout()
        up_btn = QPushButton(tr("Up"))
        up_btn.setMinimumWidth(80)
        up_btn.clicked.connect(self._move_up)
        order_btn_row.addWidget(up_btn)
        down_btn = QPushButton(tr("Down"))
        down_btn.setMinimumWidth(80)
        down_btn.clicked.connect(self._move_down)
        order_btn_row.addWidget(down_btn)
        order_btn_row.addStretch()
        layout.addLayout(order_btn_row)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton(tr("Save"))
        ok_btn.setObjectName("accentBtn")
        ok_btn.setMinimumWidth(120)
        ok_btn.clicked.connect(self._on_ok)
        btn_layout.addWidget(ok_btn)
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.setMinimumWidth(120)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        self._fill(current_value)

    def _collect_devices(self):
        devices = set()
        for key in (self._config_data or {}):
            if self._DEVICE_RE.fullmatch(key):
                devices.add(key)
        return sorted(devices)

    def _fill(self, val):
        raw = str(val or "")
        if raw.startswith("order="):
            order_parts = [p.strip() for p in raw[6:].split(";") if p.strip()]
        elif raw:
            order_parts = [p.strip() for p in raw.split(";") if p.strip()]
        else:
            order_parts = []
        order_set = set(order_parts)
        for d in order_parts:
            self._order.addItem(QListWidgetItem(d))
        for d in self._collect_devices():
            if d not in order_set:
                self._avail.addItem(QListWidgetItem(d))

    def _add_selected(self):
        item = self._avail.currentItem()
        if item:
            self._to_order(item)

    def _remove_selected(self):
        item = self._order.currentItem()
        if item:
            self._to_avail(item)

    def _to_order(self, item):
        self._order.addItem(QListWidgetItem(item.text()))
        self._avail.takeItem(self._avail.row(item))

    def _to_avail(self, item):
        self._avail.addItem(QListWidgetItem(item.text()))
        self._order.takeItem(self._order.row(item))

    def _move_up(self):
        r = self._order.currentRow()
        if r > 0:
            it = self._order.takeItem(r)
            self._order.insertItem(r - 1, it)
            self._order.setCurrentRow(r - 1)

    def _move_down(self):
        r = self._order.currentRow()
        if r >= 0 and r < self._order.count() - 1:
            it = self._order.takeItem(r)
            self._order.insertItem(r + 1, it)
            self._order.setCurrentRow(r + 1)

    def _on_ok(self):
        if self._order.count() == 0:
            msg = QMessageBox(QMessageBox.Question, tr("Empty boot order"),
                              tr("Empty boot order — VM may not boot") + "\n" + tr("Continue?"),
                              parent=self)
            yes = msg.addButton(tr("Yes"), QMessageBox.YesRole)
            msg.addButton(tr("No"), QMessageBox.NoRole)
            msg.setDefaultButton(yes)
            msg.exec()
            if msg.clickedButton() != yes:
                return
        self.accept()

    def get_raw_value(self):
        parts = [self._order.item(i).text() for i in range(self._order.count())]
        return (self._key, f"order={';'.join(parts)}")


class VmBootdiskEditorDialog(QDialog):
    _DEVICE_TYPES = ("ide", "sata", "scsi", "virtio", "net", "efidisk")

    def __init__(self, key, label, current_value, config_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Edit: ") + label)
        self.setMinimumWidth(400)
        self._key = key

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"<b>{label} — {tr('Boot Disk')}</b>")
        layout.addWidget(header)

        devices = set()
        for k in (config_data or {}):
            for pfx in self._DEVICE_TYPES:
                if k.startswith(pfx):
                    devices.add(k)

        self._combo = QComboBox()
        self._combo.addItem(tr("— none —"), "")
        for d in sorted(devices):
            self._combo.addItem(d, d)
        idx = self._combo.findData(str(current_value or ""))
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
        else:
            self._combo.setEditText(str(current_value or ""))
        form = QFormLayout()
        form.addRow(tr("Device:"), self._combo)
        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton(tr("Save"))
        ok_btn.setObjectName("accentBtn")
        ok_btn.setMinimumWidth(120)
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.setMinimumWidth(120)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def get_raw_value(self):
        val = self._combo.currentData()
        return (self._key, val if val else None)


class VmStartupEditorDialog(QDialog):
    def __init__(self, key, label, current_value, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Edit: ") + label)
        self.setMinimumWidth(400)
        self._key = key

        parsed = {"order": "", "up": "", "down": ""}
        if current_value:
            for part in str(current_value).split(","):
                if "=" in part:
                    k, v = part.split("=", 1)
                    parsed[k] = v

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"<b>{label} — {tr('Startup order and delays')}</b>")
        layout.addWidget(header)

        form = QFormLayout()

        self._order_spin = QSpinBox()
        self._order_spin.setRange(0, 9999)
        self._order_spin.setSpecialValueText(tr("Not set"))
        try:
            self._order_spin.setValue(int(parsed.get("order", 0) or 0))
        except ValueError:
            self._order_spin.setValue(0)
        form.addRow(tr("Order:"), self._order_spin)

        self._up_spin = QSpinBox()
        self._up_spin.setRange(0, 99999)
        self._up_spin.setSuffix(" " + tr("sec"))
        self._up_spin.setSpecialValueText(tr("Not set"))
        try:
            self._up_spin.setValue(int(parsed.get("up", 0) or 0))
        except ValueError:
            self._up_spin.setValue(0)
        form.addRow(tr("Start delay:"), self._up_spin)

        self._down_spin = QSpinBox()
        self._down_spin.setRange(0, 99999)
        self._down_spin.setSuffix(" " + tr("sec"))
        self._down_spin.setSpecialValueText(tr("Not set"))
        try:
            self._down_spin.setValue(int(parsed.get("down", 0) or 0))
        except ValueError:
            self._down_spin.setValue(0)
        form.addRow(tr("Stop delay:"), self._down_spin)

        layout.addLayout(form)

        info = QLabel(tr("Lower number starts earlier"))
        info.setStyleSheet(f"color: {Color.TEXT_SEC}; font-size: 11px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton(tr("Save"))
        ok_btn.setObjectName("accentBtn")
        ok_btn.setMinimumWidth(120)
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.setMinimumWidth(120)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def get_raw_value(self):
        parts = []
        if self._order_spin.value() > 0:
            parts.append(f"order={self._order_spin.value()}")
        if self._up_spin.value() > 0:
            parts.append(f"up={self._up_spin.value()}")
        if self._down_spin.value() > 0:
            parts.append(f"down={self._down_spin.value()}")
        return (self._key, ",".join(parts) if parts else None)


# ---------------------------------------------------------------------------
# Add device dialogs
# ---------------------------------------------------------------------------

DISK_BUSES = [
    ("scsi", tr("SCSI")),
    ("virtio", tr("VirtIO")),
    ("sata", tr("SATA")),
    ("ide", tr("IDE")),
]

DISK_FORMATS = [("qcow2", "qcow2"), ("raw", "raw")]


class VmAddDiskDialog(QDialog):
    """Add a new hard disk: choose bus, storage, size, cache."""

    def __init__(self, slot_key, storages, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Add: Hard Disk"))
        self.setMinimumWidth(500)
        self._key = slot_key
        self._storages = storages or []

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"<b>{tr('Add: Hard Disk')}</b>")
        layout.addWidget(header)

        bus = slot_key.rstrip("0123456789")
        info = QLabel(tr("Bus: {bus}, slot: {slot}").format(
            bus=bus, slot=slot_key[len(bus):]))
        info.setStyleSheet(f"color: {Color.TEXT_SEC}; font-size: 11px;")
        layout.addWidget(info)

        form = QFormLayout()
        form.setSpacing(8)

        self._cache_combo = QComboBox()
        for val, label_text in DISK_CACHE:
            self._cache_combo.addItem(label_text, val)
        self._cache_combo.setCurrentIndex(0)
        form.addRow(tr("Cache:"), self._cache_combo)

        self._storage_combo = QComboBox()
        self._storage_combo.setEditable(True)
        for s in self._storages:
            name = s.storage or ""
            if name:
                self._storage_combo.addItem(name, name)
        if self._storage_combo.count() == 0:
            self._storage_combo.addItem("local-lvm", "local-lvm")
        form.addRow(tr("Storage:"), self._storage_combo)

        self._size_spin = QSpinBox()
        self._size_spin.setRange(1, 1048576)
        self._size_spin.setValue(32)
        self._size_spin.setSuffix(" GB")
        form.addRow(tr("Size:"), self._size_spin)

        self._discard_check = QCheckBox(tr("Discard (TRIM/UNMAP)"))
        form.addRow("", self._discard_check)

        self._ssd_check = QCheckBox(tr("SSD emulation"))
        form.addRow("", self._ssd_check)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton(tr("Add"))
        ok_btn.setObjectName("accentBtn")
        ok_btn.setMinimumWidth(120)
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.setMinimumWidth(120)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def get_raw_value(self):
        storage = self._storage_combo.currentText().strip() or "local-lvm"
        size = self._size_spin.value()
        val = f"{storage}:{size}"
        parts = []
        cache = self._cache_combo.currentData()
        if cache and cache != "none":
            parts.append(f"cache={cache}")
        if self._discard_check.isChecked():
            parts.append("discard=on")
        if self._ssd_check.isChecked():
            parts.append("ssd=1")
        if parts:
            val += "," + ",".join(parts)
        return (self._key, val)


class VmAddUsbDialog(QDialog):
    """Add a USB device: host=XXXX:YYYY or spice."""

    def __init__(self, slot_key, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Add: USB Device"))
        self.setMinimumWidth(450)
        self._key = slot_key

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"<b>{tr('Add: USB Device')}</b>")
        layout.addWidget(header)

        info = QLabel(f"{tr('Slot:')} {slot_key}")
        info.setStyleSheet(f"color: {Color.TEXT_SEC}; font-size: 11px;")
        layout.addWidget(info)

        form = QFormLayout()
        form.setSpacing(8)

        self._type_combo = QComboBox()
        self._type_combo.addItem(tr("Host device"), "host")
        self._type_combo.addItem(tr("SPICE"), "spice")
        form.addRow(tr("Type:"), self._type_combo)

        self._host_edit = QLineEdit()
        self._host_edit.setPlaceholderText("1234:5678")
        form.addRow(tr("Host device:"), self._host_edit)

        self._usb3_check = QCheckBox(tr("USB 3.0"))
        form.addRow("", self._usb3_check)

        layout.addLayout(form)

        self._type_combo.currentTextChanged.connect(self._on_type_changed)
        self._on_type_changed()

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton(tr("Add"))
        ok_btn.setObjectName("accentBtn")
        ok_btn.setMinimumWidth(120)
        ok_btn.clicked.connect(self._on_ok)
        btn_layout.addWidget(ok_btn)
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.setMinimumWidth(120)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _on_type_changed(self):
        is_host = self._type_combo.currentData() == "host"
        self._host_edit.setEnabled(is_host)

    def _on_ok(self):
        if self._type_combo.currentData() == "host" and not self._host_edit.text().strip():
            return
        self.accept()

    def get_raw_value(self):
        tp = self._type_combo.currentData()
        if tp == "spice":
            return (self._key, "spice")
        host = self._host_edit.text().strip()
        parts = [f"host={host}"]
        if self._usb3_check.isChecked():
            parts.append("usb3=1")
        return (self._key, ",".join(parts))


class VmAddPciDialog(QDialog):
    """Add a PCI device: hostpciN."""

    def __init__(self, slot_key, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Add: PCI Device"))
        self.setMinimumWidth(450)
        self._key = slot_key

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"<b>{tr('Add: PCI Device')}</b>")
        layout.addWidget(header)

        info = QLabel(f"{tr('Slot:')} {slot_key}")
        info.setStyleSheet(f"color: {Color.TEXT_SEC}; font-size: 11px;")
        layout.addWidget(info)

        form = QFormLayout()
        form.setSpacing(8)

        self._host_edit = QLineEdit()
        self._host_edit.setPlaceholderText("0000:01:02.0")
        form.addRow(tr("Host device:"), self._host_edit)

        self._rombar_check = QCheckBox(tr("ROM-Bar"))
        form.addRow("", self._rombar_check)

        self._xvga_check = QCheckBox(tr("x-VGA (passthrough)"))
        form.addRow("", self._xvga_check)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton(tr("Add"))
        ok_btn.setObjectName("accentBtn")
        ok_btn.setMinimumWidth(120)
        ok_btn.clicked.connect(self._on_ok)
        btn_layout.addWidget(ok_btn)
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.setMinimumWidth(120)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _on_ok(self):
        if not self._host_edit.text().strip():
            return
        self.accept()

    def get_raw_value(self):
        host = self._host_edit.text().strip()
        parts = [host]
        if self._rombar_check.isChecked():
            parts.append("rombar=1")
        if self._xvga_check.isChecked():
            parts.append("x-vga=1")
        return (self._key, ",".join(parts))


class VmAddSerialDialog(QDialog):
    """Add a serial port: serialN."""

    def __init__(self, slot_key, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Add: Serial Port"))
        self.setMinimumWidth(400)
        self._key = slot_key

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"<b>{tr('Add: Serial Port')}</b>")
        layout.addWidget(header)

        info = QLabel(f"{tr('Slot:')} {slot_key}")
        info.setStyleSheet(f"color: {Color.TEXT_SEC}; font-size: 11px;")
        layout.addWidget(info)

        form = QFormLayout()
        form.setSpacing(8)

        self._type_combo = QComboBox()
        self._type_combo.addItem(tr("Socket"), "socket")
        self._type_combo.addItem(tr("Device (/dev/ttyS*)"), "device")
        form.addRow(tr("Type:"), self._type_combo)

        self._dev_edit = QLineEdit()
        self._dev_edit.setPlaceholderText("/dev/ttyS0")
        self._dev_edit.setEnabled(False)
        form.addRow(tr("Device:"), self._dev_edit)

        layout.addLayout(form)

        self._type_combo.currentTextChanged.connect(self._on_type_changed)
        self._on_type_changed()

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton(tr("Add"))
        ok_btn.setObjectName("accentBtn")
        ok_btn.setMinimumWidth(120)
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.setMinimumWidth(120)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _on_type_changed(self):
        self._dev_edit.setEnabled(self._type_combo.currentData() == "device")

    def get_raw_value(self):
        if self._type_combo.currentData() == "socket":
            return (self._key, "socket")
        dev = self._dev_edit.text().strip()
        return (self._key, dev or "/dev/ttyS0")


class VmAddEfiDialog(QDialog):
    """Add an EFI disk: efidisk0."""

    def __init__(self, slot_key, storages, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Add: EFI Disk"))
        self.setMinimumWidth(450)
        self._key = slot_key
        self._storages = storages or []

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"<b>{tr('Add: EFI Disk')}</b>")
        layout.addWidget(header)

        form = QFormLayout()
        form.setSpacing(8)

        self._storage_combo = QComboBox()
        self._storage_combo.setEditable(True)
        for s in self._storages:
            name = s.storage or ""
            if name:
                self._storage_combo.addItem(name, name)
        if self._storage_combo.count() == 0:
            self._storage_combo.addItem("local-lvm", "local-lvm")
        form.addRow(tr("Storage:"), self._storage_combo)

        self._format_combo = QComboBox()
        for val, label_text in DISK_FORMATS:
            self._format_combo.addItem(label_text, val)
        form.addRow(tr("Format:"), self._format_combo)

        self._type_combo = QComboBox()
        self._type_combo.addItem(tr("4 MB (Secure Boot)"), "4m")
        self._type_combo.addItem(tr("2 MB (legacy)"), "2m")
        form.addRow(tr("EFI type:"), self._type_combo)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton(tr("Add"))
        ok_btn.setObjectName("accentBtn")
        ok_btn.setMinimumWidth(120)
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.setMinimumWidth(120)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def get_raw_value(self):
        storage = self._storage_combo.currentText().strip() or "local-lvm"
        efitype = self._type_combo.currentData()
        fmt = self._format_combo.currentData()
        size = 4 if efitype != "2m" else 2
        val = f"{storage}:{size},efitype={efitype},format={fmt}"
        return (self._key, val)


class VmAddTpmDialog(QDialog):
    """Add a TPM state: tpmstate0."""

    def __init__(self, slot_key, storages, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Add: TPM"))
        self.setMinimumWidth(450)
        self._key = slot_key
        self._storages = storages or []

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"<b>{tr('Add: TPM')}</b>")
        layout.addWidget(header)

        form = QFormLayout()
        form.setSpacing(8)

        self._storage_combo = QComboBox()
        self._storage_combo.setEditable(True)
        for s in self._storages:
            name = s.storage or ""
            if name:
                self._storage_combo.addItem(name, name)
        if self._storage_combo.count() == 0:
            self._storage_combo.addItem("local-lvm", "local-lvm")
        form.addRow(tr("Storage:"), self._storage_combo)

        self._version_combo = QComboBox()
        self._version_combo.addItem(tr("v2.0"), "v2.0")
        self._version_combo.addItem(tr("v1.2"), "v1.2")
        form.addRow(tr("Version:"), self._version_combo)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton(tr("Add"))
        ok_btn.setObjectName("accentBtn")
        ok_btn.setMinimumWidth(120)
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.setMinimumWidth(120)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def get_raw_value(self):
        storage = self._storage_combo.currentText().strip() or "local-lvm"
        version = self._version_combo.currentData()
        val = f"{storage}:1,version={version}"
        return (self._key, val)


class VmRemoveDeviceDialog(QDialog):
    """Confirm removal of a device, with optional disk destroy."""

    def __init__(self, key, label, is_disk, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Remove device"))
        self.setMinimumWidth(450)
        self._key = key
        self._is_disk = is_disk
        self._destroy = False

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QLabel(f"<b>{tr('Remove device?')}</b>")
        layout.addWidget(header)

        desc = QLabel(tr("This will remove the configuration entry: {label}").format(label=label))
        desc.setWordWrap(True)
        layout.addWidget(desc)

        if is_disk:
            self._destroy_check = QCheckBox(
                tr("Destroy disk image (permanent, cannot be undone)")
            )
            self._destroy_check.toggled.connect(self._on_destroy_toggled)
            layout.addWidget(self._destroy_check)

            warn = QLabel(
                tr("Without destroying, the disk image remains on storage "
                   "and can be re-attached later.")
            )
            warn.setStyleSheet(f"color: {Color.TEXT_SEC}; font-size: 11px;")
            warn.setWordWrap(True)
            layout.addWidget(warn)
        else:
            self._destroy_check = None

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton(tr("Remove"))
        ok_btn.setObjectName("accentBtn")
        ok_btn.setMinimumWidth(120)
        ok_btn.clicked.connect(self._on_ok)
        btn_layout.addWidget(ok_btn)
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.setMinimumWidth(120)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _on_destroy_toggled(self, checked):
        self._destroy = checked

    def _on_ok(self):
        self.accept()

    @property
    def destroy(self):
        return self._destroy

    def get_key(self):
        return self._key
