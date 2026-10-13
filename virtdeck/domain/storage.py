"""Domain model: Storage (PVE storage resource).

A frozen dataclass representing a PVE storage at a point in time.
"""

from __future__ import annotations

from dataclasses import dataclass

from ._dictcompat import DictCompat
from ._format import safe_pct


@dataclass(frozen=True)
class Storage(DictCompat):
    """A PVE storage resource (list-level data)."""

    _FIELD_MAP = {
        "storage": "storage",
        "node": "node",
        "host_name": "host_name",
        "cluster": "cluster",
        "type": "storage_type",
        "content": "content",
        "used": "used_bytes",
        "total": "total_bytes",
        "avail": "avail_bytes",
        "shared": "shared",
        "conn_id": "conn_id",
    }

    # -- Identity --
    storage: str
    """Storage ID / name (e.g. 'local', 'local-lvm')."""

    node: str
    """PVE node name."""

    host_name: str
    """virtdeck config name."""

    cluster: str
    """Cluster name, "" for standalone."""

    # -- Attributes --
    storage_type: str
    """Storage plugin type: 'lvm', 'dir', 'zfs', 'nfs', etc."""

    content: str
    """Comma-separated content types: 'images,iso,backup,vztmpl,...'."""

    used_bytes: int
    total_bytes: int
    avail_bytes: int
    shared: bool
    """Whether the storage is shared across nodes."""

    # -- Identity of the producing connection (stage 5.1.2) --
    conn_id: str = ""
    """conn_id of the config entry that fetched this row; the resource
    cache is identity-keyed on it. Empty for legacy rows."""

    # -- Computed properties --
    @property
    def used_gib(self) -> float:
        """Used space in GiB, rounded to 1 decimal."""
        return round(self.used_bytes / (1024**3), 1) if self.used_bytes else 0.0

    @property
    def total_gib(self) -> float:
        """Total space in GiB, rounded to 1 decimal."""
        return round(self.total_bytes / (1024**3), 1) if self.total_bytes else 0.0

    @property
    def avail_gib(self) -> float:
        """Available space in GiB, rounded to 1 decimal."""
        return round(self.avail_bytes / (1024**3), 1) if self.avail_bytes else 0.0

    @property
    def usage_pct(self) -> int:
        """Usage percentage (0-100)."""
        return safe_pct(self.used_bytes, self.total_bytes)

    @property
    def content_list(self) -> list[str]:
        """Content types as a list of stripped strings."""
        return [c.strip() for c in self.content.split(",") if c.strip()] if self.content else []

    @property
    def display_name(self) -> str:
        """Storage name for display."""
        return self.storage

    @property
    def type_text(self) -> str:
        """Storage type for display."""
        return self.storage_type

    @property
    def content_text(self) -> str:
        """Content types formatted for display: 'images, iso'."""
        return ", ".join(self.content_list) if self.content_list else ""

    @property
    def used_text(self) -> str:
        """Used space formatted: '10.0 GiB'."""
        return f"{self.used_gib} GiB"

    @property
    def total_text(self) -> str:
        """Total space formatted: '100.0 GiB'."""
        return f"{self.total_gib} GiB"

    @property
    def usage_text(self) -> str:
        """Usage percentage formatted: '10%'."""
        return f"{self.usage_pct}%"

    @property
    def _key(self) -> str:
        """Unique row key for CardList matching."""
        return self.storage

    # -- Factory --
    @staticmethod
    def from_pve(d: dict, host_name: str, cluster: str) -> Storage:
        """Build a Storage from a raw PVE API dict.

        ``host_name`` and ``cluster`` are set by the fetch layer, not the API.
        """
        return Storage(
            storage=d.get("storage", "") or "",
            node=d.get("node", "") or "",
            host_name=host_name,
            # Standalone host configs store "cluster": false — normalize
            # falsy to "" so scope filters (s.cluster == "") match.
            cluster=cluster or "",
            # /cluster/resources reports the backend in "plugintype" ("dir",
            # "cephfs", ...) while "type" is just "storage"; per-node
            # /nodes/{node}/storage has the backend in "type".
            storage_type=d.get("plugintype") or d.get("type", "") or "",
            content=d.get("content", "") or "",
            # /cluster/resources reports usage as disk/maxdisk; per-node
            # /nodes/{node}/storage reports used/total/avail. Accept both.
            used_bytes=d.get("used", 0) or d.get("disk", 0) or 0,
            total_bytes=d.get("total", 0) or d.get("maxdisk", 0) or 0,
            avail_bytes=d.get("avail", 0) or 0,
            shared=bool(d.get("shared")),
            conn_id=d.get("conn_id", "") or "",
        )
