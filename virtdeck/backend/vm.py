"""VM/CT detail, config, disk, task-history, snapshots and bulk actions."""

import logging

from PySide6.QtCore import QObject, QRunnable, Signal

from ..domain.snapshot import Snapshot
from ..domain.task import Task
from ..plugins import create_provider
from ..ui.i18n import tr
from ..ui.vm_actions import VM_ACTION_MESSAGE_LABELS
from .core import _await_task, _sanitize_error

logger = logging.getLogger(__name__)

class VmDetailSignals(QObject):
    detail_ready = Signal(dict)
    finished = Signal()
class VmDetailWorker(QRunnable):
    def __init__(self, host_cfg, node_name, vmid, vm_type):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.vmid = vmid
        self.vm_type = vm_type
        self.signals = VmDetailSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=10)
            vm_api = provider.vms
            status = vm_api.get_status(self.node_name, self.vmid, self.vm_type)
            try:
                self.signals.detail_ready.emit({
                    "vmid": self.vmid,
                    "status": "ok",
                    "data": status
                })
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug("backend error: %s", e)
            try:
                self.signals.detail_ready.emit({
                    "vmid": self.vmid,
                    "status": "error",
                    "error": str(e)
                })
            except RuntimeError:
                pass
        finally:
            if provider:
                provider.close()
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass

# ----------------------------------------------------------------------
# VmConfigWorker
# ----------------------------------------------------------------------
class VmConfigSignals(QObject):
    config_ready = Signal(int, dict)
    config_error = Signal(int, str)
    finished = Signal()
class VmConfigWorker(QRunnable):
    def __init__(self, host_cfg, node_name, vmid, vm_type='qemu'):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.vmid = vmid
        self.vm_type = vm_type
        self.signals = VmConfigSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=10)
            vm_api = provider.vms
            config = vm_api.get_config(self.node_name, self.vmid, self.vm_type)
            try:
                self.signals.config_ready.emit(self.vmid, config)
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug("backend error: %s", e)
            try:
                self.signals.config_error.emit(self.vmid, str(e))
            except RuntimeError:
                pass
        finally:
            if provider:
                provider.close()
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass

# ----------------------------------------------------------------------
# VmConfigUpdateWorker — PUT /nodes/{node}/qemu/{vmid}/config
# ----------------------------------------------------------------------
class VmConfigUpdateSignals(QObject):
    config_updated = Signal(int, object)
    config_update_error = Signal(int, str)
    finished = Signal()
class VmConfigUpdateWorker(QRunnable):
    """Updates VM parameters via PUT /nodes/{node}/qemu/{vmid}/config."""
    def __init__(self, host_cfg, node_name, vmid, params, vm_type='qemu'):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.vmid = vmid
        self.params = params
        self.vm_type = vm_type
        self.signals = VmConfigUpdateSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=10)
            vm_api = provider.vms
            result = vm_api.update_config(self.node_name, self.vmid, self.vm_type, **self.params)
            try:
                self.signals.config_updated.emit(self.vmid, result)
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug("backend error: %s", e)
            try:
                self.signals.config_update_error.emit(self.vmid, str(e))
            except RuntimeError:
                pass
        finally:
            if provider:
                provider.close()
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass

# ----------------------------------------------------------------------
# VmDiskResizeWorker — PUT /nodes/{node}/qemu/{vmid}/resize
# ----------------------------------------------------------------------
class VmDiskResizeSignals(QObject):
    disk_resized = Signal(int, str)   # vmid, "" (emitted after task completion)
    disk_resize_error = Signal(int, str)
    finished = Signal()
class VmDiskResizeWorker(QRunnable):
    """Resize a VM disk via PUT /nodes/{node}/qemu/{vmid}/resize."""
    def __init__(self, host_cfg, node_name, vmid, disk, size, vm_type="qemu"):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.vmid = vmid
        self.disk = disk        # e.g. "scsi0", "virtio0"
        self.size = size        # e.g. "+10G" or "20G"
        self.vm_type = vm_type
        self.signals = VmDiskResizeSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=30)
            vm_api = provider.vms
            # PUT resize forks an async task in PVE — await it, otherwise
            # a failed resize (no space, bad size) reports a false success
            ok, err = _await_task(
                provider, self.node_name,
                vm_api.resize_disk(self.node_name, self.vmid, self.vm_type,
                                   self.disk, self.size),
                timeout=600,
            )
            if ok:
                try:
                    self.signals.disk_resized.emit(self.vmid, "")
                except RuntimeError:
                    pass
            else:
                try:
                    self.signals.disk_resize_error.emit(self.vmid, err)
                except RuntimeError:
                    pass
        except Exception as e:
            logger.debug("backend error: %s", e)
            try:
                self.signals.disk_resize_error.emit(self.vmid, _sanitize_error(e))
            except RuntimeError:
                pass
        finally:
            if provider:
                provider.close()
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass

# ----------------------------------------------------------------------
# VmDiskMoveWorker — POST /nodes/{node}/qemu/{vmid}/move_disk
# ----------------------------------------------------------------------
class VmDiskMoveSignals(QObject):
    disk_moved = Signal(int, str)   # vmid, "" (emitted after task completion)
    disk_move_error = Signal(int, str)
    finished = Signal()
class VmDiskMoveWorker(QRunnable):
    """Move a VM disk to another storage via POST /nodes/{node}/qemu/{vmid}/move_disk."""
    def __init__(self, host_cfg, node_name, vmid, disk, storage,
                 delete=False, vm_type="qemu"):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.vmid = vmid
        self.disk = disk            # e.g. "scsi0"
        self.storage = storage      # target storage name
        self.delete = delete        # delete source after move
        self.vm_type = vm_type
        self.signals = VmDiskMoveSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=60)
            vm_api = provider.vms
            # POST move_disk/move_volume is a long async task (disk
            # copy) — await it; a false "moved" hides a half-moved disk
            ok, err = _await_task(
                provider, self.node_name,
                vm_api.move_disk(self.node_name, self.vmid, self.vm_type,
                                 self.disk, self.storage, delete=self.delete),
                timeout=3600,
            )
            if ok:
                try:
                    self.signals.disk_moved.emit(self.vmid, "")
                except RuntimeError:
                    pass
            else:
                try:
                    self.signals.disk_move_error.emit(self.vmid, err)
                except RuntimeError:
                    pass
        except Exception as e:
            logger.debug("backend error: %s", e)
            try:
                self.signals.disk_move_error.emit(self.vmid, _sanitize_error(e))
            except RuntimeError:
                pass
        finally:
            if provider:
                provider.close()
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass

# ----------------------------------------------------------------------
# VmTaskHistoryWorker
# ----------------------------------------------------------------------
class VmTaskHistorySignals(QObject):
    tasks_ready = Signal(int, list)   # vmid, task list
    tasks_error = Signal(int, str)
    finished = Signal()
class VmTaskHistoryWorker(QRunnable):
    """Loads the task history for a specific VM."""
    def __init__(self, host_cfg, node_name, vmid, limit=50):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.vmid = vmid
        self.limit = limit
        self.signals = VmTaskHistorySignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=10)
            task_api = provider.tasks
            tasks = [Task.from_pve(t)
                     for t in task_api.list_for_vm(self.node_name, self.vmid,
                                                   limit=self.limit)]
            try:
                self.signals.tasks_ready.emit(self.vmid, tasks)
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug("backend error: %s", e)
            try:
                self.signals.tasks_error.emit(self.vmid, str(e))
            except RuntimeError:
                pass
        finally:
            if provider:
                provider.close()
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass

# ----------------------------------------------------------------------
# VmSnapshotsWorker
# ----------------------------------------------------------------------
class VmSnapshotsSignals(QObject):
    snapshots_ready = Signal(int, list)   # vmid, snapshot list
    snapshots_error = Signal(int, str)
    finished = Signal()
_DISK_KEYS = ("scsi", "ide", "sata", "virtio", "efidisk")
def _parse_disk_size(val_str):
    """Parse size from a PVE disk config string like 'local-lvm:vm-100-disk-0,size=32G'."""
    if not isinstance(val_str, str):
        return 0
    total = 0
    for part in val_str.split(","):
        part = part.strip()
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key.strip() != "size":
            continue
        value = value.strip().upper()
        if not value:
            continue
        multiplier = 1
        if value.endswith("T"):
            multiplier = 1024 ** 4
            value = value[:-1]
        elif value.endswith("G"):
            multiplier = 1024 ** 3
            value = value[:-1]
        elif value.endswith("M"):
            multiplier = 1024 ** 2
            value = value[:-1]
        elif value.endswith("K"):
            multiplier = 1024
            value = value[:-1]
        try:
            total += float(value) * multiplier
        except ValueError:
            pass
    return int(total)
class VmSnapshotsWorker(QRunnable):
    """Loads the snapshot list for a specific VM (with an extra size request)."""
    def __init__(self, host_cfg, node_name, vmid, vm_type="qemu"):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.vmid = vmid
        self.vm_type = vm_type
        self.signals = VmSnapshotsSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=10)
            vm_api = provider.vms
            snaps = vm_api.list_snapshots(self.node_name, self.vmid, self.vm_type)
            filtered = []
            for s in snaps:
                if s.get("name") == "current":
                    continue
                raw = dict(s)
                name = raw.get("name", "")
                if not name:
                    continue
                try:
                    cfg = vm_api.get_snapshot_config(
                        self.node_name, self.vmid, self.vm_type, name
                    )
                    total_bytes = 0
                    for key, val in cfg.items():
                        if not isinstance(val, str):
                            continue
                        if key[0].isdigit() or key.startswith(
                            ("scsi", "ide", "sata", "virtio", "efidisk")
                        ):
                            total_bytes += _parse_disk_size(val)
                    raw["size"] = total_bytes
                except Exception:
                    raw["size"] = 0
                raw["vmid"] = self.vmid
                filtered.append(Snapshot.from_pve(raw))
            filtered.sort(key=lambda s: (s.snaptime or 0))
            try:
                self.signals.snapshots_ready.emit(self.vmid, filtered)
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug("VmSnapshotsWorker error for vmid %s: %s", self.vmid, e)
            try:
                self.signals.snapshots_error.emit(self.vmid, str(e))
            except RuntimeError:
                pass
        finally:
            if provider:
                provider.close()
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass

# ----------------------------------------------------------------------
# Delete token from the server
# ----------------------------------------------------------------------
class VmActionSignals(QObject):
    action_result = Signal(str)
    action_error = Signal(str)
    finished = Signal()
class VmActionWorker(QRunnable):
    ACTION_NAMES = VM_ACTION_MESSAGE_LABELS
    # POST status/{action} is an async task in PVE: it must be awaited,
    # otherwise a failed start/stop is reported as a false "completed"
    TASK_TIMEOUTS = {"start": 600, "shutdown": 600, "reboot": 900,
                     "stop": 300, "reset": 300, "suspend": 300,
                     "resume": 300}
    DEFAULT_TASK_TIMEOUT_S = 600

    def __init__(self, host_cfg, node_name, vmid, vm_type, action):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.vmid = vmid
        self.vm_type = vm_type
        self.action = action
        self.signals = VmActionSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=10)
            vm_api = provider.vms
            ok, err = _await_task(
                provider, self.node_name,
                vm_api.perform_action(self.node_name, self.vmid,
                                      self.vm_type, self.action),
                timeout=self.TASK_TIMEOUTS.get(
                    self.action, self.DEFAULT_TASK_TIMEOUT_S),
            )
            if ok:
                action_name = self.ACTION_NAMES.get(self.action, self.action)
                try:
                    self.signals.action_result.emit(
                        tr("VM {vmid}: {action} completed").format(
                            vmid=self.vmid, action=action_name)
                    )
                except RuntimeError:
                    pass
            else:
                try:
                    self.signals.action_error.emit(err)
                except RuntimeError:
                    pass
        except Exception as e:
            logger.debug("backend error: %s", e)
            try:
                self.signals.action_error.emit(_sanitize_error(e))
            except RuntimeError:
                pass
        finally:
            if provider:
                provider.close()
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass
class BulkVmActionSignals(QObject):
    progress = Signal(int, int, int)  # done, total, current vmid
    vm_done = Signal(int, bool, str)  # vmid, ok, message
    finished = Signal()
class BulkVmActionWorker(QRunnable):
    """Perform one action over many VMs sequentially (B3 bulk operations).

    Targets: list of dicts with keys host_cfg, node, vmid, vm_type.
    Emits progress before each VM, vm_done after each VM, finished at the end.
    Cancellation is cooperative: cancel() stops before the next VM.
    Each action task is awaited — a failed start/stop is reported as a
    per-VM failure, not a false "completed".
    """

    TASK_TIMEOUTS = VmActionWorker.TASK_TIMEOUTS
    DEFAULT_TASK_TIMEOUT_S = VmActionWorker.DEFAULT_TASK_TIMEOUT_S

    def __init__(self, targets, action):
        super().__init__()
        self.targets = list(targets)
        self.action = action
        self.signals = BulkVmActionSignals()
        self._cancel = False
        self.was_cancelled = False

    def cancel(self):
        self._cancel = True

    def run(self):
        total = len(self.targets)
        done = 0
        providers: dict = {}  # per-host reuse: one login for many VMs
        try:
            for target in self.targets:
                if self._cancel:
                    self.was_cancelled = True
                    break
                vmid = target["vmid"]
                try:
                    self.signals.progress.emit(done, total, vmid)
                except RuntimeError:
                    pass
                ok = False
                msg = ""
                try:
                    provider = self._host_provider(providers, target)
                    ok, err = _await_task(
                        provider, target["node"],
                        provider.vms.perform_action(
                            target["node"], vmid, target["vm_type"],
                            self.action,
                        ),
                        timeout=self.TASK_TIMEOUTS.get(
                            self.action, self.DEFAULT_TASK_TIMEOUT_S),
                    )
                    if ok:
                        action_name = VM_ACTION_MESSAGE_LABELS.get(
                            self.action, self.action)
                        msg = tr("VM {vmid}: {action} completed").format(
                            vmid=vmid, action=action_name)
                    else:
                        ok = False
                        msg = err
                except Exception as e:
                    logger.debug("backend error: %s", e)
                    msg = _sanitize_error(e)
                done += 1
                try:
                    self.signals.vm_done.emit(vmid, ok, msg)
                except RuntimeError:
                    pass
        finally:
            for p in providers.values():
                try:
                    p.close()
                except Exception:
                    pass
        try:
            self.signals.finished.emit()
        except RuntimeError:
            pass

    @staticmethod
    def _host_provider(providers: dict, target: dict):
        """One provider (session/login) per host for the whole bulk run."""
        host = str(target["host_cfg"].get("name", ""))
        if host not in providers:
            providers[host] = create_provider(target["host_cfg"], timeout=10)
        return providers[host]
class VmSnapshotCreateSignals(QObject):
    result = Signal(str)
    error = Signal(str)
    finished = Signal()
class VmSnapshotCreateWorker(QRunnable):
    def __init__(self, host_cfg, node_name, vmid, vm_type, snap_name, description="", vmstate=False):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.vmid = vmid
        self.vm_type = vm_type
        self.snap_name = snap_name
        self.description = description
        self.vmstate = vmstate
        self.signals = VmSnapshotCreateSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=10)
            vm_api = provider.vms
            ok, err = _await_task(
                provider, self.node_name,
                vm_api.create_snapshot(
                    self.node_name, self.vmid, self.vm_type,
                    self.snap_name, self.description, self.vmstate,
                ),
                timeout=120,
            )
            if ok:
                try:
                    self.signals.result.emit(
                        tr("Snapshot \"{name}\" created").format(name=self.snap_name)
                    )
                except RuntimeError:
                    pass
            else:
                try:
                    self.signals.error.emit(
                        tr("Snapshot create failed: {err}").format(err=err)
                    )
                except RuntimeError:
                    pass
        except Exception as e:
            logger.debug("backend error: %s", e)
            try:
                self.signals.error.emit(_sanitize_error(e))
            except RuntimeError:
                pass
        finally:
            if provider:
                provider.close()
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass

# ----------------------------------------------------------------------
# VmSnapshotDeleteWorker
# ----------------------------------------------------------------------
class VmSnapshotDeleteSignals(QObject):
    result = Signal(str)
    error = Signal(str)
    finished = Signal()
class VmSnapshotDeleteWorker(QRunnable):
    def __init__(self, host_cfg, node_name, vmid, vm_type, snap_name):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.vmid = vmid
        self.vm_type = vm_type
        self.snap_name = snap_name
        self.signals = VmSnapshotDeleteSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=10)
            vm_api = provider.vms
            ok, err = _await_task(
                provider, self.node_name,
                vm_api.delete_snapshot(self.node_name, self.vmid, self.vm_type, self.snap_name),
                timeout=120,
            )
            if ok:
                try:
                    self.signals.result.emit(
                        tr("Snapshot \"{name}\" deleted").format(name=self.snap_name)
                    )
                except RuntimeError:
                    pass
            else:
                try:
                    self.signals.error.emit(
                        tr("Snapshot delete failed: {err}").format(err=err)
                    )
                except RuntimeError:
                    pass
        except Exception as e:
            logger.debug("backend error: %s", e)
            try:
                self.signals.error.emit(_sanitize_error(e))
            except RuntimeError:
                pass
        finally:
            if provider:
                provider.close()
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass

# ----------------------------------------------------------------------
# VmSnapshotRollbackWorker
# ----------------------------------------------------------------------
class VmSnapshotRollbackSignals(QObject):
    result = Signal(str)
    error = Signal(str)
    finished = Signal()
class VmSnapshotRollbackWorker(QRunnable):
    def __init__(self, host_cfg, node_name, vmid, vm_type, snap_name):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.vmid = vmid
        self.vm_type = vm_type
        self.snap_name = snap_name
        self.signals = VmSnapshotRollbackSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=10)
            vm_api = provider.vms
            ok, err = _await_task(
                provider, self.node_name,
                vm_api.rollback_snapshot(
                    self.node_name, self.vmid, self.vm_type, self.snap_name
                ),
                timeout=180,
            )
            if ok:
                try:
                    self.signals.result.emit(
                        tr("Rolled back to snapshot \"{name}\"").format(name=self.snap_name)
                    )
                except RuntimeError:
                    pass
            else:
                try:
                    self.signals.error.emit(
                        tr("Snapshot rollback failed: {err}").format(err=err)
                    )
                except RuntimeError:
                    pass
        except Exception as e:
            logger.debug("backend error: %s", e)
            try:
                self.signals.error.emit(_sanitize_error(e))
            except RuntimeError:
                pass
        finally:
            if provider:
                provider.close()
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass

# ----------------------------------------------------------------------
# ClusterTasksWorker
# ----------------------------------------------------------------------
