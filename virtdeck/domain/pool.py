"""Domain model: Pool (PVE resource pool).

A pool is a named grouping of VMs.  Members are derived from VMs'
``pool`` field, not stored on the Pool object itself.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Pool:
    """A PVE resource pool.

    ``poolid`` is unique within a PVE cluster / standalone instance, but
    NOT across independent infrastructures — two unrelated hosts may both
    have a pool named "web".  ``host_name`` (the virtdeck config name of
    the host whose API reported the pool) is part of the pool identity
    (audit 4.2, D2).
    """

    poolid: str
    """Pool identifier / name."""

    comment: str = ""
    """Optional pool comment."""

    host_name: str = ""
    """Config name of the host whose API reported this pool."""

    @staticmethod
    def from_pve(d: dict, host_name: str = "") -> Pool:
        """Build a Pool from a raw dict (``{"poolid": "name"}``)."""
        return Pool(
            poolid=d.get("poolid", "") or d.get("pool", "") or "",
            comment=d.get("comment", "") or "",
            host_name=host_name,
        )
