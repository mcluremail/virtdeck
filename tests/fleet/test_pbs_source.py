"""Fleet Health PBS source: the last-backup mapping per server (P0).

The real PbsProvider is replaced by a stub: the tests pin the mapping
semantics (fresh max per group, failed verification excluded, nested
namespaces walked) and source isolation (a dead server or a broken
datastore → a partial mapping, never an exception).
"""

from __future__ import annotations

from datetime import datetime

import virtdeck.fleet.pbs_source as pbs_source
from virtdeck.domain.pbs import PbsDatastore, PbsSnapshot
from virtdeck.fleet.pbs_source import collect_pbs_last_backups


def snap(btype: str, bid: str, t: int, verify: str = "ok") -> PbsSnapshot:
    return PbsSnapshot(store="main", backup_type=btype, backup_id=bid,
                       backup_time=datetime.fromtimestamp(t), verify=verify)


class StubProvider:
    """PbsProvider double fed from a script dict:

    ``{"main": {"snaps": {"": [...], "a": [...], "a/b": [...]},
                "ns": {"": ["a"], "a": ["b"]}}}``
    A value in ``snaps`` may be an Exception instance → raised.
    """

    def __init__(self, script: dict):
        self.script = script
        self.closed = False

    def datastores(self):
        return [PbsDatastore(name=n) for n in self.script]

    def snapshots(self, store: str, ns: str = ""):
        val = self.script[store]["snaps"].get(ns, [])
        if isinstance(val, Exception):
            raise val
        return val

    def namespaces(self, store: str, parent: str = ""):
        return self.script[store]["ns"].get(parent, [])

    def close(self):
        self.closed = True


SCRIPT = {
    "main": {
        "snaps": {
            "": [snap("vm", "101", 100), snap("vm", "101", 200),
                 snap("vm", "102", 300, verify="failed")],
            "a": [snap("lxc", "301", 400)],
            "a/b": [snap("vm", "103", 500)],
        },
        "ns": {"": ["a"], "a": ["b"]},
    },
}


def test_mapping_fresh_max_and_verify(monkeypatch):
    monkeypatch.setattr(pbs_source, "PbsProvider",
                        lambda cfg, timeout=15: StubProvider(cfg["_script"]))
    mapping = collect_pbs_last_backups(
        [{"name": "pbs1", "_script": SCRIPT}])
    # max time per group; failed verification excluded; the nested
    # namespace "a/b" is walked
    assert mapping == {("vm", "101"): 200, ("lxc", "301"): 400,
                       ("vm", "103"): 500}


def test_dead_server_isolated(monkeypatch):
    class Dead:
        def __init__(self, cfg, timeout=15):
            pass

        def datastores(self):
            raise RuntimeError("connection refused")

        def close(self):
            pass

    monkeypatch.setattr(
        pbs_source, "PbsProvider",
        lambda cfg, timeout=15: (Dead(cfg) if cfg.get("name") == "dead"
                                 else StubProvider(cfg["_script"])))
    mapping = collect_pbs_last_backups(
        [{"name": "dead"}, {"name": "pbs1", "_script": SCRIPT}])
    assert mapping[("vm", "101")] == 200  # healthy server still counted
    assert ("lxc", "301") in mapping


def test_broken_datastore_isolated(monkeypatch):
    script = {"bad": {"snaps": {"": RuntimeError("disk error")}, "ns": {}},
              "main": SCRIPT["main"]}
    monkeypatch.setattr(pbs_source, "PbsProvider",
                        lambda cfg, timeout=15: StubProvider(cfg["_script"]))
    mapping = collect_pbs_last_backups([{"name": "pbs1", "_script": script}])
    assert mapping[("vm", "101")] == 200
    assert ("vm", "999") not in mapping


def test_provider_closed_even_on_failure(monkeypatch):
    stubs = []

    def factory(cfg, timeout=15):
        s = StubProvider(cfg["_script"]) if "_script" in cfg else Broken()
        stubs.append(s)
        return s

    class Broken:
        def datastores(self):
            raise RuntimeError("boom")

        def close(self):
            pass

    monkeypatch.setattr(pbs_source, "PbsProvider", factory)
    collect_pbs_last_backups([{"name": "dead"},
                              {"name": "ok", "_script": SCRIPT}])
    assert len(stubs) == 2  # both providers were created and released
