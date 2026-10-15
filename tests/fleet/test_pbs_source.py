"""Fleet Health PBS source: dimensional evidence per source (D5 fix).

The real PbsProvider is replaced by a stub: the tests pin the evidence
semantics (per-(server, datastore, namespace) grouping, fresh max per
group, failed verification excluded, nested namespaces walked), the
server normalization (case, explicit/default port, no FQDN-vs-IP
equivalence) and source isolation (a dead server or a broken datastore
is recorded, never an exception; other sources stay usable).
"""

from __future__ import annotations

from datetime import datetime

import pytest

import virtdeck.fleet.pbs_source as pbs_source
from virtdeck.domain.pbs import PbsDatastore, PbsSnapshot
from virtdeck.fleet.pbs_source import collect_pbs_last_backups, server_key


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


# ── server_key normalization ─────────────────────────────────────────


def test_server_key_case_and_default_port():
    assert server_key("Pbs.Example.COM") == ("pbs.example.com", 8007)
    assert server_key(" pbs.local ") == ("pbs.local", 8007)


def test_server_key_explicit_port_wins():
    assert server_key("pbs.local", 8008) == ("pbs.local", 8008)
    assert server_key("pbs.local", "8008") == ("pbs.local", 8008)
    assert server_key("pbs.local", "") == ("pbs.local", 8007)
    assert server_key("pbs.local", None) == ("pbs.local", 8007)


def test_server_key_bad_port_not_silently_defaulted():
    with pytest.raises(ValueError):
        server_key("pbs.local", "abc")


def test_server_key_fqdn_ip_shortname_not_equated():
    """No DNS and no heuristics: different spellings of one machine are
    different keys (a binding may only match its literal server)."""
    assert server_key("pbs.local") != server_key("192.168.1.10")
    assert server_key("pbs.local") != server_key("pbs")
    assert server_key("PBS.Local") == server_key("pbs.local")


# ── dimensional evidence ─────────────────────────────────────────────


def test_evidence_keeps_source_dimensions(monkeypatch):
    monkeypatch.setattr(pbs_source, "PbsProvider",
                        lambda cfg, timeout=15: StubProvider(cfg["_script"]))
    ev = collect_pbs_last_backups(
        [{"name": "pbs1", "host": "Pbs.Local", "_script": SCRIPT}])
    skey = ("pbs.local", 8007)
    # root namespace, nested namespaces — separate source keys
    assert ev.by_source[(skey[0], skey[1], "main", "")] == {
        ("vm", "101"): 200}
    assert ev.by_source[(skey[0], skey[1], "main", "a")] == {
        ("lxc", "301"): 400}
    assert ev.by_source[(skey[0], skey[1], "main", "a/b")] == {
        ("vm", "103"): 500}
    assert ev.collected_stores == {(skey[0], skey[1], "main")}
    assert ev.failed_servers == set() and ev.failed_stores == set()


def test_evidence_max_per_group_and_verify_excluded():
    """Pinned at the sink level: max time per (type, id); a snapshot
    with failed verification never counts."""
    out: dict[str, dict] = {}
    pbs_source._add_snapshot(snap("vm", "101", 100), "", out)
    pbs_source._add_snapshot(snap("vm", "101", 200), "", out)
    pbs_source._add_snapshot(snap("vm", "102", 300, verify="failed"), "", out)
    assert out[""] == {("vm", "101"): 200}


def test_dead_server_recorded_not_fatal(monkeypatch):
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
    ev = collect_pbs_last_backups(
        [{"name": "dead", "host": "dead.local"},
         {"name": "pbs1", "host": "pbs.local", "_script": SCRIPT}])
    assert ev.failed_servers == {("dead.local", 8007)}
    assert ev.by_source[("pbs.local", 8007, "main", "")][("vm", "101")] == 200


def test_broken_datastore_recorded_others_kept(monkeypatch):
    script = {"bad": {"snaps": {"": RuntimeError("disk error")}, "ns": {}},
              "main": SCRIPT["main"]}
    monkeypatch.setattr(pbs_source, "PbsProvider",
                        lambda cfg, timeout=15: StubProvider(cfg["_script"]))
    ev = collect_pbs_last_backups(
        [{"name": "pbs1", "host": "pbs.local", "_script": script}])
    assert ev.failed_stores == {("pbs.local", 8007, "bad")}
    assert ("pbs.local", 8007, "main") in ev.collected_stores
    assert ev.by_source[("pbs.local", 8007, "main", "")][("vm", "101")] == 200


def test_two_servers_do_not_merge(monkeypatch):
    """The same datastore name on two servers stays two sources (D5)."""
    monkeypatch.setattr(pbs_source, "PbsProvider",
                        lambda cfg, timeout=15: StubProvider(cfg["_script"]))
    ev = collect_pbs_last_backups([
        {"name": "a", "host": "pbs-a.local", "_script": SCRIPT},
        {"name": "b", "host": "PBS-B.Local", "_script": SCRIPT},
    ])
    assert ev.by_source[("pbs-a.local", 8007, "main", "")][("vm", "101")] \
        == 200
    assert ev.by_source[("pbs-b.local", 8007, "main", "")][("vm", "101")] \
        == 200


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
    collect_pbs_last_backups([{"name": "dead", "host": "d.local"},
                              {"name": "ok", "host": "o.local",
                               "_script": SCRIPT}])
    assert len(stubs) == 2  # both providers were created and released
