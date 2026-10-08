"""Storage workers: content ops (delete, upload, download-url, move,
vzdump) and cluster storage config CRUD (B4)."""

import logging
import os

from PySide6.QtCore import QObject, QRunnable, Signal

from ..plugins import create_provider
from ..ui.i18n import tr
from .core import _await_task, _safe_emit, _sanitize_error

logger = logging.getLogger(__name__)

class StorageContentDeleteSignals(QObject):
    result = Signal(str)
    error = Signal(str)
    finished = Signal()
class StorageContentDeleteWorker(QRunnable):
    def __init__(self, host_cfg, node_name, storage, volid, timeout=120):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.storage = storage
        self.volid = volid
        self.timeout = timeout
        self.signals = StorageContentDeleteSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=10)
            storage_api = provider.storage
            ok, err = _await_task(
                provider, self.node_name,
                storage_api.delete_content(self.node_name, self.storage, self.volid),
                timeout=self.timeout,
            )
            if ok:
                try:
                    self.signals.result.emit(
                        tr("File deleted: {volid}").format(volid=self.volid)
                    )
                except RuntimeError:
                    pass
            else:
                try:
                    self.signals.error.emit(
                        tr("Delete failed: {err}").format(err=err)
                    )
                except RuntimeError:
                    pass
        except Exception as e:
            logger.debug("storage content delete error: %s", e)
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
class StorageUploadSignals(QObject):
    progress = Signal(int)
    result = Signal(str)
    error = Signal(str)
    finished = Signal()
class StorageUploadWorker(QRunnable):
    def __init__(self, host_cfg, node_name, storage_name, content_type, file_path, timeout=300):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.storage_name = storage_name
        self.content_type = content_type
        self.file_path = file_path
        self.timeout = timeout
        self.signals = StorageUploadSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=10)
            storage_api = provider.storage
            file_name = os.path.basename(self.file_path)

            def progress_cb(pct: int) -> None:
                _safe_emit(self.signals.progress, pct)

            ok, err = _await_task(
                provider, self.node_name,
                storage_api.upload_file(
                    self.node_name, self.storage_name, self.content_type,
                    self.file_path, timeout=self.timeout, progress_callback=progress_cb,
                ),
                timeout=self.timeout,
            )
            if ok:
                _safe_emit(
                    self.signals.result,
                    tr("Upload complete: {name}").format(name=file_name),
                )
            else:
                _safe_emit(
                    self.signals.error,
                    tr("Upload failed: {err}").format(err=err),
                )
        except Exception as e:
            logger.debug("upload error: %s", e)
            _safe_emit(self.signals.error, _sanitize_error(e))
        finally:
            if provider:
                provider.close()
            _safe_emit(self.signals.finished)

# ----------------------------------------------------------------------
# StorageDownloadUrlWorker — POST /nodes/{node}/storage/{storage}/download-url
# ----------------------------------------------------------------------
class StorageDownloadUrlSignals(QObject):
    result = Signal(str)
    error = Signal(str)
    finished = Signal()
class StorageDownloadUrlWorker(QRunnable):
    """Downloads a file from a URL onto storage via the PVE API.

    POST /nodes/{node}/storage/{storage}/download-url
    Parameters: url, content (iso/vztmpl), filename (optional), checksum (optional),
    verify-certificates (optional, default 1).
    """
    def __init__(self, host_cfg, node_name, storage_name, content_type, url,
                 filename=None, checksum=None, verify_certificates=True, timeout=600):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.storage_name = storage_name
        self.content_type = content_type
        self.url = url
        self.filename = filename
        self.checksum = checksum
        self.verify_certificates = verify_certificates
        self.timeout = timeout
        self.signals = StorageDownloadUrlSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=30)
            storage_api = provider.storage
            params = {
                "url": self.url,
                "content": self.content_type,
                "verify-certificates": 1 if self.verify_certificates else 0,
            }
            if self.filename:
                params["filename"] = self.filename
            if self.checksum:
                params["checksum"] = self.checksum
            ok, err = _await_task(
                provider, self.node_name,
                storage_api.download_url(self.node_name, self.storage_name, **params),
                timeout=self.timeout,
            )
            if ok:
                name = self.filename or self.url.split("/")[-1].split("?")[0] or "file"
                _safe_emit(self.signals.result,
                           tr("Download complete: {name}").format(name=name))
            else:
                _safe_emit(self.signals.error,
                           tr("Download failed: {err}").format(err=err))
        except Exception as e:
            logger.debug("download-url error: %s", e)
            _safe_emit(self.signals.error, _sanitize_error(e))
        finally:
            if provider:
                provider.close()
            _safe_emit(self.signals.finished)
class StorageMoveSignals(QObject):
    result = Signal(str)
    error = Signal(str)
    finished = Signal()
class StorageMoveWorker(QRunnable):
    def __init__(self, host_cfg, node_name, storage_name, volid,
                 target_storage, target_vmid=0, delete_source=False, timeout=300):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.storage_name = storage_name
        self.volid = volid
        self.target_storage = target_storage
        self.target_vmid = target_vmid
        self.delete_source = delete_source
        self.timeout = timeout
        self.signals = StorageMoveSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=10)
            storage_api = provider.storage
            ok, err = _await_task(
                provider, self.node_name,
                storage_api.move_content(
                    self.node_name, self.storage_name, self.volid,
                    self.target_storage, target_vmid=self.target_vmid,
                    delete_source=self.delete_source,
                ),
                timeout=self.timeout,
            )
            if ok:
                _safe_emit(self.signals.result,
                           tr("Move complete: {volid} → {storage}").format(
                               volid=self.volid, storage=self.target_storage))
            else:
                _safe_emit(self.signals.error, tr("Move failed: {err}").format(err=err))
        except Exception as e:
            logger.debug("move error: %s", e)
            _safe_emit(self.signals.error, _sanitize_error(e))
        finally:
            if provider:
                provider.close()
            _safe_emit(self.signals.finished)

# ----------------------------------------------------------------------
# VzdumpWorker — POST /nodes/{node}/vzdump (on-demand backup)
# ----------------------------------------------------------------------
class VzdumpSignals(QObject):
    result = Signal(str)
    error = Signal(str)
    finished = Signal()
class VzdumpWorker(QRunnable):
    def __init__(self, host_cfg, node_name, vmid, storage,
                 mode="snapshot", compress="0", notes="", remove=False,
                 bwlimit=0, timeout=3600):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.vmid = vmid
        self.storage = storage
        self.mode = mode
        self.compress = compress
        self.notes = notes
        self.remove = remove
        self.bwlimit = bwlimit
        self.timeout = timeout
        self.signals = VzdumpSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=10)
            node_api = provider.nodes
            params = {
                "vmid": str(self.vmid),
                "storage": self.storage,
                "mode": self.mode,
                "compress": self.compress,
            }
            if self.notes:
                params["notes"] = self.notes
            if self.remove:
                params["remove"] = 1
            if self.bwlimit > 0:
                params["bwlimit"] = self.bwlimit
            ok, err = _await_task(
                provider, self.node_name,
                node_api.backup_vzdump(self.node_name, **params),
                timeout=self.timeout,
            )
            if ok:
                _safe_emit(self.signals.result,
                           tr("Backup completed for VM {vmid}").format(vmid=self.vmid))
            else:
                _safe_emit(self.signals.error, tr("Backup failed: {err}").format(err=err))
        except Exception as e:
            logger.debug("vzdump error: %s", e)
            _safe_emit(self.signals.error, _sanitize_error(e))
        finally:
            if provider:
                provider.close()
            _safe_emit(self.signals.finished)

# ----------------------------------------------------------------------
# VmRestoreWorker — POST /nodes/{node}/qemu or /nodes/{node}/lxc (restore)
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
# Storage config CRUD (B4) — /storage
# ----------------------------------------------------------------------
class StorageConfigListSignals(QObject):
    result = Signal(list)
    error = Signal(str)
    finished = Signal()
class StorageConfigListWorker(QRunnable):
    """GET /storage — list all storage definitions."""
    def __init__(self, host_cfg, timeout=30):
        super().__init__()
        self.host_cfg = host_cfg
        self.timeout = timeout
        self.signals = StorageConfigListSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=10)
            configs = provider.cluster.list_storage_configs()
            _safe_emit(self.signals.result, configs or [])
        except Exception as e:
            logger.debug("storage config list error: %s", e)
            _safe_emit(self.signals.error, _sanitize_error(e))
        finally:
            if provider:
                provider.close()
            _safe_emit(self.signals.finished)


class StorageConfigSaveSignals(QObject):
    result = Signal(str)
    error = Signal(str)
    finished = Signal()
class StorageConfigSaveWorker(QRunnable):
    """POST (create) or PUT (update) /storage.

    ``storage`` None → create with params {"storage": id, ...};
    otherwise update the given storage id.
    """
    def __init__(self, host_cfg, storage, params, timeout=60):
        super().__init__()
        self.host_cfg = host_cfg
        self.storage = storage
        self.params = params
        self.timeout = timeout
        self.signals = StorageConfigSaveSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=10)
            if self.storage:
                ok, err = _await_task(
                    provider, None,
                    provider.cluster.update_storage(self.storage, **self.params),
                    timeout=self.timeout,
                )
                verb = tr("Storage updated: {name}")
            else:
                ok, err = _await_task(
                    provider, None,
                    provider.cluster.create_storage(**self.params),
                    timeout=self.timeout,
                )
                verb = tr("Storage created: {name}")
            name = self.params.get("storage", self.storage)
            if ok:
                _safe_emit(self.signals.result, verb.format(name=name))
            else:
                _safe_emit(self.signals.error, _sanitize_error(err))
        except Exception as e:
            logger.debug("storage config save error: %s", e)
            _safe_emit(self.signals.error, _sanitize_error(e))
        finally:
            if provider:
                provider.close()
            _safe_emit(self.signals.finished)


class StorageConfigDeleteSignals(QObject):
    result = Signal(str)
    error = Signal(str)
    finished = Signal()
class StorageConfigDeleteWorker(QRunnable):
    """DELETE /storage/{storage}."""
    def __init__(self, host_cfg, storage, timeout=60):
        super().__init__()
        self.host_cfg = host_cfg
        self.storage = storage
        self.timeout = timeout
        self.signals = StorageConfigDeleteSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=10)
            ok, err = _await_task(
                provider, None,
                provider.cluster.delete_storage(self.storage),
                timeout=self.timeout,
            )
            if ok:
                _safe_emit(self.signals.result,
                           tr("Storage deleted: {name}").format(name=self.storage))
            else:
                _safe_emit(self.signals.error, _sanitize_error(err))
        except Exception as e:
            logger.debug("storage config delete error: %s", e)
            _safe_emit(self.signals.error, _sanitize_error(e))
        finally:
            if provider:
                provider.close()
            _safe_emit(self.signals.finished)
