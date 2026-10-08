from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
)

from .i18n import tr
from .theme import Color


def _weekdays():
    return [
        ("mon", tr("Monday")),
        ("tue", tr("Tuesday")),
        ("wed", tr("Wednesday")),
        ("thu", tr("Thursday")),
        ("fri", tr("Friday")),
        ("sat", tr("Saturday")),
        ("sun", tr("Sunday")),
    ]


class BackupJobDialog(QDialog):
    """Dialog for creating or editing a scheduled backup job."""

    def __init__(self, parent=None, storages=None, job=None):
        super().__init__(parent)
        self._storages = storages or []
        self._job = job or {}
        self._is_edit = bool(job)
        self.setWindowTitle(tr("Edit backup job") if self._is_edit else tr("Add backup job"))
        self.setMinimumWidth(480)
        self._build_ui()
        if self._is_edit:
            self._fill_from_job()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        form = QFormLayout()
        form.setSpacing(8)

        self._enabled_check = QCheckBox(tr("Enabled"))
        self._enabled_check.setChecked(True)
        form.addRow("", self._enabled_check)

        self._vmid_edit = QLineEdit()
        self._vmid_edit.setPlaceholderText(tr("all or comma-separated VMIDs"))
        form.addRow(tr("VMIDs:"), self._vmid_edit)

        self._mode_combo = QComboBox()
        self._mode_combo.addItem(tr("Snapshot"), "snapshot")
        self._mode_combo.addItem(tr("Suspend"), "suspend")
        self._mode_combo.addItem(tr("Stop"), "stop")
        form.addRow(tr("Mode:"), self._mode_combo)

        self._storage_combo = QComboBox()
        backup_storages = [
            s for s in self._storages
            if "backup" in s.content_list
        ]
        for s in backup_storages:
            name = s.storage or ""
            if name:
                self._storage_combo.addItem(name, name)
        form.addRow(tr("Storage:"), self._storage_combo)

        self._storage_warn = QLabel(tr("No backup storage available"))
        self._storage_warn.setStyleSheet(f"color: {Color.DANGER};")
        self._storage_warn.setVisible(False)
        form.addRow("", self._storage_warn)

        self._compress_combo = QComboBox()
        self._compress_combo.addItem(tr("None"), "0")
        self._compress_combo.addItem("gzip", "gzip")
        self._compress_combo.addItem("lzo", "lzo")
        self._compress_combo.addItem("zstd", "zstd")
        idx = self._compress_combo.findData("zstd")
        if idx >= 0:
            self._compress_combo.setCurrentIndex(idx)
        form.addRow(tr("Compression:"), self._compress_combo)

        schedule_label = QLabel(f"<b>{tr('Schedule')}</b>")
        layout.addLayout(form)
        layout.addWidget(schedule_label)

        self._schedule_type_combo = QComboBox()
        self._schedule_type_combo.addItem(tr("Daily"), "daily")
        self._schedule_type_combo.addItem(tr("Weekly"), "weekly")
        self._schedule_type_combo.addItem(tr("Custom"), "custom")
        sched_form = QFormLayout()
        sched_form.setSpacing(8)
        sched_form.addRow(tr("Type:"), self._schedule_type_combo)

        self._time_edit = QTimeEdit()
        self._time_edit.setDisplayFormat("HH:mm")
        self._time_edit.setTime(self._time_edit.time().addSecs(2 * 3600))
        sched_form.addRow(tr("Time:"), self._time_edit)

        self._dow_combo = QComboBox()
        for code, label in _weekdays():
            self._dow_combo.addItem(label, code)
        idx = self._dow_combo.findData("sat")
        if idx >= 0:
            self._dow_combo.setCurrentIndex(idx)
        sched_form.addRow(tr("Day of week:"), self._dow_combo)

        self._custom_edit = QLineEdit()
        self._custom_edit.setPlaceholderText(tr("e.g. Sat 02:00"))
        sched_form.addRow(tr("Custom schedule:"), self._custom_edit)

        layout.addLayout(sched_form)

        self._schedule_type_combo.currentIndexChanged.connect(self._on_schedule_type_changed)
        self._on_schedule_type_changed()

        extra_form = QFormLayout()
        extra_form.setSpacing(8)

        self._notes_edit = QLineEdit()
        self._notes_edit.setMaxLength(255)
        self._notes_edit.setPlaceholderText(tr("Optional notes"))
        extra_form.addRow(tr("Notes:"), self._notes_edit)

        self._remove_check = QCheckBox(tr("Remove old backups"))
        self._remove_check.toggled.connect(self._on_remove_toggled)
        extra_form.addRow("", self._remove_check)

        self._retain_spin = QSpinBox()
        self._retain_spin.setRange(1, 999)
        self._retain_spin.setValue(3)
        self._retain_spin.setEnabled(False)
        extra_form.addRow(tr("Keep last:"), self._retain_spin)

        self._bwlimit_spin = QSpinBox()
        self._bwlimit_spin.setRange(0, 999999)
        self._bwlimit_spin.setSpecialValueText(tr("No limit"))
        extra_form.addRow(tr("Bandwidth limit (MB/s):"), self._bwlimit_spin)

        layout.addLayout(extra_form)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._ok_btn = QPushButton(tr("Save"))
        self._ok_btn.setObjectName("accentBtn")
        self._ok_btn.setMinimumWidth(120)
        self._ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton(tr("Cancel"))
        cancel_btn.setMinimumWidth(120)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        if not backup_storages:
            self._storage_warn.setVisible(True)
            self._ok_btn.setEnabled(False)

    def _on_schedule_type_changed(self):
        sched_type = self._schedule_type_combo.currentData()
        is_daily = sched_type == "daily"
        is_weekly = sched_type == "weekly"
        is_custom = sched_type == "custom"
        self._time_edit.setEnabled(is_daily or is_weekly)
        self._dow_combo.setEnabled(is_weekly)
        self._custom_edit.setEnabled(is_custom)

    def _on_remove_toggled(self, checked):
        self._retain_spin.setEnabled(checked)

    def _fill_from_job(self):
        job = self._job
        enabled_raw = job.get("enabled", 1)
        try:
            enabled_val = int(enabled_raw or 0)
        except (TypeError, ValueError):
            enabled_val = 1
        self._enabled_check.setChecked(bool(enabled_val))
        vmid = job.get("vmid", "")
        self._vmid_edit.setText(str(vmid) if vmid else "")
        mode = job.get("mode", "snapshot")
        idx = self._mode_combo.findData(mode)
        if idx >= 0:
            self._mode_combo.setCurrentIndex(idx)
        storage = job.get("storage", "")
        idx = self._storage_combo.findData(storage)
        if idx < 0 and storage:
            # Job references a storage that's not in the backup list
            # (removed/unavailable). Show it explicitly instead of silently
            # substituting the first entry and corrupting the job on save.
            self._storage_combo.addItem(
                tr("{name} (unavailable)").format(name=storage), storage
            )
            idx = self._storage_combo.count() - 1
        if idx >= 0:
            self._storage_combo.setCurrentIndex(idx)
        compress = job.get("compress", "0")
        idx = self._compress_combo.findData(str(compress))
        if idx >= 0:
            self._compress_combo.setCurrentIndex(idx)
        self._notes_edit.setText(job.get("comment", "") or "")
        try:
            remove = int(job.get("remove", 0) or 0)
        except (TypeError, ValueError):
            remove = 0
        self._remove_check.setChecked(bool(remove))
        if remove:
            prune = job.get("prune-backups", "keep-last=3")
            retain = 3
            if isinstance(prune, str):
                for part in prune.split(","):
                    part = part.strip()
                    if part.startswith("keep-last="):
                        try:
                            retain = int(part.split("=")[1].strip(" '\""))
                        except (ValueError, IndexError):
                            retain = 3
                        break
            self._retain_spin.setValue(retain)
        try:
            bwlimit = int(job.get("bwlimit", 0) or 0)
        except (TypeError, ValueError):
            bwlimit = 0
        self._bwlimit_spin.setValue(bwlimit)
        schedule = job.get("schedule", "")
        if schedule:
            sched_parts = schedule.split()
            if len(sched_parts) == 2 and sched_parts[0].lower() in (
                "mon", "tue", "wed", "thu", "fri", "sat", "sun"
            ):
                idx = self._schedule_type_combo.findData("weekly")
                if idx >= 0:
                    self._schedule_type_combo.setCurrentIndex(idx)
                dow_idx = self._dow_combo.findData(sched_parts[0].lower())
                if dow_idx >= 0:
                    self._dow_combo.setCurrentIndex(dow_idx)
                try:
                    h, m = sched_parts[1].split(":")
                    from PySide6.QtCore import QTime
                    self._time_edit.setTime(QTime(int(h), int(m)))
                except (ValueError, IndexError):
                    pass
            elif len(sched_parts) == 1 and ":" in sched_parts[0]:
                idx = self._schedule_type_combo.findData("daily")
                if idx >= 0:
                    self._schedule_type_combo.setCurrentIndex(idx)
                try:
                    h, m = sched_parts[0].split(":")
                    from PySide6.QtCore import QTime
                    self._time_edit.setTime(QTime(int(h), int(m)))
                except (ValueError, IndexError):
                    pass
            else:
                idx = self._schedule_type_combo.findData("custom")
                if idx >= 0:
                    self._schedule_type_combo.setCurrentIndex(idx)
                self._custom_edit.setText(schedule)
            self._on_schedule_type_changed()

    def get_params(self):
        params = {}
        params["enabled"] = 1 if self._enabled_check.isChecked() else 0
        vmid_text = self._vmid_edit.text().strip()
        params["vmid"] = vmid_text if vmid_text else "all"
        params["mode"] = self._mode_combo.currentData()
        params["storage"] = self._storage_combo.currentData()
        params["compress"] = self._compress_combo.currentData()
        notes = self._notes_edit.text().strip()
        if notes:
            params["comment"] = notes
        if self._remove_check.isChecked():
            params["remove"] = 1
            params["prune-backups"] = f"keep-last={self._retain_spin.value()}"
        else:
            params["remove"] = 0
        bwlimit = self._bwlimit_spin.value()
        if bwlimit > 0:
            params["bwlimit"] = bwlimit
        sched_type = self._schedule_type_combo.currentData()
        if sched_type == "daily":
            params["schedule"] = self._time_edit.time().toString("HH:mm")
        elif sched_type == "weekly":
            dow = self._dow_combo.currentData()
            params["schedule"] = f"{dow} {self._time_edit.time().toString('HH:mm')}"
        else:
            custom = self._custom_edit.text().strip()
            params["schedule"] = custom if custom else "02:00"
        return params
