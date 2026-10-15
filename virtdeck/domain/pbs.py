"""Domain models for Proxmox Backup Server (B17 stage 2).

Lightweight dataclasses parsed from PBS API responses:
datastores (``/config/datastore`` + ``/admin/datastore/{store}/status``),
snapshots (``/admin/datastore/{store}/snapshots``) and jobs
(sync/prune/verify under ``/admin``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


def _verify_state(value) -> str:
    """Normalize PBS verify-state ("ok"/"failed"/None) to ok/failed/none."""
    if value == "ok":
        return "ok"
    if value == "failed":
        return "failed"
    return "none"


@dataclass(frozen=True)
class PbsDatastore:
    """A PBS datastore with usage numbers.

    ``status_ok`` distinguishes "zero usage confirmed by a successful
    ``.../status`` call" from "status could not be read" (audit D1):
    when it is False the usage numbers are placeholders, not data, and
    the UI must show "—" instead of "0% / 0 B".
    """

    name: str
    path: str = ""
    usage: float = 0.0
    used_bytes: int = 0
    total_bytes: int = 0
    comment: str = ""
    status_ok: bool = True

    @classmethod
    def build(cls, cfg: dict, status: dict | None = None) -> PbsDatastore:
        """Combine ``/config/datastore`` entry with ``.../status`` response.

        ``status`` is None (or lacks the required usage fields) when the
        status call failed — the numbers are then NOT confirmed data.
        """
        st = status if isinstance(status, dict) else {}
        return cls(
            name=cfg.get("store", cfg.get("name", "")),
            path=cfg.get("path", ""),
            comment=cfg.get("comment", "") or "",
            usage=float(st.get("usage", 0.0) or 0.0),
            used_bytes=int(st.get("used", 0) or 0),
            total_bytes=int(st.get("total", 0) or 0),
            status_ok=all(k in st for k in ("usage", "used", "total")),
        )

    def usage_pct(self) -> int:
        return int(round(self.usage * 100))


@dataclass(frozen=True)
class PbsSnapshot:
    """One PBS snapshot (backup group at a point in time)."""

    store: str
    ns: str = ""
    backup_type: str = "vm"
    backup_id: str = ""
    backup_time: datetime | None = None
    owner: str = ""
    verify: str = "none"
    size_bytes: int = 0
    comment: str = ""

    @classmethod
    def from_api(cls, store: str, d: dict) -> PbsSnapshot:
        raw_time = d.get("backup-time")
        try:
            backup_time = datetime.fromtimestamp(int(raw_time))
        except (TypeError, ValueError, OSError, OverflowError):
            backup_time = None
        return cls(
            store=store,
            ns=d.get("ns", "") or "",
            backup_type=d.get("backup-type", "vm") or "vm",
            backup_id=d.get("backup-id", "") or "",
            backup_time=backup_time,
            owner=d.get("owner", "") or "",
            verify=_verify_state(d.get("verify-state")),
            size_bytes=int(d.get("size", 0) or 0),
            comment=d.get("comment", "") or "",
        )

    @property
    def group(self) -> str:
        return f"{self.backup_type}/{self.backup_id}"

    @property
    def snapshot_id(self) -> str:
        """Full snapshot id: group + timestamp (unique within datastore+ns)."""
        ts = self.backup_time.strftime("%Y-%m-%dT%H:%M:%S") if self.backup_time else ""
        return f"{self.group}/{ts}"


@dataclass(frozen=True)
class PbsJob:
    """A PBS scheduled job (sync / verify / prune)."""

    id: str
    kind: str  # "sync" | "verify" | "prune"
    store: str = ""
    schedule: str = ""
    comment: str = ""
    disabled: bool = False

    @classmethod
    def from_api(cls, kind: str, d: dict) -> PbsJob:
        return cls(
            id=d.get("id", "") or "",
            kind=kind,
            store=d.get("store", "") or "",
            schedule=d.get("schedule", "") or "",
            comment=d.get("comment", "") or "",
            disabled=bool(d.get("disable", False)),
        )
