"""Tests for domain global search (virtdeck/domain/search.py)."""

from __future__ import annotations

import dataclasses

import pytest

from virtdeck.domain import (
    Node,
    NodeRepository,
    NodeStatus,
    Pool,
    PoolRepository,
    Storage,
    StorageRepository,
    Vm,
    VmRepository,
    VmStatus,
)
from virtdeck.domain.search import SEARCH_LIMIT, SearchResult, global_search

# --- Helpers ---


def make_vm(host: str, vmid: int, node: str = "pve01", name: str = "",
            pool: str = "", tags: str = ""):
    return Vm.from_pve(
        {"vmid": vmid, "name": name or f"vm-{vmid}", "type": "qemu",
         "node": node, "status": VmStatus.RUNNING.value, "pool": pool,
         "tags": tags},
        host,
    )


def make_node(host: str, node: str, cluster: str = ""):
    return Node.from_pve(
        {"node": node, "status": NodeStatus.ONLINE.value, "cpu": 0.1,
         "mem": 1024**3, "maxmem": 2 * 1024**3, "uptime": 3600},
        host,
        cluster,
    )


def make_storage(host: str, node: str, storage: str, cluster: str = "",
                 shared: bool = False):
    return Storage.from_pve(
        {"storage": storage, "node": node, "type": "dir", "content": "iso",
         "used": 1024**3, "total": 10 * 1024**3, "shared": int(shared)},
        host,
        cluster,
    )


def make_repos():
    node_repo = NodeRepository()
    vm_repo = VmRepository()
    storage_repo = StorageRepository()
    pool_repo = PoolRepository()
    node_repo.add_many([
        make_node("h1", "pve01", "ros"),
        make_node("h2", "standalone"),
    ])
    vm_repo.add_many([
        make_vm("h1", 100, name="web-server", pool="prod", tags="nginx;web"),
        make_vm("h1", 101, name="database", node="pve02"),
        make_vm("h2", 202, name="backup", node="standalone"),
    ])
    storage_repo.add_many([
        make_storage("h1", "pve01", "local-lvm", "ros"),
        make_storage("h1", "pve01", "ros-pool", "ros", shared=True),
        make_storage("h2", "standalone", "ceph"),
    ])
    pool_repo.add_many([Pool.from_pve({"poolid": "prod"}),
                        Pool.from_pve({"poolid": "dev"})])
    return node_repo, vm_repo, storage_repo, pool_repo


def search(query: str, node_repo=None, vm_repo=None, storage_repo=None,
           pool_repo=None, limit=SEARCH_LIMIT):
    nr, vr, sr, pr = make_repos()
    return global_search(
        query,
        node_repo if node_repo is not None else nr,
        vm_repo if vm_repo is not None else vr,
        storage_repo if storage_repo is not None else sr,
        pool_repo if pool_repo is not None else pr,
        limit=limit,
    )


# --- Basic behaviour ---


class TestGlobalSearch:
    def test_empty_and_blank_query(self):
        assert search("") == []
        assert search("   ") == []
        assert isinstance(search("back")[0], SearchResult)

    def test_vm_by_name_case_insensitive(self):
        results = search("WEB-Serv")
        assert len(results) == 1
        assert results[0].kind == "vm"
        assert results[0].label == "web-server (100)"
        assert results[0].key == ("h1", 100, "pve01")

    def test_vm_by_vmid_substring(self):
        labels = [r.label for r in search("10")]
        assert "web-server (100)" in labels
        assert "database (101)" in labels
        assert "backup (202)" not in labels

    def test_vm_by_tag(self):
        results = search("nginx")
        assert len(results) == 1
        assert results[0].key == ("h1", 100, "pve01")

    def test_vm_by_pool_and_node_and_host(self):
        assert [r.key for r in search("prod")][0] == ("h1", 100, "pve01")
        assert [r.key for r in search("pve02")][0] == ("h1", 101, "pve02")
        assert [r.key for r in search("h2")][0] == ("h2", 202, "standalone")

    def test_host_by_node_name_and_cluster(self):
        results = search("pve01")
        host_hits = [r for r in results if r.kind == "host"]
        assert len(host_hits) == 1
        assert host_hits[0].key == ("host", "pve01", "h1")
        assert host_hits[0].detail == "ros"
        assert search("ros")[0].key == ("host", "pve01", "h1")

    def test_host_standalone_detail_is_config_host(self):
        host_hits = [r for r in search("standalone") if r.kind == "host"]
        assert host_hits[0].key == ("host", "standalone", "h2")
        assert host_hits[0].detail == "h2"

    def test_pool(self):
        results = search("dev")
        assert len(results) == 1
        assert results[0].kind == "pool"
        assert results[0].key == ("pool", "dev", "")

    def test_pool_same_id_different_hosts_distinct_keys(self):
        """Same poolid on two hosts — both found, keys distinguish them
        (audit 4.2, D2)."""
        repo = PoolRepository()
        repo.add(Pool(poolid="prod", host_name="h1"))
        repo.add(Pool(poolid="prod", host_name="h2"))
        results = global_search("prod", NodeRepository(), VmRepository(),
                                StorageRepository(), repo)
        assert len(results) == 2
        assert {r.key for r in results} == {("pool", "prod", "h1"),
                                            ("pool", "prod", "h2")}

    def test_storage_standalone(self):
        results = search("ceph")
        assert len(results) == 1
        assert results[0].kind == "storage"
        assert results[0].detail == "h2"
        assert results[0].key == ("storage", "ceph", "host", "h2",
                                  "standalone")

    def test_storage_shared_in_cluster(self):
        results = search("ros-pool")
        assert len(results) == 1
        assert results[0].detail == "@ros"
        assert results[0].key == ("storage", "ros-pool", "cluster", "ros")

    def test_storage_local_on_cluster_node(self):
        # B20 audit: a local storage on a cluster node must keep a host-scope
        # key — the tree has no cluster-scope item for it. The PVE node
        # rides in the key: the same storage name can exist on every
        # member of the cluster (2026-10-19).
        results = search("local-lvm")
        assert len(results) == 1
        assert results[0].detail == "h1"
        assert results[0].key == ("storage", "local-lvm", "host", "h1",
                                  "pve01")

    def test_order_vms_hosts_pools_storages(self):
        results = search("prod")
        kinds = [r.kind for r in results]
        assert kinds == ["vm", "host", "pool"] or kinds == ["vm", "pool"] or kinds[:2] == ["vm", "host"]
        vm_idx = kinds.index("vm") if "vm" in kinds else -1
        pool_idx = kinds.index("pool") if "pool" in kinds else len(kinds)
        host_idx = kinds.index("host") if "host" in kinds else -1
        storage_idx = kinds.index("storage") if "storage" in kinds else len(kinds)
        assert host_idx < pool_idx < storage_idx
        assert vm_idx < pool_idx

    def test_no_results(self):
        assert search("zzz-nonexistent") == []

    def test_limit(self):
        many = VmRepository()
        for i in range(20):
            many.add(make_vm("h1", 1000 + i, name="same-name"))
        results = search("same-name", vm_repo=many,
                         node_repo=NodeRepository(),
                         storage_repo=StorageRepository(),
                         pool_repo=PoolRepository(), limit=5)
        assert len(results) == 5

    def test_frozen_result(self):
        result = search("nginx")[0]
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.kind = "x"
