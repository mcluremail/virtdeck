"""Backup job create/edit dialog (stage 6.2.1, audit D1–D3b).

Guest selection follows the real PVE contract (PVE::API2::Backup):
selecting all guests, selecting a pool and listing explicit VMIDs are
three different job kinds — ``all`` is a boolean, ``pool`` is a pool id,
``vmid`` is a vmid-list. The word "all" inside the ``vmid`` field is
INVALID for the API.

Editing is diff-based: a field the user did not change is not sent in
the PUT at all, and PVE keeps the stored value (update_job only touches
provided keys). This is what preserves fields the form does not know
about (mailto, mailnotification, performance, fleecing, notes-template,
repeat-missed) and prevents a pool/all job from silently turning into a
vmid-list. Clearing a previously set optional value (exclude/node) goes
through the PUT ``delete`` parameter — an empty string cannot express
removal for those options.

prune-backups is preserved verbatim in the canonical property-string
form; PVE 8 returns it as an object in GET responses, so both shapes
are normalized for display. An unparsable policy blocks the save
instead of being replaced with a form default.
"""

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
)

from .i18n import tr
from .theme import Color

_WEEKDAY_CODES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_KEEP_ORDER = ("keep-hourly", "keep-daily", "keep-weekly",
               "keep-monthly", "keep-yearly", "keep-last")
# PVE defaults for options the GET response may omit (the stored config
# only carries explicit values; defaults are NOT filled in by the API).
_PVE_DEFAULT_REMOVE = 1
_PVE_DEFAULT_COMPRESS = "lzo"
_PVE_DEFAULT_MODE = "snapshot"


def _truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.strip() not in ("", "0")
    return bool(value)


def _normalize_policy(value: object) -> str:
    """prune-backups → canonical property string for display/editing.

    Accepts the property string ("keep-last=3,keep-daily=7") and the
    object shape PVE 8 returns from GET ({"keep-daily": 7, ...}).
    Unknown keys are kept verbatim — normalization must not invent or
    drop policy elements (audit D3).
    """
    if isinstance(value, dict):
        parts = [f"{k}={value[k]}" for k in _KEEP_ORDER if k in value]
        parts += [f"{k}={value[k]}" for k in value if k not in _KEEP_ORDER]
        return ",".join(str(p) for p in parts)
    text = str(value or "").strip()
    parts = [p.strip() for p in text.split(",") if p.strip()]
    rank = {k: i for i, k in enumerate(_KEEP_ORDER)}
    parts.sort(key=lambda p: rank.get(str(p).partition("=")[0].strip(),
                                      len(rank)))
    return ",".join(parts)


def selection_label(job: dict) -> str:
    """Human-readable guest selection for the jobs table (audit A2):
    'All guests', a pool name, a vmid list or a node-restricted variant —
    pool and all=1 jobs must not look like a job without a selection."""
    all_vms = _truthy(job.get("all"))
    pool = str(job.get("pool") or "").strip()
    vmid = str(job.get("vmid") or "").strip()
    exclude = str(job.get("exclude") or "").strip()
    node = str(job.get("node") or "").strip()
    parts = []
    if all_vms:
        label = tr("All guests")
        if exclude:
            label += f" (excl: {exclude})"
        parts.append(label)
    if pool:
        parts.append(f"{tr('pool')}: {pool}")
    if vmid and not all_vms:
        parts.append(vmid)
    if node:
        parts.append(f"@{node}")
    return "  ".join(parts) if parts else "—"


class _InvalidParams(ValueError):
    """The form state cannot produce a safe request (audit A2)."""


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

    def __init__(self, parent=None, storages=None, job=None, pools=None):
        super().__init__(parent)
        self._storages = storages or []
        self._job = job or {}
        self._is_edit = bool(job)
        self._pools = [str(p) for p in (pools or []) if str(p)]
        # Base snapshot of the loaded job: fields absent from the API
        # answer are tracked as absent so an unchanged save does not
        # invent defaults (audit D3b: PVE remove/compress defaults).
        self._base = self._job_base(self._job)
        self.setWindowTitle(tr("Edit backup job") if self._is_edit
                            else tr("Add backup job"))
        self.setMinimumWidth(480)
        self._build_ui()
        if self._is_edit:
            self._fill_from_job()

    # -- base snapshot -----------------------------------------------------

    @staticmethod
    def _job_base(job: dict) -> dict:
        return {
            "all": job.get("all"),
            "pool": job.get("pool"),
            "vmid": job.get("vmid"),
            "exclude": job.get("exclude"),
            "node": job.get("node"),
            "enabled": job.get("enabled", 1),
            "mode": job.get("mode", _PVE_DEFAULT_MODE),
            "storage": job.get("storage"),
            "compress": job.get("compress"),
            "comment": job.get("comment"),
            "remove": job.get("remove"),
            "prune": job.get("prune-backups"),
            "bwlimit": job.get("bwlimit"),
            "schedule": job.get("schedule"),
        }

    # -- UI ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        form = QFormLayout()
        form.setSpacing(8)

        self._enabled_check = QCheckBox(tr("Enabled"))
        self._enabled_check.setChecked(True)
        form.addRow("", self._enabled_check)

        # -- guest selection (audit A2): three distinct job kinds --
        self._sel_combo = QComboBox()
        self._sel_combo.addItem(tr("All guests"), "all")
        self._sel_combo.addItem(tr("pool"), "pool")
        self._sel_combo.addItem(tr("VMID list"), "vmid")
        form.addRow(tr("Selection mode:"), self._sel_combo)

        self._vmid_edit = QLineEdit()
        self._vmid_edit.setPlaceholderText(tr("comma-separated VMIDs"))
        form.addRow(tr("VMIDs:"), self._vmid_edit)

        self._pool_combo = QComboBox()
        self._pool_combo.setEditable(True)
        for p in self._pools:
            self._pool_combo.addItem(p, p)
        form.addRow(tr("pool"), self._pool_combo)

        self._exclude_edit = QLineEdit()
        self._exclude_edit.setPlaceholderText(tr("comma-separated VMIDs"))
        form.addRow(tr("Exclude:"), self._exclude_edit)

        self._node_edit = QLineEdit()
        self._node_edit.setPlaceholderText(tr("empty — all nodes"))
        form.addRow(tr("Node:"), self._node_edit)

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
        self._sel_combo.currentIndexChanged.connect(self._on_sel_mode_changed)

        extra_form = QFormLayout()
        extra_form.setSpacing(8)

        self._notes_edit = QLineEdit()
        self._notes_edit.setMaxLength(255)
        self._notes_edit.setPlaceholderText(tr("Optional notes"))
        extra_form.addRow(tr("Notes:"), self._notes_edit)

        self._remove_check = QCheckBox(tr("Remove old backups"))
        self._remove_check.toggled.connect(self._on_remove_toggled)
        extra_form.addRow("", self._remove_check)

        self._prune_edit = QLineEdit()
        self._prune_edit.setPlaceholderText(
            tr("empty — storage's own retention policy"))
        extra_form.addRow(tr("Retention policy:"), self._prune_edit)

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

        self._on_schedule_type_changed()
        self._on_sel_mode_changed()

    def _on_schedule_type_changed(self):
        sched_type = self._schedule_type_combo.currentData()
        is_daily = sched_type == "daily"
        is_weekly = sched_type == "weekly"
        is_custom = sched_type == "custom"
        self._time_edit.setEnabled(is_daily or is_weekly)
        self._dow_combo.setEnabled(is_weekly)
        self._custom_edit.setEnabled(is_custom)

    def _on_sel_mode_changed(self):
        """Only the fields belonging to the selected job kind are
        enabled (audit A2: do not send fields foreign to the mode)."""
        mode = self._sel_combo.currentData()
        self._pool_combo.setEnabled(mode == "pool")
        self._vmid_edit.setEnabled(mode == "vmid")
        self._exclude_edit.setEnabled(mode == "all")

    def _on_remove_toggled(self, checked):
        self._prune_edit.setEnabled(checked)

    # -- fill (edit) ---------------------------------------------------------

    def _fill_from_job(self):
        base = self._base

        self._enabled_check.setChecked(bool(int(base["enabled"] or 0)))

        # guest selection: all > pool > vmid (vzdump priority)
        if _truthy(base["all"]):
            self._sel_combo.setCurrentIndex(
                self._sel_combo.findData("all"))
        elif str(base["pool"] or "").strip():
            self._sel_combo.setCurrentIndex(
                self._sel_combo.findData("pool"))
        else:
            self._sel_combo.setCurrentIndex(
                self._sel_combo.findData("vmid"))
        self._vmid_edit.setText(str(base["vmid"] or ""))
        exclude = str(base["exclude"] or "").strip()
        self._exclude_edit.setText(exclude)
        pool = str(base["pool"] or "").strip()
        if pool:
            if self._pool_combo.findText(pool) < 0:
                self._pool_combo.addItem(pool, pool)
            self._pool_combo.setCurrentText(pool)
        self._node_edit.setText(str(base["node"] or "").strip())

        mode = base["mode"] or _PVE_DEFAULT_MODE
        idx = self._mode_combo.findData(mode)
        if idx >= 0:
            self._mode_combo.setCurrentIndex(idx)
        storage = base["storage"] or ""
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
        compress = base["compress"]
        display_compress = str(compress) if compress is not None \
            else _PVE_DEFAULT_COMPRESS
        idx = self._compress_combo.findData(display_compress)
        if idx >= 0:
            self._compress_combo.setCurrentIndex(idx)
        self._notes_edit.setText(str(base["comment"] or ""))

        # remove: PVE default is 1 — a missing field must not read as 0
        remove_effective = _PVE_DEFAULT_REMOVE if base["remove"] is None \
            else int(base["remove"] or 0)
        self._remove_check.setChecked(bool(remove_effective))
        self._prune_edit.setText(_normalize_policy(base["prune"])
                                 if base["prune"] is not None else "")

        try:
            bwlimit = int(base["bwlimit"] or 0)
        except (TypeError, ValueError):
            bwlimit = 0
        self._bwlimit_spin.setValue(bwlimit)

        schedule = str(base["schedule"] or "")
        if schedule:
            sched_parts = schedule.split()
            if len(sched_parts) == 2 and sched_parts[0].lower() in _WEEKDAY_CODES:
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
        self._on_remove_toggled(self._remove_check.isChecked())
        self._on_sel_mode_changed()

    # -- params ----------------------------------------------------------

    def _selection_params(self) -> dict:
        """Guest selection for the currently chosen job kind.

        Only the mode's own keys are returned — foreign selection keys
        must never accompany them (PVE treats the keys as mutually
        exclusive and deletes the others).
        """
        mode = self._sel_combo.currentData()
        params: dict = {}
        if mode == "all":
            params["all"] = 1
            exclude = self._exclude_edit.text().strip()
            if exclude:
                params["exclude"] = exclude
        elif mode == "pool":
            pool = self._pool_combo.currentText().strip()
            if not pool:
                raise _InvalidParams(tr(
                    "Select a pool or change the selection mode"))
            params["pool"] = pool
        else:
            vmid = self._vmid_edit.text().strip()
            if not vmid:
                raise _InvalidParams(tr(
                    "Enter at least one VMID or change the selection mode"))
            err = self._check_vmid_list(vmid)
            if err:
                raise _InvalidParams(err)
            params["vmid"] = vmid
        return params

    @staticmethod
    def _check_vmid_list(text: str) -> str | None:
        for part in text.split(","):
            part = part.strip()
            if not part:
                continue
            if not part.isdigit() or int(part) <= 0:
                return tr("Invalid VMID: {vmid}").format(vmid=part)
        return None

    def _current_selection_state(self) -> tuple[str, str]:
        """(kind, value) as shown in the form; value '' — not set."""
        mode = self._sel_combo.currentData()
        if mode == "all":
            return ("all", self._exclude_edit.text().strip())
        if mode == "pool":
            return ("pool", self._pool_combo.currentText().strip())
        return ("vmid", self._vmid_edit.text().strip())

    def _base_selection_state(self) -> tuple[str, str]:
        """The loaded job's selection as a (kind, value) state. A job
        without any selection (degenerate config) is represented as
        ('vmid', '') — an unchanged save then sends no selection keys
        and the job stays intact (audit A1)."""
        if _truthy(self._base["all"]):
            return ("all", str(self._base["exclude"] or "").strip())
        pool = str(self._base["pool"] or "").strip()
        if pool:
            return ("pool", pool)
        return ("vmid", str(self._base["vmid"] or "").strip())

    def _selection_deletions(self) -> list[str]:
        """Keys to drop via PUT ``delete``.

        A mode switch needs no explicit deletes: when the new selection
        key arrives, PVE itself removes the other keys (update_job's
        elsif chain). Only same-mode clears — and the independent
        ``node`` — need an explicit ``delete``: an empty string cannot
        express removal for those options."""
        if not self._is_edit:
            return []
        base_mode, base_val = self._base_selection_state()
        cur_mode, cur_val = self._current_selection_state()
        deletions: list[str] = []
        if cur_mode == base_mode:
            if base_val and not cur_val:
                deletions.append({"all": "exclude", "pool": "pool",
                                  "vmid": "vmid"}[base_mode])
        node_base = str(self._base["node"] or "").strip()
        if node_base and not self._node_edit.text().strip():
            deletions.append("node")
        return deletions

    def _schedule_string(self) -> str:
        sched_type = self._schedule_type_combo.currentData()
        if sched_type == "daily":
            return self._time_edit.time().toString("HH:mm")
        if sched_type == "weekly":
            dow = self._dow_combo.currentData()
            return f"{dow} {self._time_edit.time().toString('HH:mm')}"
        custom = self._custom_edit.text().strip()
        return custom if custom else "02:00"

    def _changed(self, key: str) -> bool:
        """Field-level diff against the loaded job: a value is sent only
        when the user actually changed it (absent ≠ default ≠ changed)."""
        base = self._base.get(key)
        if key == "enabled":
            return bool(int(base or 0)) != self._enabled_check.isChecked()
        if key == "comment":
            return str(base or "") != self._notes_edit.text().strip()
        if key == "node":
            return str(base or "").strip() != self._node_edit.text().strip()
        if key == "remove":
            base_effective = _PVE_DEFAULT_REMOVE if base is None \
                else int(base or 0)
            return bool(base_effective) != self._remove_check.isChecked()
        if key == "compress":
            base_display = str(base) if base is not None \
                else _PVE_DEFAULT_COMPRESS
            return base_display != self._compress_combo.currentData()
        if key == "prune":
            base_text = _normalize_policy(base) if base is not None else ""
            return base_text != self._prune_edit.text().strip()
        if key == "bwlimit":
            try:
                base_value = int(base or 0)
            except (TypeError, ValueError):
                base_value = 0
            return base_value != self._bwlimit_spin.value()
        if key == "mode":
            return (base or _PVE_DEFAULT_MODE) \
                != self._mode_combo.currentData()
        if key == "storage":
            return str(base or "") != str(self._storage_combo.currentData()
                                          or "")
        if key == "schedule":
            return str(base or "") != self._schedule_string()
        return False

    def get_params(self):
        """Request parameters; ``{}`` for an edit without changes.

        Raises _InvalidParams when the form state cannot produce a safe
        request (empty selection, unparsable retention policy).  In edit
        mode only fields the user changed are included — PVE keeps every
        key not present in the PUT, so fields the form does not know
        (mailto, performance, fleecing, …) survive untouched (audit A4).
        """
        params: dict = {}
        if self._is_edit:
            base_state = self._base_selection_state()
            cur_state = self._current_selection_state()
            if cur_state != base_state:
                base_mode, base_val = base_state
                cur_mode, cur_val = cur_state
                if cur_mode == base_mode and not cur_val:
                    # same kind, value cleared: the stored key is removed
                    # via ``delete`` — re-sending the mode's key is not
                    # needed and an empty vmid/pool cannot be sent at all
                    pass
                else:
                    params.update(self._selection_params())
            deletions = self._selection_deletions()
            if deletions:
                params["delete"] = ",".join(deletions)
            if self._changed("node"):
                node = self._node_edit.text().strip()
                if node:
                    params["node"] = node
            if self._changed("enabled"):
                params["enabled"] = 1 if self._enabled_check.isChecked() \
                    else 0
            if self._changed("mode"):
                params["mode"] = self._mode_combo.currentData()
            if self._changed("storage"):
                params["storage"] = self._storage_combo.currentData()
            if self._changed("compress"):
                params["compress"] = self._compress_combo.currentData()
            if self._changed("comment"):
                params["comment"] = self._notes_edit.text().strip()
            if self._changed("remove"):
                params["remove"] = 1 if self._remove_check.isChecked() \
                    else 0
            if self._remove_check.isChecked() and self._changed("prune"):
                params["prune-backups"] = self._parsed_policy()
            if self._changed("bwlimit") and self._bwlimit_spin.value() > 0:
                params["bwlimit"] = self._bwlimit_spin.value()
            if self._changed("schedule"):
                params["schedule"] = self._schedule_string()
            return params

        # creation: everything is explicit
        params.update(self._selection_params())
        node = self._node_edit.text().strip()
        if node:
            params["node"] = node
        params["enabled"] = 1 if self._enabled_check.isChecked() else 0
        params["mode"] = self._mode_combo.currentData()
        params["storage"] = self._storage_combo.currentData()
        params["compress"] = self._compress_combo.currentData()
        notes = self._notes_edit.text().strip()
        if notes:
            params["comment"] = notes
        if self._remove_check.isChecked():
            params["remove"] = 1
            policy = self._prune_edit.text().strip()
            if policy:
                params["prune-backups"] = self._parsed_policy()
        else:
            params["remove"] = 0
        bwlimit = self._bwlimit_spin.value()
        if bwlimit > 0:
            params["bwlimit"] = bwlimit
        params["schedule"] = self._schedule_string()
        return params

    def _parsed_policy(self) -> str:
        text = self._prune_edit.text().strip()
        if not text:
            return ""
        for part in text.split(","):
            part = part.strip()
            if not part:
                continue
            key, _sep, value = part.partition("=")
            if key not in _KEEP_ORDER or not value.isdigit():
                raise _InvalidParams(tr(
                    "Invalid retention policy: {policy}").format(policy=part))
        return text

    def accept(self):
        try:
            params = self.get_params()
        except _InvalidParams as exc:
            QMessageBox.warning(self, tr("Cannot save backup job"),
                                str(exc))
            return
        if self._is_edit and not params:
            QMessageBox.information(self, tr("Edit backup job"),
                                    tr("No changes to save"))
            return
        super().accept()
