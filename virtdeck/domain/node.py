"""Domain model: Node (PVE host).

A frozen dataclass representing a Proxmox VE node at a point in time.
Raw PVE API values are stored as-is; human-readable representations are
computed via read-only properties.
"""

from __future__ import annotations

from dataclasses import dataclass

from ._dictcompat import DictCompat
from ._format import format_uptime, safe_pct
from .enums import NodeStatus


@dataclass(frozen=True)
class Node(DictCompat):
    """A Proxmox VE node (host) at a point in time.

    Fields hold raw PVE API values.  Use computed properties for display.
    """

    _FIELD_MAP = {
        "node": "node",
        "host_name": "host_name",
        "cluster": "cluster",
        "status": "_status_value",
        "error": "error",
        "cpu": "cpu_fraction",
        "sockets": "cpu_sockets",
        "mem": "mem_bytes",
        "maxmem": "maxmem_bytes",
        "disk": "disk_bytes",
        "maxdisk": "maxdisk_bytes",
        "uptime": "uptime_seconds",
        "pveversion": "pve_version_raw",
        "kernel": "kernel_version",
        "qemu": "qemu_version",
        "lxctype": "lxc_version",
        "_display_name": "display_name",
        "_is_cluster": "is_cluster",
        "conn_id": "conn_id",
    }

    # -- Identity --
    host_name: str
    """virtdeck config name (our own identifier)."""

    node: str
    """PVE node name."""

    cluster: str
    """Cluster name, "" for standalone hosts."""

    # -- Status --
    status: NodeStatus
    error: str
    """Error message when status == ERROR."""

    # -- Resources (raw PVE values) --
    cpu_fraction: float
    """CPU usage 0.0-1.0."""

    cpu_sockets: int
    mem_bytes: int
    maxmem_bytes: int
    disk_bytes: int
    maxdisk_bytes: int
    uptime_seconds: int

    # -- Software versions --
    pve_version_raw: str
    """Raw PVE version string, e.g. 'pve-manager/8.2.4/abc'."""

    kernel_version: str
    qemu_version: str
    lxc_version: str

    # -- Flags --
    is_cluster: bool
    """Whether this node was fetched via a cluster-representative config."""

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
        """Used disk in GiB, rounded to 1 decimal."""
        return round(self.disk_bytes / (1024**3), 1) if self.disk_bytes else 0.0

    @property
    def maxdisk_gib(self) -> float:
        """Maximum disk in GiB, rounded to 1 decimal."""
        return round(self.maxdisk_bytes / (1024**3), 1) if self.maxdisk_bytes else 0.0

    @property
    def uptime_str(self) -> str:
        """Human-readable uptime like '5d 3h 20m 10s', or '—' if zero."""
        return format_uptime(self.uptime_seconds) if self.uptime_seconds else "—"

    @property
    def pve_version(self) -> str:
        """Short PVE version, e.g. '8.2.4' extracted from raw string."""
        return (
            self.pve_version_raw.split("/")[-1]
            if "/" in self.pve_version_raw
            else self.pve_version_raw
        )

    @property
    def display_name(self) -> str:
        """Display name: 'node@cluster' for cluster nodes, 'node' for standalone."""
        return f"{self.node}@{self.cluster}" if self.cluster else self.node

    @property
    def status_color(self) -> str:
        """Color tag for UI: 'ok', 'off', 'err', 'warn'."""
        mapping = {
            NodeStatus.ONLINE: "ok",
            NodeStatus.OFFLINE: "off",
            NodeStatus.ERROR: "err",
            NodeStatus.UNKNOWN: "warn",
        }
        return mapping[self.status]

    @property
    def status_value(self) -> str:
        """Raw status string for CardRow dot matching ('online', 'offline', ...)."""
        return self.status.value

    @property
    def _status_value(self) -> str:
        """Alias for status_value — used by _FIELD_MAP for dict-compat."""
        return self.status.value

    @property
    def cpu_text(self) -> str:
        """CPU usage formatted for display: '42.0%'."""
        return f"{self.cpu_pct}%"

    @property
    def ram_text(self) -> str:
        """Memory usage formatted: '8.0/16.0 GiB'."""
        return f"{self.mem_gib}/{self.maxmem_gib} GiB"

    @property
    def disk_text(self) -> str:
        """Disk usage formatted: '1.0/50.0 GiB'."""
        return f"{self.disk_gib}/{self.maxdisk_gib} GiB"

    @property
    def pve_text(self) -> str:
        """PVE version for display, or '—'."""
        return self.pve_version or "—"

    @property
    def _key(self) -> str:
        """Unique row key for CardList matching."""
        return f"{self.node}@{self.host_name}"

    @property
    def address(self) -> str:
        """Host address — empty, filled from config by UI layer."""
        return ""

    @property
    def vms_text(self) -> str:
        """VM count text — empty, filled by UI layer (needs VmRepository)."""
        return ""

    # -- Factory --
    @staticmethod
    def from_pve(
        d: dict,
        host_name: str,
        cluster: str,
        is_cluster: bool = False,
    ) -> Node:
        """Build a Node from a raw PVE API dict.

        Missing fields default to zero/empty — never raises on shape.
        """
        # Standalone host configs store "cluster": false — normalize any
        # falsy value to "" so tree/scope comparisons (== cluster_scope)
        # match instead of failing on False == "".
        return Node(
            host_name=host_name,
            node=d.get("node", ""),
            cluster=cluster or "",
            status=NodeStatus.from_pve(d.get("status")),
            error=d.get("error", ""),
            cpu_fraction=d.get("cpu", 0.0) or 0.0,
            cpu_sockets=d.get("sockets", 0) or 0,
            mem_bytes=d.get("mem", 0) or 0,
            maxmem_bytes=d.get("maxmem", 0) or 0,
            disk_bytes=d.get("disk", 0) or 0,
            maxdisk_bytes=d.get("maxdisk", 0) or 0,
            uptime_seconds=d.get("uptime", 0) or 0,
            pve_version_raw=d.get("pveversion", ""),
            kernel_version=d.get("kernel", ""),
            qemu_version=d.get("qemu", ""),
            lxc_version=d.get("lxctype", ""),
            is_cluster=is_cluster,
            conn_id=d.get("conn_id", "") or "",
        )

    @staticmethod
    def loading_stub(host_name: str) -> Node:
        """Placeholder node shown in the tree while data is being fetched.

        The node name equals the config name; status is LOADING so the UI
        renders a spinner instead of an icon.
        """
        return Node(
            host_name=host_name,
            node=host_name,
            cluster="",
            status=NodeStatus.LOADING,
            error="",
            cpu_fraction=0.0,
            cpu_sockets=0,
            mem_bytes=0,
            maxmem_bytes=0,
            disk_bytes=0,
            maxdisk_bytes=0,
            uptime_seconds=0,
            pve_version_raw="",
            kernel_version="",
            qemu_version="",
            lxc_version="",
            is_cluster=False,
        )
