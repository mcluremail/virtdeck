"""Tests for domain repositories."""

from __future__ import annotations

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

# --- Helpers ---


def make_node(host: str, node: str, cluster: str = "", status: NodeStatus = NodeStatus.ONLINE):
    return Node.from_pve(
        {"node": node, "status": status.value, "cpu": 0.1, "mem": 1024**3,
         "maxmem": 2 * 1024**3, "uptime": 3600},
        host,
        cluster,
    )


def make_vm(host: str, vmid: int, node: str = "pve01", status: VmStatus = VmStatus.RUNNING,
            pool: str = ""):
    return Vm.from_pve(
        {"vmid": vmid, "name": f"vm-{vmid}", "type": "qemu", "node": node,
         "status": status.value, "cpu": 0.5, "mem": 1024**3, "maxmem": 2 * 1024**3,
         "uptime": 3600, "pool": pool},
        host,
    )


def make_storage(host: str, node: str, storage: str, cluster: str = ""):
    return Storage.from_pve(
        {"storage": storage, "node": node, "type": "dir", "content": "iso",
         "used": 1024**3, "total": 10 * 1024**3},
        host,
        cluster,
    )


# --- NodeRepository ---


class TestNodeRepository:
    def test_add_and_get(self):
        repo = NodeRepository()
        n = make_node("h1", "pve01", "ros")
        repo.add(n)
        assert repo.get("h1", "pve01") is n
        assert len(repo) == 1

    def test_add_replaces_existing(self):
        repo = NodeRepository()
        repo.add(make_node("h1", "pve01", "ros", NodeStatus.ONLINE))
        repo.add(make_node("h1", "pve01", "ros", NodeStatus.OFFLINE))
        assert len(repo) == 1
        assert repo.get("h1", "pve01").status is NodeStatus.OFFLINE

    def test_get_missing(self):
        repo = NodeRepository()
        assert repo.get("h1", "pve01") is None

    def test_get_by_host(self):
        repo = NodeRepository()
        repo.add(make_node("h1", "pve01"))
        repo.add(make_node("h1", "pve02"))
        repo.add(make_node("h2", "pve03"))
        assert len(repo.get_by_host("h1")) == 2
        assert len(repo.get_by_host("h2")) == 1
        assert repo.get_by_host("h3") == []

    def test_filter_by_cluster(self):
        repo = NodeRepository()
        repo.add(make_node("h1", "pve01", "ros"))
        repo.add(make_node("h2", "pve02", "ros"))
        repo.add(make_node("h3", "pve03", ""))
        result = repo.filter_by_cluster("ros")
        assert len(result) == 2
        assert all(n.cluster == "ros" for n in result)

    def test_filter_standalone(self):
        repo = NodeRepository()
        repo.add(make_node("h1", "pve01", "ros"))
        repo.add(make_node("h3", "pve03", ""))
        result = repo.filter_standalone()
        assert len(result) == 1
        assert result[0].node == "pve03"

    def test_count_online(self):
        repo = NodeRepository()
        repo.add(make_node("h1", "pve01", status=NodeStatus.ONLINE))
        repo.add(make_node("h1", "pve02", status=NodeStatus.ONLINE))
        repo.add(make_node("h1", "pve03", status=NodeStatus.OFFLINE))
        assert repo.count_online() == 2

    def test_remove_host(self):
        repo = NodeRepository()
        repo.add(make_node("h1", "pve01"))
        repo.add(make_node("h1", "pve02"))
        repo.add(make_node("h2", "pve03"))
        repo.remove_host("h1")
        assert len(repo) == 1
        assert repo.get("h1", "pve01") is None
        assert repo.get("h2", "pve03") is not None

    def test_clear(self):
        repo = NodeRepository()
        repo.add(make_node("h1", "pve01"))
        repo.clear()
        assert len(repo) == 0
        assert repo.all() == []

    def test_add_many(self):
        repo = NodeRepository()
        nodes = [make_node("h1", "pve01"), make_node("h2", "pve02")]
        repo.add_many(nodes)
        assert len(repo) == 2


# --- VmRepository ---


class TestVmRepository:
    def test_add_and_get(self):
        repo = VmRepository()
        vm = make_vm("h1", 100, "pve01")
        repo.add(vm)
        assert repo.get("h1", 100) is vm
        assert len(repo) == 1

    def test_add_replaces_existing(self):
        repo = VmRepository()
        repo.add(make_vm("h1", 100, status=VmStatus.RUNNING))
        repo.add(make_vm("h1", 100, status=VmStatus.STOPPED))
        assert len(repo) == 1
        assert repo.get("h1", 100).status is VmStatus.STOPPED

    def test_get_missing(self):
        repo = VmRepository()
        assert repo.get("h1", 100) is None

    def test_filter_by_host(self):
        repo = VmRepository()
        repo.add(make_vm("h1", 100, "pve01"))
        repo.add(make_vm("h1", 101, "pve01"))
        repo.add(make_vm("h1", 102, "pve02"))
        result = repo.filter_by_host("h1", "pve01")
        assert len(result) == 2
        assert all(v.node == "pve01" for v in result)

    def test_filter_by_pool(self):
        repo = VmRepository()
        repo.add(make_vm("h1", 100, pool="web"))
        repo.add(make_vm("h1", 101, pool="web"))
        repo.add(make_vm("h1", 102, pool="db"))
        result = repo.filter_by_pool("web")
        assert len(result) == 2

    def test_filter_by_status(self):
        repo = VmRepository()
        repo.add(make_vm("h1", 100, status=VmStatus.RUNNING))
        repo.add(make_vm("h1", 101, status=VmStatus.STOPPED))
        result = repo.filter_by_status(VmStatus.RUNNING)
        assert len(result) == 1

    def test_count_by_host(self):
        repo = VmRepository()
        repo.add(make_vm("h1", 100, "pve01", VmStatus.RUNNING))
        repo.add(make_vm("h1", 101, "pve01", VmStatus.RUNNING))
        repo.add(make_vm("h1", 102, "pve01", VmStatus.STOPPED))
        repo.add(make_vm("h1", 103, "pve02", VmStatus.RUNNING))
        total, running = repo.count_by_host("h1", "pve01")
        assert total == 3
        assert running == 2

    def test_all_vmids(self):
        repo = VmRepository()
        repo.add(make_vm("h1", 100))
        repo.add(make_vm("h1", 101))
        repo.add(make_vm("h2", 200))
        assert repo.all_vmids() == {100, 101, 200}

    def test_remove_host(self):
        repo = VmRepository()
        repo.add(make_vm("h1", 100))
        repo.add(make_vm("h2", 200))
        repo.remove_host("h1")
        assert len(repo) == 1
        assert repo.get("h1", 100) is None
        assert repo.get("h2", 200) is not None

    def test_clear(self):
        repo = VmRepository()
        repo.add(make_vm("h1", 100))
        repo.clear()
        assert len(repo) == 0


# --- StorageRepository ---


class TestStorageRepository:
    def test_add_and_get(self):
        repo = StorageRepository()
        s = make_storage("h1", "pve01", "local")
        repo.add(s)
        assert repo.get("h1", "pve01", "local") is s
        assert len(repo) == 1

    def test_add_replaces_existing(self):
        repo = StorageRepository()
        repo.add(make_storage("h1", "pve01", "local"))
        repo.add(Storage.from_pve(
            {"storage": "local", "node": "pve01", "type": "lvm", "used": 999},
            "h1", ""))
        result = repo.get("h1", "pve01", "local")
        assert result.storage_type == "lvm"

    def test_filter_by_host(self):
        repo = StorageRepository()
        repo.add(make_storage("h1", "pve01", "local"))
        repo.add(make_storage("h1", "pve01", "nfs"))
        repo.add(make_storage("h1", "pve02", "local"))
        result = repo.filter_by_host("h1", "pve01")
        assert len(result) == 2

    def test_remove_host(self):
        repo = StorageRepository()
        repo.add(make_storage("h1", "pve01", "local"))
        repo.add(make_storage("h2", "pve02", "local"))
        repo.remove_host("h1")
        assert len(repo) == 1
        assert repo.get("h2", "pve02", "local") is not None

    def test_clear(self):
        repo = StorageRepository()
        repo.add(make_storage("h1", "pve01", "local"))
        repo.clear()
        assert len(repo) == 0


# --- PoolRepository ---


class TestPoolRepository:
    def test_add_and_get(self):
        repo = PoolRepository()
        repo.add(Pool(poolid="web"))
        assert repo.get("web") is not None
        assert repo.get("web").poolid == "web"

    def test_add_replaces_existing(self):
        repo = PoolRepository()
        repo.add(Pool(poolid="web"))
        repo.add(Pool(poolid="web"))
        assert len(repo) == 1

    def test_empty_poolid_ignored(self):
        repo = PoolRepository()
        repo.add(Pool(poolid=""))
        assert len(repo) == 0

    def test_all_ids(self):
        repo = PoolRepository()
        repo.add(Pool(poolid="web"))
        repo.add(Pool(poolid="db"))
        assert set(repo.all_ids()) == {"web", "db"}

    def test_clear(self):
        repo = PoolRepository()
        repo.add(Pool(poolid="web"))
        repo.clear()
        assert len(repo) == 0


# --- Audit 4 / D4: index consistency when a VM moves between nodes ---


class TestVmMovesBetweenNodes:
    def test_move_removes_ghost_from_old_node_bucket(self):
        """A VM that migrated to another node must not stay in the old
        node's bucket: filter_by_host/count_by_host must not report a
        ghost (audit 4, D4)."""
        repo = VmRepository()
        repo.add(make_vm("h1", 100, node="pve01"))
        repo.add(make_vm("h1", 101, node="pve02"))

        repo.add(make_vm("h1", 100, node="pve02"))  # migration

        assert [v.vmid for v in repo.filter_by_host("h1", "pve01")] == []
        assert sorted(v.vmid for v in repo.filter_by_host("h1", "pve02")) == [100, 101]
        assert repo.count_by_host("h1", "pve01") == (0, 0)
        assert repo.count_by_host("h1", "pve02") == (2, 2)
        assert len(repo) == 2  # no duplicates by (host, vmid)

    def test_move_updates_node_of_stored_object(self):
        repo = VmRepository()
        repo.add(make_vm("h1", 100, node="pve01"))
        repo.add(make_vm("h1", 100, node="pve02"))
        assert repo.get("h1", 100).node == "pve02"

    def test_move_back_and_forth(self):
        repo = VmRepository()
        for node in ("pve02", "pve01", "pve02"):
            repo.add(make_vm("h1", 100, node=node))
        assert [v.vmid for v in repo.filter_by_host("h1", "pve01")] == []
        assert [v.vmid for v in repo.filter_by_host("h1", "pve02")] == [100]
        assert len(repo) == 1

    def test_replace_on_same_node_keeps_single_entry(self):
        repo = VmRepository()
        repo.add(make_vm("h1", 100, node="pve01", status=VmStatus.RUNNING))
        repo.add(make_vm("h1", 100, node="pve01", status=VmStatus.STOPPED))
        assert len(repo) == 1
        assert repo.filter_by_host("h1", "pve01")[0].status is VmStatus.STOPPED
        assert repo.count_by_host("h1", "pve01") == (1, 0)

    def test_other_nodes_unaffected_by_move(self):
        repo = VmRepository()
        repo.add(make_vm("h1", 100, node="pve01"))
        repo.add(make_vm("h1", 101, node="pve01"))
        repo.add(make_vm("h1", 102, node="pve03"))
        repo.add(make_vm("h2", 200, node="pve01"))

        repo.add(make_vm("h1", 100, node="pve02"))  # only VM 100 moves

        assert sorted(v.vmid for v in repo.filter_by_host("h1", "pve01")) == [101]
        assert sorted(v.vmid for v in repo.filter_by_host("h1", "pve02")) == [100]
        assert sorted(v.vmid for v in repo.filter_by_host("h1", "pve03")) == [102]
        assert sorted(v.vmid for v in repo.filter_by_host("h2", "pve01")) == [200]
        assert repo.count_by_host("h2", "pve01") == (1, 1)

    def test_move_between_hosts_is_separate_identity(self):
        """Same vmid on different hosts is a different identity — both stay."""
        repo = VmRepository()
        repo.add(make_vm("h1", 100, node="pve01"))
        repo.add(make_vm("h2", 100, node="pve01"))
        assert len(repo) == 2

    def test_remove_host_clears_all_buckets(self):
        repo = VmRepository()
        repo.add(make_vm("h1", 100, node="pve01"))
        repo.add(make_vm("h1", 101, node="pve02"))
        repo.remove_host("h1")
        assert len(repo) == 0
        assert repo.filter_by_host("h1", "pve01") == []
        assert repo.filter_by_host("h1", "pve02") == []


class TestStorageIndexConsistency:
    """Storage identity includes the node, so a "move" is a different
    object — but replace and remove_host must keep buckets consistent."""

    def test_replace_keeps_single_entry(self):
        repo = StorageRepository()
        repo.add(make_storage("h1", "pve01", "local"))
        repo.add(make_storage("h1", "pve01", "local"))
        assert len(repo) == 1
        assert len(repo.filter_by_host("h1", "pve01")) == 1

    def test_same_storage_name_on_different_nodes(self):
        """PVE has a 'local' storage on every node — separate objects."""
        repo = StorageRepository()
        repo.add(make_storage("h1", "pve01", "local"))
        repo.add(make_storage("h1", "pve02", "local"))
        assert len(repo) == 2
        assert len(repo.filter_by_host("h1", "pve01")) == 1
        assert len(repo.filter_by_host("h1", "pve02")) == 1

    def test_remove_host_clears_buckets(self):
        repo = StorageRepository()
        repo.add(make_storage("h1", "pve01", "local"))
        repo.add(make_storage("h1", "pve02", "local"))
        repo.remove_host("h1")
        assert len(repo) == 0
        assert repo.filter_by_host("h1", "pve02") == []
