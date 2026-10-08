"""VM lifecycle ops: create, delete, migrate, clone, template conversion, restore."""

import logging

from PySide6.QtCore import QObject, QRunnable, Signal

from ..plugins import create_provider
from ..ui.i18n import tr
from .core import _await_task, _safe_emit, _sanitize_error

logger = logging.getLogger(__name__)

class CreateVmSignals(QObject):
    vm_created = Signal(str)  # success message
    vm_error = Signal(str)    # error message
    finished = Signal()
class CreateVmWorker(QRunnable):
    """Creates QEMU VM via POST /nodes/{node}/qemu."""
    def __init__(self, host_cfg, node_name, params, ha_group=None):
        """
        params: dict with VM parameters (name, cores, memory, sockets, ostype, etc.)
        ha_group: HA group name (optional)
        """
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.params = params
        self.ha_group = ha_group
        self.signals = CreateVmSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=30)
            cluster_api = provider.cluster
            vm_api = provider.vms

            params = dict(self.params)
            # Request next free VMID if not specified
            if not params.get("vmid"):
                try:
                    params["vmid"] = cluster_api.next_vmid()
                except Exception:
                    try:
                        self.signals.vm_error.emit(
                            tr("Could not get next free VMID from cluster")
                        )
                    except RuntimeError:
                        pass
                    return

            ok, err = _await_task(
                provider, self.node_name,
                vm_api.create_qemu(self.node_name, **params),
                timeout=300,
            )
            if not ok:
                try:
                    self.signals.vm_error.emit(
                        tr("VM create failed: {err}").format(err=err)
                    )
                except RuntimeError:
                    pass
                return
            vmid = params.get("vmid", "?")
            msg = tr("VM {vmid} created on {node}").format(vmid=vmid, node=self.node_name)

            # Add to HA group
            if self.ha_group:
                try:
                    ha_params = {
                        "sid": f"vm:{vmid}",
                        "group": self.ha_group,
                    }
                    if not self.params.get("start"):
                        ha_params["state"] = "stopped"
                    cluster_api.add_ha_resource(**ha_params)
                    msg += tr(", added to HA ") + self.ha_group
                except Exception as ha_err:
                    msg += tr(", but HA error: {}").format(ha_err)

            try:
                self.signals.vm_created.emit(msg)
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug("backend error: %s", e)
            try:
                self.signals.vm_error.emit(_sanitize_error(e))
            except RuntimeError:
                pass
        finally:
            if provider:
                provider.close()
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass
class DeleteVmSignals(QObject):
    vm_deleted = Signal(str)  # success message
    vm_error = Signal(str)    # error message
    finished = Signal()
class DeleteVmWorker(QRunnable):
    """Deletes a QEMU VM or LXC container via DELETE /nodes/{node}/{qemu|lxc}/{vmid}."""
    def __init__(self, host_cfg, node_name, vmid, vm_type="qemu"):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.vmid = vmid
        self.vm_type = vm_type
        self.signals = DeleteVmSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=30)
            vm_api = provider.vms
            ok, err = _await_task(
                provider, self.node_name,
                vm_api.delete(self.node_name, self.vmid, self.vm_type, purge=True),
                timeout=600,
            )
            if not ok:
                try:
                    self.signals.vm_error.emit(
                        tr("VM delete failed: {err}").format(err=err)
                    )
                except RuntimeError:
                    pass
                return
            msg = tr("VM {vmid} deleted from {node}").format(vmid=self.vmid, node=self.node_name)
            try:
                self.signals.vm_deleted.emit(msg)
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug("backend error: %s", e)
            try:
                self.signals.vm_error.emit(_sanitize_error(e))
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
# HaResourcesWorker — GET /cluster/ha/resources
# ----------------------------------------------------------------------
class MigrateVmSignals(QObject):
    vm_migrated = Signal(str)
    vm_error = Signal(str)
    finished = Signal()
class MigrateVmWorker(QRunnable):
    """Migrate QEMU VM or LXC container to another node in cluster.
    QEMU: POST /nodes/{node}/qemu/{vmid}/migrate {target: ...}
    LXC:  not supported by PVE API — emit error."""
    def __init__(self, host_cfg, node_name, vmid, vm_type, target_node,
                 with_local_disks=True):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.vmid = vmid
        self.vm_type = vm_type
        self.target_node = target_node
        self.with_local_disks = with_local_disks
        self.signals = MigrateVmSignals()

    def run(self):
        if self.vm_type == "lxc":
            try:
                self.signals.vm_error.emit(
                    tr("Live migration of containers (LXC) is not supported by PVE")
                )
            except RuntimeError:
                pass
            return
        try:
            provider = None
            provider = create_provider(self.host_cfg, timeout=120)
            vm_api = provider.vms
            vm_api.migrate(self.node_name, self.vmid, self.target_node,
                           self.with_local_disks)
            msg = tr("VM {vmid} migration to {target} started").format(
                vmid=self.vmid, target=self.target_node)
            try:
                self.signals.vm_migrated.emit(msg)
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug("migrate error: %s", e)
            try:
                self.signals.vm_error.emit(_sanitize_error(e))
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
# CloneVmWorker — clone QEMU VM or LXC container
# ----------------------------------------------------------------------
class CloneVmSignals(QObject):
    vm_cloned = Signal(str)
    vm_error = Signal(str)
    finished = Signal()
class CloneVmWorker(QRunnable):
    """Clone QEMU VM or LXC container.
    QEMU: POST /nodes/{node}/qemu/{vmid}/clone {newid, name, target, full, storage}
    LXC:  POST /nodes/{node}/lxc/{vmid}/clone {newid, hostname, target, storage}"""
    def __init__(self, host_cfg, node_name, vmid, vm_type, params):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.vmid = vmid
        self.vm_type = vm_type
        self.params = params
        self.signals = CloneVmSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=120)
            cluster_api = provider.cluster
            vm_api = provider.vms

            params = dict(self.params)
            if not params.get("newid"):
                params["newid"] = cluster_api.next_vmid()

            if self.vm_type == "lxc":
                clone_params = {
                    "newid": params["newid"],
                    "target": params.get("target", self.node_name),
                }
                if params.get("name"):
                    clone_params["hostname"] = params["name"]
                if params.get("storage"):
                    clone_params["storage"] = params["storage"]
                if params.get("full"):
                    clone_params["full"] = 1
            else:
                clone_params = {
                    "newid": params["newid"],
                    "target": params.get("target", self.node_name),
                }
                if params.get("name"):
                    clone_params["name"] = params["name"]
                if params.get("full"):
                    clone_params["full"] = 1
                if params.get("storage"):
                    clone_params["storage"] = params["storage"]
            ok, err = _await_task(
                provider, self.node_name,
                vm_api.clone(self.node_name, self.vmid, self.vm_type, **clone_params),
                timeout=900,
            )
            if not ok:
                try:
                    self.signals.vm_error.emit(
                        tr("Clone failed: {err}").format(err=err)
                    )
                except RuntimeError:
                    pass
                return
            newid = params.get("newid", "?")
            msg = tr("VM {vmid} cloned to {newid} on {target}").format(
                vmid=self.vmid, newid=newid,
                target=params.get("target", self.node_name))
            try:
                self.signals.vm_cloned.emit(msg)
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug("clone error: %s", e)
            try:
                self.signals.vm_error.emit(_sanitize_error(e))
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
# ConvertToTemplateWorker — convert QEMU VM to template
# POST /nodes/{node}/qemu/{vmid}/template
# ----------------------------------------------------------------------
class ConvertToTemplateSignals(QObject):
    result = Signal(str)
    error = Signal(str)
    finished = Signal()
class ConvertToTemplateWorker(QRunnable):
    """Convert a QEMU VM to a template.
    Only QEMU is supported (LXC has no template conversion in PVE API).
    The VM must be stopped before conversion."""
    def __init__(self, host_cfg, node_name, vmid):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.vmid = vmid
        self.signals = ConvertToTemplateSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=30)
            vm_api = provider.vms
            ok, err = _await_task(
                provider, self.node_name,
                vm_api.convert_to_template(self.node_name, self.vmid),
                timeout=120,
            )
            if not ok:
                try:
                    self.signals.error.emit(
                        tr("Convert to template failed: {err}").format(err=err)
                    )
                except RuntimeError:
                    pass
                return
            msg = tr("VM {vmid} converted to template").format(vmid=self.vmid)
            try:
                self.signals.result.emit(msg)
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug("convert-to-template error: %s", e)
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
# ConvertToVmWorker — convert template back to VM
# DELETE template flag via config update: POST /nodes/{node}/qemu/{vmid}/config {template: 0}
# ----------------------------------------------------------------------
class ConvertToVmSignals(QObject):
    result = Signal(str)
    error = Signal(str)
    finished = Signal()
class ConvertToVmWorker(QRunnable):
    """Convert a QEMU template back to a regular VM by clearing the template flag."""
    def __init__(self, host_cfg, node_name, vmid):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.vmid = vmid
        self.signals = ConvertToVmSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=30)
            vm_api = provider.vms
            ok, err = _await_task(
                provider, self.node_name,
                vm_api.post_config(self.node_name, self.vmid, "qemu", template=0),
                timeout=120,
            )
            if not ok:
                try:
                    self.signals.error.emit(
                        tr("Convert to VM failed: {err}").format(err=err)
                    )
                except RuntimeError:
                    pass
                return
            msg = tr("Template {vmid} converted to VM").format(vmid=self.vmid)
            try:
                self.signals.result.emit(msg)
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug("convert-to-vm error: %s", e)
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
# StorageContentDeleteWorker — destroy disk image via DELETE /storage/{storage}/content/{volid}
# ----------------------------------------------------------------------
class VmRestoreSignals(QObject):
    result = Signal(str)
    error = Signal(str)
    finished = Signal()
class VmRestoreWorker(QRunnable):
    def __init__(self, host_cfg, node_name, vmid, vm_type, archive,
                 storage="", name="", force=False, unique=False, timeout=3600):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.vmid = vmid
        self.vm_type = vm_type
        self.archive = archive
        self.storage = storage
        self.name = name
        self.force = force
        self.unique = unique
        self.timeout = timeout
        self.signals = VmRestoreSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=10)
            vm_api = provider.vms
            params = {
                "vmid": int(self.vmid),
                "archive": self.archive,
                "force": 1 if self.force else 0,
            }
            if self.storage:
                params["storage"] = self.storage
            if self.vm_type == "lxc":
                if self.name:
                    params["hostname"] = self.name
                result = vm_api.create_lxc(self.node_name, **params)
            else:
                if self.name:
                    params["name"] = self.name
                if self.unique:
                    params["unique"] = 1
                result = vm_api.create_qemu(self.node_name, **params)
            ok, err = _await_task(provider, self.node_name, result, timeout=self.timeout)
            if ok:
                _safe_emit(self.signals.result,
                           tr("Restore completed for VM {vmid}").format(vmid=self.vmid))
            else:
                _safe_emit(self.signals.error, tr("Restore failed: {err}").format(err=err))
        except Exception as e:
            logger.debug("restore error: %s", e)
            _safe_emit(self.signals.error, _sanitize_error(e))
        finally:
            if provider:
                provider.close()
            _safe_emit(self.signals.finished)

# ----------------------------------------------------------------------
# Cluster jobs — GET /cluster/backup (PVE7) or /cluster/jobs (PVE8+)
# ----------------------------------------------------------------------
