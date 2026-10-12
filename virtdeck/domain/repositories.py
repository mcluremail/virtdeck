"""Domain repositories: indexed collections of domain objects.

Each repository provides O(1) lookup by identity and O(n) filtering by
attributes.  They replace the scattered ``_vms_by_key`` / ``_nodes_by_pair``
index dicts that were duplicated across MainWindow, TreePanel, and DetailPanel.
"""

from __future__ import annotations

from typing import Protocol

from .enums import NodeStatus, VmStatus
from .node import Node
from .pool import Pool
from .storage import Storage
from .vm import Vm


class _NodeLike(Protocol):
    """Minimal interface for loading nodes (used by host rendering)."""

    host_name: str
    node: str
    cluster: str
    status: NodeStatus
    display_name: str


class NodeRepository:
    """Indexed collection of :class:`Node` objects."""

    def __init__(self) -> None:
        self._by_pair: dict[tuple[str, str], Node] = {}
        self._by_host: dict[str, dict[tuple[str, str], Node]] = {}

    def add(self, node: Node) -> None:
        """Add or replace a node — O(1) dedup by ``(host_name, node)``."""
        key = (node.host_name, node.node)
        self._by_pair[key] = node
        host_bucket = self._by_host.setdefault(node.host_name, {})
        host_bucket[key] = node

    def add_many(self, nodes: list[Node]) -> None:
        """Bulk add/replace."""
        for n in nodes:
            self.add(n)

    def get(self, host_name: str, node: str) -> Node | None:
        """O(1) lookup by ``(host_name, node)``."""
        return self._by_pair.get((host_name, node))

    def get_by_host(self, host_name: str) -> list[Node]:
        """All nodes for a given virtdeck config name."""
        return list(self._by_host.get(host_name, {}).values())

    def all(self) -> list[Node]:
        """All nodes as a list."""
        return list(self._by_pair.values())

    def filter_by_cluster(self, cluster: str) -> list[Node]:
        """Nodes belonging to a specific cluster."""
        return [n for n in self._by_pair.values() if n.cluster == cluster]

    def filter_standalone(self) -> list[Node]:
        """Nodes not in any cluster (``cluster == ""``)."""
        return [n for n in self._by_pair.values() if not n.cluster]

    def count_online(self) -> int:
        """Count of nodes with ``ONLINE`` status."""
        return sum(1 for n in self._by_pair.values() if n.status is NodeStatus.ONLINE)

    def remove_host(self, host_name: str) -> None:
        """Remove all nodes for a host (on host removal)."""
        for key in [k for k in self._by_pair if k[0] == host_name]:
            del self._by_pair[key]
        self._by_host.pop(host_name, None)

    def clear(self) -> None:
        self._by_pair.clear()
        self._by_host.clear()

    def __len__(self) -> int:
        return len(self._by_pair)


class VmRepository:
    """Indexed collection of :class:`Vm` objects."""

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, int], Vm] = {}
        self._by_host_node: dict[tuple[str, str], list[Vm]] = {}

    def add(self, vm: Vm) -> None:
        """Add or replace a VM — O(1) dedup by ``(host_name, vmid)``.

        If the VM moved to another node since the previous snapshot, the
        stale entry is removed from the old node's bucket — otherwise
        ``filter_by_host()``/``count_by_host()`` keep reporting a ghost VM
        on the node it left (audit 4, D4).
        """
        key = (vm.host_name, vm.vmid)
        old = self._by_key.get(key)
        if old is not None and old.node != vm.node:
            old_bucket = self._by_host_node.get((old.host_name, old.node))
            if old_bucket is not None:
                self._by_host_node[(old.host_name, old.node)] = [
                    v for v in old_bucket if v.vmid != vm.vmid
                ]
        self._by_key[key] = vm
        bucket_key = (vm.host_name, vm.node)
        bucket = self._by_host_node.setdefault(bucket_key, [])
        existing_idx = next(
            (i for i, v in enumerate(bucket) if v.vmid == vm.vmid), None
        )
        if existing_idx is not None:
            bucket[existing_idx] = vm
        else:
            bucket.append(vm)

    def add_many(self, vms: list[Vm]) -> None:
        """Bulk add/replace."""
        for v in vms:
            self.add(v)

    def get(self, host_name: str, vmid: int) -> Vm | None:
        """O(1) lookup by ``(host_name, vmid)``."""
        return self._by_key.get((host_name, vmid))

    def all(self) -> list[Vm]:
        """All VMs as a list."""
        return list(self._by_key.values())

    def filter_by_host(self, host_name: str, node: str) -> list[Vm]:
        """VMs on a specific PVE node (``host_name`` is config name, ``node`` is PVE name)."""
        return list(self._by_host_node.get((host_name, node), []))

    def filter_by_pool(self, pool: str) -> list[Vm]:
        """VMs in a specific pool."""
        return [v for v in self._by_key.values() if v.pool == pool]

    def filter_by_status(self, status: VmStatus) -> list[Vm]:
        """VMs with a specific status."""
        return [v for v in self._by_key.values() if v.status is status]

    def count_by_host(self, host_name: str, node: str) -> tuple[int, int]:
        """Return ``(total, running)`` counts for a PVE node."""
        vms = self._by_host_node.get((host_name, node), [])
        total = len(vms)
        running = sum(1 for v in vms if v.status is VmStatus.RUNNING)
        return total, running

    def all_vmids(self) -> set[int]:
        """All VM IDs in use."""
        return {v.vmid for v in self._by_key.values()}

    def remove_host(self, host_name: str) -> None:
        """Remove all VMs for a host (on host removal)."""
        for key in [k for k in self._by_key if k[0] == host_name]:
            del self._by_key[key]
        for bn in [k for k in self._by_host_node if k[0] == host_name]:
            del self._by_host_node[bn]

    def clear(self) -> None:
        self._by_key.clear()
        self._by_host_node.clear()

    def __len__(self) -> int:
        return len(self._by_key)


class StorageRepository:
    """Indexed collection of :class:`Storage` objects."""

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str, str], Storage] = {}
        self._by_host_node: dict[tuple[str, str], list[Storage]] = {}

    def add(self, storage: Storage) -> None:
        """Add or replace — O(1) dedup by ``(host_name, node, storage)``."""
        key = (storage.host_name, storage.node, storage.storage)
        self._by_key[key] = storage
        bucket_key = (storage.host_name, storage.node)
        bucket = self._by_host_node.setdefault(bucket_key, [])
        existing_idx = next(
            (i for i, s in enumerate(bucket) if s.storage == storage.storage), None
        )
        if existing_idx is not None:
            bucket[existing_idx] = storage
        else:
            bucket.append(storage)

    def add_many(self, storages: list[Storage]) -> None:
        """Bulk add/replace."""
        for s in storages:
            self.add(s)

    def get(self, host_name: str, node: str, storage: str) -> Storage | None:
        """O(1) lookup by ``(host_name, node, storage)``."""
        return self._by_key.get((host_name, node, storage))

    def all(self) -> list[Storage]:
        """All storages as a list."""
        return list(self._by_key.values())

    def filter_by_host(self, host_name: str, node: str) -> list[Storage]:
        """Storages on a specific PVE node."""
        return list(self._by_host_node.get((host_name, node), []))

    def remove_host(self, host_name: str) -> None:
        """Remove all storages for a host."""
        for key in [k for k in self._by_key if k[0] == host_name]:
            del self._by_key[key]
        for bn in [k for k in self._by_host_node if k[0] == host_name]:
            del self._by_host_node[bn]

    def clear(self) -> None:
        self._by_key.clear()
        self._by_host_node.clear()

    def __len__(self) -> int:
        return len(self._by_key)


class PoolRepository:
    """Indexed collection of :class:`Pool` objects.

    Pool identity is ``(host_name, poolid)`` (audit 4.2, D2): a poolid is
    unique within a PVE cluster / standalone instance but not across
    independent infrastructures, so identical ids of different hosts must
    coexist instead of silently replacing each other.
    """

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], Pool] = {}

    def add(self, pool: Pool) -> None:
        """Add or replace — O(1) dedup by ``(host_name, poolid)``."""
        if pool.poolid:
            self._by_key[(pool.host_name, pool.poolid)] = pool

    def add_many(self, pools: list[Pool]) -> None:
        """Bulk add/replace."""
        for p in pools:
            self.add(p)

    def get(self, host_name: str, poolid: str) -> Pool | None:
        """O(1) lookup by ``(host_name, poolid)``."""
        return self._by_key.get((host_name, poolid))

    def for_host(self, host_name: str) -> list[Pool]:
        """All pools reported by a specific host."""
        return [p for (h, _pid), p in self._by_key.items() if h == host_name]

    def all(self) -> list[Pool]:
        """All pools as a list."""
        return list(self._by_key.values())

    def all_ids(self) -> list[str]:
        """All pool IDs as a list of strings."""
        return list({p.poolid for p in self._by_key.values()})

    def remove_host(self, host_name: str) -> None:
        """Remove all pools reported by a host."""
        for key in [k for k in self._by_key if k[0] == host_name]:
            del self._by_key[key]

    def clear(self) -> None:
        self._by_key.clear()

    def __len__(self) -> int:
        return len(self._by_key)
