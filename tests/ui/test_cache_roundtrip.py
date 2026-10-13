"""Tests for domain object serialization round-trip (cache compat)."""
import json

from virtdeck.domain.enums import NodeStatus, VmStatus
from virtdeck.domain.node import Node
from virtdeck.domain.storage import Storage
from virtdeck.domain.vm import Vm


class TestNodeRoundTrip:
    def test_dict_and_back(self, make_node):
        n = make_node(node="pve01", host_name="h1", cluster="cl")
        d = dict(n)
        n2 = Node.from_pve(d, d["host_name"], d["cluster"], d["_is_cluster"])
        assert n2 == n

    def test_json_round_trip(self, make_node):
        n = make_node()
        d = dict(n)
        s = json.dumps(d, default=str)
        d2 = json.loads(s)
        n2 = Node.from_pve(d2, d2["host_name"], d2["cluster"], d2["_is_cluster"])
        assert n2 == n

    def test_keys_cover_all_from_pve_fields(self, make_node):
        n = make_node()
        d = dict(n)
        # All fields Node.from_pve reads must be present
        for key in ("node", "status", "error", "cpu", "sockets", "mem", "maxmem",
                     "disk", "maxdisk", "uptime", "pveversion", "kernel",
                     "qemu", "lxctype", "host_name", "cluster", "_is_cluster"):
            assert key in d, f"Missing key {key}"


class TestVmRoundTrip:
    def test_dict_and_back(self, make_vm):
        v = make_vm()
        d = dict(v)
        v2 = Vm.from_pve(d, d["host_name"])
        assert v2 == v

    def test_json_round_trip(self, make_vm):
        v = make_vm()
        d = dict(v)
        s = json.dumps(d, default=str)
        d2 = json.loads(s)
        v2 = Vm.from_pve(d2, d2["host_name"])
        assert v2 == v

    def test_keys_cover_all_from_pve_fields(self, make_vm):
        v = make_vm()
        d = dict(v)
        for key in ("vmid", "name", "type", "node", "host_name", "pool",
                     "status", "hastate", "tags", "template", "cpu",
                     "mem", "maxmem", "disk", "maxdisk", "uptime",
                     "netin", "netout", "diskread", "diskwrite"):
            assert key in d, f"Missing key {key}"


class TestStorageRoundTrip:
    def test_dict_and_back(self, make_storage):
        s_obj = make_storage()
        d = dict(s_obj)
        s2 = Storage.from_pve(d, d["host_name"], d["cluster"])
        assert s2 == s_obj

    def test_json_round_trip(self, make_storage):
        s_obj = make_storage()
        d = dict(s_obj)
        s = json.dumps(d, default=str)
        d2 = json.loads(s)
        s2 = Storage.from_pve(d2, d2["host_name"], d2["cluster"])
        assert s2 == s_obj

    def test_keys_cover_all_from_pve_fields(self, make_storage):
        s_obj = make_storage()
        d = dict(s_obj)
        for key in ("storage", "node", "host_name", "cluster", "type",
                     "content", "used", "total", "avail", "shared"):
            assert key in d, f"Missing key {key}"


class TestSaveLoadCache:
    """End-to-end test: domain objects → save_resources_cache → load → repos."""

    def test_round_trip_through_config(self, tmp_path, monkeypatch, make_node, make_vm, make_storage):
        # Redirect SQLite DB to temp dir
        monkeypatch.setenv("HOME", str(tmp_path))
        from virtdeck.config import _init_db, load_resources_cache, save_resources_cache
        _init_db()  # initialize in temp location

        nodes = [make_node(node="n1", host_name="h1", conn_id="id-h1"),
                 make_node(node="n2", host_name="h2", conn_id="id-h2")]
        vms = [make_vm(vmid=100, host_name="h1", conn_id="id-h1"),
               make_vm(vmid=101, host_name="h2", conn_id="id-h2")]
        storages = [make_storage(storage="local", host_name="h1",
                                 conn_id="id-h1"),
                    make_storage(storage="lvm", host_name="h2",
                                 conn_id="id-h2")]

        save_resources_cache(
            [dict(n) for n in nodes],
            [dict(v) for v in vms],
            [dict(s) for s in storages],
        )

        cached, ts = load_resources_cache()
        assert cached is not None
        assert len(cached["nodes"]) == 2
        assert len(cached["vms"]) == 2
        assert len(cached["storages"]) == 2

        # Reconstruct domain objects
        for n_dict in cached["nodes"]:
            n = Node.from_pve(n_dict, n_dict["host_name"], n_dict.get("cluster", ""), n_dict.get("_is_cluster", False))
            assert n.status is NodeStatus.ONLINE
        for v_dict in cached["vms"]:
            v = Vm.from_pve(v_dict, v_dict["host_name"])
            assert v.status is VmStatus.RUNNING
        for s_dict in cached["storages"]:
            s = Storage.from_pve(s_dict, s_dict["host_name"], s_dict.get("cluster", ""))
            assert s.storage_type == "dir"
