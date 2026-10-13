"""Domain model: Vm (QEMU VM or LXC container).

A frozen dataclass representing a PVE virtual machine or container
at a point in time.  Raw PVE API values are stored as-is; human-readable
representations are computed via read-only properties.
"""

from __future__ import annotations

from dataclasses import dataclass

from ._dictcompat import DictCompat
from ._format import format_uptime, safe_pct
from .enums import VmStatus, VmType


@dataclass(frozen=True)
class Vm(DictCompat):
    """A PVE virtual machine or container (list-level data).

    Represents the dict returned by ``/cluster/resources`` (cluster path)
    or ``/nodes/{node}/qemu`` + ``/nodes/{node}/lxc`` (standalone path).
    Detail status (``/status.current``) and config (``/config``) are
    separate concerns, fetched on demand — not modelled here.
    """

    _FIELD_MAP = {
        "vmid": "vmid",
        "name": "name",
        "type": "_type_value",
        "node": "node",
        "host_name": "host_name",
        "pool": "pool",
        "status": "_status_value",
        "hastate": "hastate",
        "tags": "tags",
        "template": "template",
        "cpu": "cpu_fraction",
        "mem": "mem_bytes",
        "maxmem": "maxmem_bytes",
        "disk": "disk_bytes",
        "maxdisk": "maxdisk_bytes",
        "uptime": "uptime_seconds",
        "netin": "netin_bytes",
        "netout": "netout_bytes",
        "diskread": "diskread_bytes",
        "diskwrite": "diskwrite_bytes",
        "conn_id": "conn_id",
    }

    # -- Identity --
    vmid: int
    """PVE VM/container ID."""

    name: str
    """VM name, empty string if absent."""

    vm_type: VmType
    """QEMU or LXC."""

    node: str
    """PVE node name where the VM runs."""

    host_name: str
    """virtdeck config name."""

    pool: str
    """Pool name, empty string if not in a pool."""

    # -- Status --
    status: VmStatus
    hastate: str
    """HA state string, empty if not in HA."""

    tags: str
    """Semicolon-separated tags."""

    template: bool
    """Whether this is a template."""

    # -- Resources (raw PVE values) --
    cpu_fraction: float
    """CPU usage 0.0-1.0."""

    mem_bytes: int
    maxmem_bytes: int
    disk_bytes: int
    """Used disk bytes (LXC only; 0 for QEMU)."""

    maxdisk_bytes: int
    uptime_seconds: int
    netin_bytes: int
    """Cumulative network-in bytes."""

    netout_bytes: int
    """Cumulative network-out bytes."""

    diskread_bytes: int
    """Cumulative disk-read bytes."""

    diskwrite_bytes: int
    """Cumulative disk-write bytes."""

    # -- Identity of the producing connection (stage 5.1.2) --
    conn_id: str = ""
    """conn_id of the config entry that fetched this row; the resource
    cache is identity-keyed on it. Empty for legacy rows."""

    # -- Computed properties --
    @property
    def cpu_pct(self) -> float:
        """CPU usage as percentage (0.0-100.0), rounded to 1 decimal."""
        return round(self.cpu_fraction * 100, 1) if self.cpu_fraction else 0.0

    @property
    def mem_gib(self) -> float:
        """Used memory in GiB, rounded to 2 decimals."""
        return round(self.mem_bytes / (1024**3), 2) if self.mem_bytes else 0.0

    @property
    def maxmem_gib(self) -> float:
        """Maximum memory in GiB, rounded to 2 decimals."""
        return round(self.maxmem_bytes / (1024**3), 2) if self.maxmem_bytes else 0.0

    @property
    def mem_pct(self) -> int:
        """Memory usage percentage (0-100)."""
        return safe_pct(self.mem_bytes, self.maxmem_bytes)

    @property
    def disk_gib(self) -> float:
        """Used disk in GiB, rounded to 2 decimals (meaningful for LXC only)."""
        return round(self.disk_bytes / (1024**3), 2) if self.disk_bytes else 0.0

    @property
    def maxdisk_gib(self) -> float:
        """Maximum disk in GiB, rounded to 2 decimals."""
        return round(self.maxdisk_bytes / (1024**3), 2) if self.maxdisk_bytes else 0.0

    @property
    def disk_pct(self) -> int:
        """Disk usage percentage (0-100, meaningful for LXC only)."""
        return safe_pct(self.disk_bytes, self.maxdisk_bytes)

    @property
    def cpu_text(self) -> str:
        """CPU usage formatted: '35.0%'."""
        return f"{self.cpu_pct}%"

    @property
    def ram_text(self) -> str:
        """Memory usage formatted: '2.0/4.0 GiB'."""
        return f"{self.mem_gib}/{self.maxmem_gib} GiB"

    @property
    def disk_text(self) -> str:
        """Disk usage formatted: '1.0/16.0 GiB' (meaningful for LXC only)."""
        return f"{self.disk_gib}/{self.maxdisk_gib} GiB"

    @property
    def netin_mib(self) -> float:
        """Cumulative network-in in MiB, rounded to 2 decimals."""
        return round(self.netin_bytes / (1024**2), 2) if self.netin_bytes else 0.0

    @property
    def netout_mib(self) -> float:
        """Cumulative network-out in MiB, rounded to 2 decimals."""
        return round(self.netout_bytes / (1024**2), 2) if self.netout_bytes else 0.0

    @property
    def uptime_str(self) -> str:
        """Human-readable uptime like '5d 3h 20m 10s', or '—' if zero."""
        return format_uptime(self.uptime_seconds) if self.uptime_seconds else "—"

    @property
    def display_name(self) -> str:
        """Display name: name if present, else 'VM {vmid}'."""
        return self.name or f"VM {self.vmid}"

    @property
    def status_color(self) -> str:
        """Color tag for UI: 'ok', 'err', 'warn'."""
        if self.status is VmStatus.RUNNING:
            return "ok"
        if self.status is VmStatus.STOPPED:
            return "err"
        return "warn"

    @property
    def is_lxc(self) -> bool:
        """Whether this is an LXC container."""
        return self.vm_type is VmType.LXC

    @property
    def is_qemu(self) -> bool:
        """Whether this is a QEMU VM."""
        return self.vm_type is VmType.QEMU

    @property
    def key(self) -> tuple[str, int]:
        """Tuple (host_name, vmid) for indexing."""
        return (self.host_name, self.vmid)

    @property
    def status_value(self) -> str:
        """Raw status string for CardRow dot matching ('running', 'stopped', ...)."""
        return self.status.value

    @property
    def _status_value(self) -> str:
        """Alias for status_value — used by _FIELD_MAP for dict-compat."""
        return self.status.value

    @property
    def _type_value(self) -> str:
        """Raw type string ('qemu', 'lxc') — used by _FIELD_MAP for dict-compat."""
        return self.vm_type.value

    @property
    def _key(self) -> str:
        """Unique row key for CardList matching."""
        return str(self.vmid)

    # -- Factory --
    @staticmethod
    def from_pve(d: dict, host_name: str) -> Vm:
        """Build a Vm from a raw PVE API dict.

        Missing fields default to zero/empty — never raises on shape.
        ``host_name`` is the virtdeck config name (set by MainWindow,
        not by the API).
        """
        return Vm(
            vmid=d.get("vmid", 0) or 0,
            name=d.get("name", "") or "",
            vm_type=VmType.from_pve(d.get("type")),
            node=d.get("node", "") or "",
            host_name=host_name,
            pool=d.get("pool", "") or "",
            status=VmStatus.from_pve(d.get("status")),
            hastate=d.get("hastate", "") or "",
            tags=d.get("tags", "") or "",
            template=bool(d.get("template")),
            cpu_fraction=d.get("cpu", 0.0) or 0.0,
            mem_bytes=d.get("mem", 0) or 0,
            maxmem_bytes=d.get("maxmem", 0) or 0,
            disk_bytes=d.get("disk", 0) or 0,
            maxdisk_bytes=d.get("maxdisk", 0) or 0,
            uptime_seconds=d.get("uptime", 0) or 0,
            netin_bytes=d.get("netin", 0) or 0,
            netout_bytes=d.get("netout", 0) or 0,
            diskread_bytes=d.get("diskread", 0) or 0,
            diskwrite_bytes=d.get("diskwrite", 0) or 0,
            conn_id=d.get("conn_id", "") or "",
        )
