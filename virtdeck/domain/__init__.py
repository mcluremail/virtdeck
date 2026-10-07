"""Domain model layer for VirtDeck.

Pure-Python dataclasses and enums representing PVE entities.
No Qt/i18n dependencies — safe to use in any context.
"""

from __future__ import annotations

from .backup import BackupSnapshot, parse_pbs_volid, verify_state
from .backup_coverage import BackupJob, Coverage, Guest, compute_coverage
from .cluster import ClusterInfo, ClusterNode, ClusterStatus
from .enums import NodeStatus, QuorumState, VmStatus, VmType
from .fleet import (
    ClusterFleetReport,
    CollectError,
    FleetReport,
    GuestBackupState,
    build_backup_states,
    build_cluster_report,
    last_pbs_backup_times,
    merge_fleet_reports,
)
from .ha_group import HaGroup
from .ha_resource import HaResource
from .iso_image import IsoImage
from .network import NetworkInterface
from .node import Node
from .pool import Pool
from .repositories import (
    NodeRepository,
    PoolRepository,
    StorageRepository,
    VmRepository,
)
from .snapshot import Snapshot
from .storage import Storage
from .task import Task
from .vm import Vm

__all__ = [
    "BackupJob",
    "BackupSnapshot",
    "ClusterFleetReport",
    "ClusterInfo",
    "ClusterNode",
    "ClusterStatus",
    "CollectError",
    "Coverage",
    "FleetReport",
    "Guest",
    "GuestBackupState",
    "HaGroup",
    "HaResource",
    "IsoImage",
    "NetworkInterface",
    "Node",
    "NodeRepository",
    "NodeStatus",
    "Pool",
    "PoolRepository",
    "QuorumState",
    "Snapshot",
    "Storage",
    "StorageRepository",
    "Task",
    "Vm",
    "VmRepository",
    "VmStatus",
    "VmType",
    "build_backup_states",
    "build_cluster_report",
    "last_pbs_backup_times",
    "merge_fleet_reports",
]
