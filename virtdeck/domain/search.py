"""Domain service: global search over repositories (pure, no Qt).

Searches VMs, nodes, pools and storages by case-insensitive substring
and returns results that carry the tree key tuples used by
``TreePanel.find_and_select`` for quick navigation.
"""

from __future__ import annotations

from dataclasses import dataclass

from .repositories import (
    NodeRepository,
    PoolRepository,
    StorageRepository,
    VmRepository,
)
from .vm import Vm

SEARCH_LIMIT = 50
"""Maximum number of results returned by :func:`global_search`."""


@dataclass(frozen=True)
class SearchResult:
    """One search hit with the tree key used for navigation."""

    kind: str
    """Result kind: ``vm``, ``host``, ``pool`` or ``storage``."""

    label: str
    """Primary display label (name with id where applicable)."""

    detail: str
    """Secondary info: node, config host, cluster or pool."""

    key: tuple
    """Tree key tuple accepted by ``TreePanel.find_and_select``."""


def _matches(query: str, *texts: str) -> bool:
    """Case-insensitive substring match over non-empty texts."""
    return any(query in t.lower() for t in texts if t)


def _vm_matches(vm: Vm, query: str) -> bool:
    """Match a VM against name, VMID, tags, pool, node or config host."""
    texts = [vm.name, str(vm.vmid), vm.pool, vm.node, vm.host_name]
    texts.extend(t for t in vm.tags.split(";") if t)
    return _matches(query, *texts)


def global_search(
    query: str,
    node_repo: NodeRepository,
    vm_repo: VmRepository,
    storage_repo: StorageRepository,
    pool_repo: PoolRepository,
    limit: int = SEARCH_LIMIT,
) -> list[SearchResult]:
    """Search VMs, hosts, pools and storages by substring.

    VMs match name, VMID, tags, pool, node and config host name;
    hosts match node, display and config host name and cluster;
    pools match poolid; storages match storage name, cluster and
    config host name.  Results are ordered: VMs, hosts, pools,
    storages, capped at ``limit`` entries.
    """
    q = query.strip().lower()
    if not q:
        return []

    results: list[SearchResult] = []

    for vm in vm_repo.all():
        if _vm_matches(vm, q):
            detail_parts = [vm.node, vm.host_name]
            if vm.pool:
                detail_parts.append(vm.pool)
            results.append(SearchResult(
                kind="vm",
                label=f"{vm.display_name} ({vm.vmid})",
                detail=" · ".join(p for p in detail_parts if p),
                key=(vm.host_name, vm.vmid, vm.node),
            ))

    for node in node_repo.all():
        if _matches(q, node.node, node.display_name, node.host_name, node.cluster):
            detail = node.cluster or node.host_name
            results.append(SearchResult(
                kind="host",
                label=node.display_name,
                detail=detail,
                key=("host", node.node, node.host_name),
            ))

    for pool in pool_repo.all():
        if _matches(q, pool.poolid):
            # Same poolid may exist on independent hosts — show which one
            results.append(SearchResult(
                kind="pool",
                label=pool.poolid,
                detail=pool.host_name,
                key=("pool", pool.poolid, pool.host_name),
            ))

    for storage in storage_repo.all():
        if _matches(q, storage.storage, storage.cluster, storage.host_name):
            # Key must mirror the tree (B20): shared storages hang off the
            # cluster ("name (@cluster)"), local ones off the host — a local
            # storage on a cluster node has cluster set but is NOT a
            # cluster-scope item in the tree.
            if storage.shared and storage.cluster:
                detail = f"@{storage.cluster}"
                key = ("storage", storage.storage, "cluster", storage.cluster)
            else:
                detail = storage.host_name
                key = ("storage", storage.storage, "host", storage.host_name)
            results.append(SearchResult(
                kind="storage",
                label=storage.storage,
                detail=detail,
                key=key,
            ))

    return results[:limit]
