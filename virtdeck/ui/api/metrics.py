import concurrent.futures
import logging
import threading
import urllib.parse

import requests
from PySide6.QtCore import QObject, QRunnable, Signal

from ...backend import _suppress_ssl_warnings
from ...plugins import create_provider
from ...provider._session import build_requests_session
from ..i18n import tr

logger = logging.getLogger(__name__)

# PVE API default port — keep in sync with backend.py
PVE_PORT = 8006


def _verify_ssl(cfg):
    """Return verify_ssl value for requests.
    trust_ssl=False (default) → strict verification, verify_ssl=True.
    trust_ssl=True → accept any cert, verify_ssl=False."""
    trust = cfg.get("trust_ssl", False)
    if trust:
        _suppress_ssl_warnings()
    return not bool(trust)


def _check_response(resp):
    """Check HTTP response and extract error body from PVE JSON."""
    if not resp.ok:
        try:
            body = resp.json()
            msg = body.get('data', {}).get('message', '') or body.get('message', '')
        except Exception:
            msg = ''
        raise Exception(f"HTTP {resp.status_code}: {msg or resp.reason}"[:500])


class _FinishedMixin(QObject):
    """Add finished-signal to any worker Signals class."""

    finished = Signal()


class MetricsSignals(_FinishedMixin):
    # timeframe, vmid, metrics_dict
    data_fetched = Signal(str, int, dict)
    error_occurred = Signal(str)

class HostMetricsSignals(_FinishedMixin):
    data_fetched = Signal(str, str, dict)  # timeframe, node_name, metrics_dict
    error_occurred = Signal(str)

class StorageMetricsWorker(QRunnable):
    """Fetch RRD data for a storage (fill level over time)."""
    def __init__(self, host_cfg, node_name, storage_name, timeframe='hour'):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.storage_name = storage_name
        self.timeframe = timeframe
        self.signals = HostMetricsSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=10)
            rrd_api = provider.rrd
            rrd_response = rrd_api.get_storage_rrddata(
                self.node_name, self.storage_name, self.timeframe
            )

            metrics = {'usage': []}
            for entry in rrd_response:
                t = entry.get('time')
                val = entry.get('used')
                if t is not None and val is not None:
                    metrics['usage'].append({'time': t, 'value': val / (1024**3)})
            try:
                self.signals.data_fetched.emit(self.timeframe, self.node_name, metrics)
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug("metrics error", exc_info=True)
            try:
                self.signals.error_occurred.emit(str(e))
            except RuntimeError:
                pass
        finally:
            if provider:
                provider.close()
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass


class ContentListSignals(_FinishedMixin):
    result = Signal(str, str, list)  # storage_name, content_type, list of vol dicts
    error = Signal(str, str, str)

class StorageContentListWorker(QRunnable):
    def __init__(self, host_cfg, node_name, storage_name, content_type):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.storage_name = storage_name
        self.content_type = content_type
        self.signals = ContentListSignals()

    def run(self):
        session = build_requests_session(self.host_cfg)
        try:
            session.verify = _verify_ssl(self.host_cfg)
            auth_token = (f"PVEAPIToken={self.host_cfg['user']}!{self.host_cfg['token_name']}={self.host_cfg['token_value']}")
            headers = {"Authorization": auth_token}
            encoded_name = urllib.parse.quote(self.storage_name, safe='')
            url = (f"https://{self.host_cfg['host']}:{PVE_PORT}/api2/json/"
                   f"nodes/{self.node_name}/storage/{encoded_name}/content")
            resp = session.get(url, headers=headers, params={"content": self.content_type}, verify=_verify_ssl(self.host_cfg), timeout=60, allow_redirects=False)
            _check_response(resp)
            data = resp.json().get('data', [])
            try:
                self.signals.result.emit(self.storage_name, self.content_type, data)
            except RuntimeError:
                pass
        except requests.exceptions.ReadTimeout:
            try:
                self.signals.error.emit(self.storage_name, self.content_type, "PVE timeout loading storage content")
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug("metrics error", exc_info=True)
            try:
                self.signals.error.emit(self.storage_name, self.content_type, str(e))
            except RuntimeError:
                pass
        finally:
            session.close()
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass


class BackupSignals(_FinishedMixin):
    backups_ready = Signal(str, list)
    backups_error = Signal(str, str)

class StorageBackupWorker(QRunnable):
    def __init__(self, host_cfg, node_name, storage_name):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.storage_name = storage_name
        self.signals = BackupSignals()

    def run(self):
        session = build_requests_session(self.host_cfg)
        try:
            session.verify = _verify_ssl(self.host_cfg)
            auth_token = (f"PVEAPIToken={self.host_cfg['user']}!{self.host_cfg['token_name']}={self.host_cfg['token_value']}")
            headers = {"Authorization": auth_token}
            encoded_name = urllib.parse.quote(self.storage_name, safe='')
            url = (f"https://{self.host_cfg['host']}:{PVE_PORT}/api2/json/"
                   f"nodes/{self.node_name}/storage/{encoded_name}/content")
            resp = session.get(url, headers=headers, params={"content": "backup"}, verify=_verify_ssl(self.host_cfg), timeout=60, allow_redirects=False)
            _check_response(resp)
            data = resp.json().get('data', [])
            try:
                self.signals.backups_ready.emit(self.storage_name, data)
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug("metrics error", exc_info=True)
            try:
                self.signals.backups_error.emit(self.storage_name, str(e))
            except RuntimeError:
                pass
        finally:
            session.close()
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass


class NetworkSignals(_FinishedMixin):
    network_ready = Signal(str, list)
    network_error = Signal(str, str)

class HostNetworkWorker(QRunnable):
    def __init__(self, host_cfg, node_name):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.signals = NetworkSignals()

    def run(self):
        session = build_requests_session(self.host_cfg)
        try:
            session.verify = _verify_ssl(self.host_cfg)
            auth_token = (
                f"PVEAPIToken={self.host_cfg['user']}!"
                f"{self.host_cfg['token_name']}={self.host_cfg['token_value']}"
            )
            headers = {"Authorization": auth_token}
            url = (f"https://{self.host_cfg['host']}:{PVE_PORT}/api2/json/"
                   f"nodes/{self.node_name}/network")
            resp = session.get(url, headers=headers, verify=_verify_ssl(self.host_cfg), timeout=10, allow_redirects=False)
            _check_response(resp)
            data = resp.json().get('data', [])
            try:
                self.signals.network_ready.emit(self.node_name, data)
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug("metrics error", exc_info=True)
            try:
                self.signals.network_error.emit(self.node_name, str(e))
            except RuntimeError:
                pass
        finally:
            session.close()
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass


class ServicesSignals(_FinishedMixin):
    services_ready = Signal(str, list)
    services_error = Signal(str, str)

class HostServicesWorker(QRunnable):
    def __init__(self, host_cfg, node_name):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.signals = ServicesSignals()

    def run(self):
        session = build_requests_session(self.host_cfg)
        try:
            session.verify = _verify_ssl(self.host_cfg)
            auth_token = (
                f"PVEAPIToken={self.host_cfg['user']}!"
                f"{self.host_cfg['token_name']}={self.host_cfg['token_value']}"
            )
            headers = {"Authorization": auth_token}
            url = (f"https://{self.host_cfg['host']}:{PVE_PORT}/api2/json/"
                   f"nodes/{self.node_name}/services")
            resp = session.get(url, headers=headers, verify=_verify_ssl(self.host_cfg), timeout=10, allow_redirects=False)
            _check_response(resp)
            data = resp.json().get('data', [])
            try:
                self.signals.services_ready.emit(self.node_name, data)
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug("metrics error", exc_info=True)
            try:
                self.signals.services_error.emit(self.node_name, str(e))
            except RuntimeError:
                pass
        finally:
            session.close()
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass


class DisksSignals(_FinishedMixin):
    disks_ready = Signal(str, list)
    disks_error = Signal(str, str)

class HostDisksWorker(QRunnable):
    def __init__(self, host_cfg, node_name):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.signals = DisksSignals()

    def run(self):
        session = build_requests_session(self.host_cfg)
        try:
            session.verify = _verify_ssl(self.host_cfg)
            auth_token = (
                f"PVEAPIToken={self.host_cfg['user']}!"
                f"{self.host_cfg['token_name']}={self.host_cfg['token_value']}"
            )
            headers = {"Authorization": auth_token}
            url = (f"https://{self.host_cfg['host']}:{PVE_PORT}/api2/json/"
                   f"nodes/{self.node_name}/disks/list")
            resp = session.get(url, headers=headers, verify=_verify_ssl(self.host_cfg), timeout=10, allow_redirects=False)
            _check_response(resp)
            data = resp.json().get('data', [])
            try:
                self.signals.disks_ready.emit(self.node_name, data)
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug("metrics error", exc_info=True)
            try:
                self.signals.disks_error.emit(self.node_name, str(e))
            except RuntimeError:
                pass
        finally:
            session.close()
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass


class SnapshotSignals(_FinishedMixin):
    snapshots_ready = Signal(str, list)
    snapshots_error = Signal(str, str)


_DISK_PREFIXES = ("scsi", "ide", "sata", "virtio", "efidisk")


def _parse_disk_size(val_str):
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


class HostSnapshotsWorker(QRunnable):
    def __init__(self, host_cfg, node_name, vms):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.vms = vms
        self.signals = SnapshotSignals()

    def run(self):
        try:
            auth_token = (
                f"PVEAPIToken={self.host_cfg['user']}!"
                f"{self.host_cfg['token_name']}={self.host_cfg['token_value']}"
            )
            headers = {"Authorization": auth_token}
            base = f"https://{self.host_cfg['host']}:{PVE_PORT}/api2/json"
            all_snapshots = []
            lock = threading.Lock()

            def fetch_vm_snapshots(vm):
                vmid = vm.vmid
                vm_type = vm.vm_type.value
                vm_name = vm.name or ""
                if not vmid:
                    return
                s = build_requests_session(self.host_cfg)
                try:
                    s.verify = _verify_ssl(self.host_cfg)
                    enc_node = urllib.parse.quote(self.node_name, safe="")
                    url = f"{base}/nodes/{enc_node}/{vm_type}/{vmid}/snapshot"
                    r = s.get(url, headers=headers, verify=_verify_ssl(self.host_cfg), timeout=10, allow_redirects=False)
                    _check_response(r)
                    data = r.json().get("data", [])
                    vm_snaps = []
                    for snap in data:
                        if snap.get("name") == "current":
                            continue
                        snap["vmid"] = vmid
                        snap["vm_name"] = vm_name
                        snap["host_name"] = vm.host_name
                        snap["node"] = vm.node or self.node_name
                        snap["size"] = 0
                        vm_snaps.append(dict(snap))
                    for snap in vm_snaps:
                        snap_name = snap.get("name", "")
                        if not snap_name:
                            continue
                        try:
                            cfg_url = f"{url}/{urllib.parse.quote(snap_name, safe='')}/config"
                            rc = s.get(cfg_url, headers=headers, verify=_verify_ssl(self.host_cfg), timeout=10, allow_redirects=False)
                            _check_response(rc)
                            cfg = rc.json().get("data", {})
                            total_bytes = 0
                            for key, val in cfg.items():
                                if not isinstance(val, str):
                                    continue
                                if any(key.startswith(p) for p in _DISK_PREFIXES):
                                    total_bytes += _parse_disk_size(val)
                            snap["size"] = total_bytes
                        except Exception:
                            pass
                    with lock:
                        all_snapshots.extend(vm_snaps)
                except Exception:
                    pass
                finally:
                    s.close()

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(fetch_vm_snapshots, self.vms))

            all_snapshots.sort(key=lambda s: (s.get("vmid", 0), s.get("snaptime", 0) or 0))
            try:
                self.signals.snapshots_ready.emit(self.node_name, all_snapshots)
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug("metrics error", exc_info=True)
            try:
                self.signals.snapshots_error.emit(self.node_name, str(e))
            except RuntimeError:
                pass
        finally:
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass


class DiskSignals(_FinishedMixin):
    disks_ready = Signal(str, list)
    disks_error = Signal(str, str)

class StorageDisksWorker(QRunnable):
    """Collect guest disks on the given storage from VM configs (in parallel)."""
    def __init__(self, host_cfg, node_name, storage_name, all_vms):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.storage_name = storage_name
        self.all_vms = all_vms
        self.signals = DiskSignals()

    def run(self):
        try:
            auth_token = (
                f"PVEAPIToken={self.host_cfg['user']}!"
                f"{self.host_cfg['token_name']}={self.host_cfg['token_value']}"
            )
            headers = {"Authorization": auth_token}
            base = f"https://{self.host_cfg['host']}:{PVE_PORT}/api2/json"
            prefix = self.storage_name + ":"
            disks = []
            lock = threading.Lock()

            def fetch_vm_config(vm):
                vmid = vm.vmid
                vm_node = vm.node
                if not vmid or not vm_node:
                    return
                s = build_requests_session(self.host_cfg)
                try:
                    s.verify = _verify_ssl(self.host_cfg)
                    enc_node = urllib.parse.quote(vm_node, safe="")
                    vm_type = vm.vm_type.value
                    r = s.get(
                        f"{base}/nodes/{enc_node}/{vm_type}/{vmid}/config",
                        headers=headers, verify=_verify_ssl(self.host_cfg), timeout=10
                    )
                    _check_response(r)
                    config = r.json().get("data", {})
                    vm_name = vm.name or ""

                    for key, val in config.items():
                        val_str = str(val)
                        if ":" in val_str and val_str.startswith(prefix):
                            # Skip CDROM (ISO images)
                            if "media=cdrom" in val_str:
                                continue
                            volpath = val_str.split(",")[0]
                            volparts = volpath.split(":", 1)
                            if len(volparts) == 2:
                                volid = volparts[1]
                                size_bytes = 0
                                for part in str(val).split(","):
                                    part = part.strip()
                                    if part.startswith("size="):
                                        size_str = part.split("=", 1)[1]
                                        size_bytes = self._parse_size(size_str)
                                        break
                                with lock:
                                    disks.append({
                                        "vmid": vmid,
                                        "vm_name": vm_name,
                                        "volid": f"{self.storage_name}:{volid}",
                                        "bus": key,
                                        "size": size_bytes,
                                        "host_name": vm.host_name,
                                        "node": vm_node,
                                    })
                except Exception:
                    pass
                finally:
                    s.close()

            # executor.map returns a lazy iterator — without list() the futures
            # are never created and threads never start. The result list is not
            # needed, but the iterator must be materialized so workers run.
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(fetch_vm_config, self.all_vms))

            try:
                self.signals.disks_ready.emit(self.storage_name, disks)
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug("metrics error", exc_info=True)
            try:
                self.signals.disks_error.emit(self.storage_name, str(e))
            except RuntimeError:
                pass
        finally:
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass

    @staticmethod
    def _parse_size(size_str):
        """Parse PVE size string like '32G', '512M', '1T' to bytes."""
        size_str = str(size_str).strip().upper()
        if size_str.endswith("T"):
            return int(float(size_str[:-1]) * 1024**4)
        elif size_str.endswith("G"):
            return int(float(size_str[:-1]) * 1024**3)
        elif size_str.endswith("M"):
            return int(float(size_str[:-1]) * 1024**2)
        elif size_str.endswith("K"):
            return int(float(size_str[:-1]) * 1024)
        else:
            try:
                return int(float(size_str))
            except ValueError:
                return 0


class HostMetricsWorker(QRunnable):
    """Fetch RRD data for a Proxmox node (CPU, RAM, network)."""
    def __init__(self, host_cfg, node_name, timeframe='hour'):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.timeframe = timeframe
        self.signals = HostMetricsSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=10)
            rrd_api = provider.rrd
            rrd_response = rrd_api.get_node_rrddata(self.node_name, self.timeframe)

            metrics = {
                'cpu': [],
                'mem': [],
                'netin': [],
                'netout': [],
            }
            for entry in rrd_response:
                t = entry.get('time')
                if t is None:
                    continue
                for key in metrics.keys():
                    field = 'memused' if key == 'mem' else key
                    if field in entry and entry[field] is not None:
                        metrics[key].append({'time': t, 'value': entry[field]})
            try:
                self.signals.data_fetched.emit(self.timeframe, self.node_name, metrics)
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug("metrics error", exc_info=True)
            try:
                self.signals.error_occurred.emit(str(e))
            except RuntimeError:
                pass
        finally:
            if provider:
                provider.close()
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass


class MetricsWorker(QRunnable):
    """Fetch RRD data for a VM/CT (CPU, RAM, network, disk)."""
    def __init__(self, host_cfg, node_name, vmid, vm_type='qemu', timeframe='hour'):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.vmid = vmid
        self.vm_type = vm_type
        self.timeframe = timeframe
        self.signals = MetricsSignals()

    def run(self):
        provider = None
        try:
            provider = create_provider(self.host_cfg, timeout=10)
            rrd_api = provider.rrd
            rrd_response = rrd_api.get_vm_rrddata(
                self.node_name, self.vmid, self.vm_type, self.timeframe
            )

            metrics = {
                'cpu': [],
                'mem': [],
                'netin': [],
                'netout': [],
                'diskread': [],
                'diskwrite': []
            }
            for entry in rrd_response:
                t = entry.get('time')
                if t is None:
                    continue
                for key in metrics.keys():
                    if key in entry and entry[key] is not None:
                        metrics[key].append({'time': t, 'value': entry[key]})
            try:
                self.signals.data_fetched.emit(self.timeframe, self.vmid, metrics)
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug("metrics error", exc_info=True)
            try:
                self.signals.error_occurred.emit(str(e))
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
# Health Check Worker — collects subscription, updates, services status
# ----------------------------------------------------------------------

_CRITICAL_SERVICES = {
    "pvestatd", "pvedaemon", "pveproxy", "pve-cluster",
    "pve-firewall", "corosync", "pve-ha-crm", "pve-ha-lrm",
}

_CPU_WARN = 0.70
_CPU_CRIT = 0.90
_MEM_WARN = 0.70
_MEM_CRIT = 0.85
_DISK_WARN = 0.70
_DISK_CRIT = 0.85


class HealthCheckSignals(_FinishedMixin):
    health_ready = Signal(str, dict)  # node_name, health_data
    health_error = Signal(str, str)   # node_name, error


class HealthCheckWorker(QRunnable):
    """Collects node health: CPU/mem/disk thresholds, services, subscription, updates."""

    def __init__(self, host_cfg, node_name, node_status=None):
        super().__init__()
        self.host_cfg = host_cfg
        self.node_name = node_name
        self.node_status = node_status or {}
        self.signals = HealthCheckSignals()

    def run(self):
        session = build_requests_session(self.host_cfg)
        try:
            session.verify = _verify_ssl(self.host_cfg)
            auth_token = (
                f"PVEAPIToken={self.host_cfg['user']}!"
                f"{self.host_cfg['token_name']}={self.host_cfg['token_value']}"
            )
            headers = {"Authorization": auth_token}
            base = f"https://{self.host_cfg['host']}:{PVE_PORT}/api2/json"

            issues = []
            warnings = []

            cpu_frac = self.node_status.get("cpu", 0) or 0
            if isinstance(cpu_frac, (int, float)):
                if cpu_frac >= _CPU_CRIT:
                    issues.append(tr("CPU usage {pct}% (critical)").format(
                        pct=round(cpu_frac * 100, 1)))
                elif cpu_frac >= _CPU_WARN:
                    warnings.append(tr("CPU usage {pct}% (high)").format(
                        pct=round(cpu_frac * 100, 1)))

            mem = self.node_status.get("mem", 0) or 0
            maxmem = self.node_status.get("maxmem", 0) or 0
            if maxmem and isinstance(mem, (int, float)):
                mem_ratio = mem / maxmem
                if mem_ratio >= _MEM_CRIT:
                    issues.append(tr("Memory usage {pct}% (critical)").format(
                        pct=round(mem_ratio * 100, 1)))
                elif mem_ratio >= _MEM_WARN:
                    warnings.append(tr("Memory usage {pct}% (high)").format(
                        pct=round(mem_ratio * 100, 1)))

            disk = self.node_status.get("disk", 0) or 0
            maxdisk = self.node_status.get("maxdisk", 0) or 0
            if maxdisk and isinstance(disk, (int, float)):
                disk_ratio = disk / maxdisk
                if disk_ratio >= _DISK_CRIT:
                    issues.append(tr("Root disk usage {pct}% (critical)").format(
                        pct=round(disk_ratio * 100, 1)))
                elif disk_ratio >= _DISK_WARN:
                    warnings.append(tr("Root disk usage {pct}% (high)").format(
                        pct=round(disk_ratio * 100, 1)))

            try:
                resp = session.get(f"{base}/nodes/{self.node_name}/services",
                                   headers=headers, timeout=10, allow_redirects=False)
                _check_response(resp)
                services = resp.json().get("data", [])
                for svc in services:
                    name = svc.get("name", "")
                    state = svc.get("state", "")
                    if name in _CRITICAL_SERVICES and state != "running":
                        issues.append(tr("Service {svc} is not running").format(svc=name))
            except Exception as e:
                logger.debug("health services error: %s", e)

            try:
                resp = session.get(f"{base}/nodes/{self.node_name}/subscription",
                                   headers=headers, timeout=10, allow_redirects=False)
                _check_response(resp)
                sub = resp.json().get("data", {})
                sub_status = sub.get("status", "")
                if sub_status in ("expired", "invalid", "suspended"):
                    issues.append(tr("Subscription {status}").format(status=sub_status))
            except Exception as e:
                logger.debug("health subscription error: %s", e)

            try:
                resp = session.get(f"{base}/nodes/{self.node_name}/apt/update",
                                   headers=headers, timeout=10, allow_redirects=False)
                _check_response(resp)
                updates = resp.json().get("data", [])
                if updates:
                    warnings.append(tr("{count} package updates available").format(
                        count=len(updates)))
            except Exception as e:
                logger.debug("health updates error: %s", e)

            if not issues and not warnings:
                status = "healthy"
            elif issues:
                status = "critical"
            else:
                status = "warning"

            health = {
                "status": status,
                "issues": issues,
                "warnings": warnings,
            }
            try:
                self.signals.health_ready.emit(self.node_name, health)
            except RuntimeError:
                pass
        except Exception as e:
            logger.debug("health check error", exc_info=True)
            try:
                self.signals.health_error.emit(self.node_name, str(e))
            except RuntimeError:
                pass
        finally:
            session.close()
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass
