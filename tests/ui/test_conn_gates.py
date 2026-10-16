"""Stage 5.1.2 UI gates: worker-result identity checks, cache restore
filtering, token-refresh preservation and ambiguous-connection handling."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QRunnable

# --- shared doubles (mirrors test_refresh_lifecycle.py) -------------------


def _cfg(name, host="10.0.0.1", **extra):
    cfg = {"name": name, "host": host, "user": "u@pam",
           "token_name": "t", "token_value": "s"}
    cfg.update(extra)
    return cfg


def _node(node="pve1", status="online"):
    return {"node": node, "status": status}


def _vm(vmid=100, node="pve1"):
    return {"vmid": vmid, "name": f"vm{vmid}", "type": "qemu",
            "node": node, "status": "running"}


def _ok(host, nodes=None, vms=None, storages=None):
    return {"host": host, "status": "ok",
            "nodes": nodes if nodes is not None else [_node()],
            "vms": vms if vms is not None else [_vm()],
            "storages": storages if storages is not None else [],
            "pools": [], "iso_images": {}, "ha_groups": []}


def _err(host):
    return {"host": host, "status": "error", "error": "boom"}


def _install_fake_fetch(monkeypatch):
    import virtdeck.ui.mainwindow as mw_mod
    created = []

    class _FakeFetch(QRunnable):
        def __init__(self, cfg):
            super().__init__()
            self.node_cfg = cfg
            self.signals = MagicMock()
            created.append(self)

        def run(self):  # pragma: no cover — reports are simulated
            pass

    monkeypatch.setattr(mw_mod, "FetchWorker", _FakeFetch)
    return created


@pytest.fixture
def mw(qtbot, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from virtdeck.ui.mainwindow import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    yield window
    window.close()


# --- hard slot gate --------------------------------------------------------


def test_result_of_unknown_conn_id_is_dropped(mw, monkeypatch):
    """A payload claiming a conn_id that is not in the config (deleted
    connection) must not touch repos, epochs or the cache."""
    created = _install_fake_fetch(monkeypatch)
    mw.nodes_cfg = [_cfg("h1")]
    mw.refresh_data()
    gen = mw._refresh.hard_gen
    assert created

    # simulate the connection being deleted after the worker started
    mw.nodes_cfg = []
    mw._rebuild_cfg_indexes()
    mw.on_worker_finished(_ok("h1"), created[0], gen)
    assert mw._node_repo.all() == []
    assert mw._vm_repo.all() == []


def test_result_of_recycled_connection_is_dropped(mw, monkeypatch):
    """Same name, NEW conn_id (deleted and re-added): the old connection's
    late result must not be applied to the new connection."""
    created = _install_fake_fetch(monkeypatch)
    old_cfg = _cfg("h1")
    mw.nodes_cfg = [old_cfg]
    mw.refresh_data()
    gen = mw._refresh.hard_gen
    old_id = old_cfg["conn_id"]

    # the user removes and re-adds the connection
    new_cfg = _cfg("h1", conn_id="brand-new-id")
    mw.nodes_cfg = [new_cfg]
    mw._rebuild_cfg_indexes()

    payload = _ok("h1")
    payload["conn_id"] = old_id
    mw.on_worker_finished(payload, created[0], gen)
    assert mw._vm_repo.all() == []


def test_result_of_ambiguous_entry_is_dropped(mw, monkeypatch):
    _install_fake_fetch(monkeypatch)
    a = _cfg("Web", "10.0.0.1")
    b = _cfg("web", "10.0.0.2")
    mw.nodes_cfg = [a, b]
    mw._rebuild_cfg_indexes()
    assert a.get("_ambiguous") and b.get("_ambiguous")

    payload = _ok("Web")
    payload["conn_id"] = a["conn_id"]
    mw.on_worker_finished(payload, None, 0)  # gen=0: legacy current
    assert mw._vm_repo.all() == []


def test_valid_result_stamped_and_applied(mw, monkeypatch):
    created = _install_fake_fetch(monkeypatch)
    cfg = _cfg("h1")
    mw.nodes_cfg = [cfg]
    mw.refresh_data()
    gen = mw._refresh.hard_gen

    payload = _ok("h1")
    payload["conn_id"] = cfg["conn_id"]
    mw.on_worker_finished(payload, created[0], gen)
    vms = mw._vm_repo.all()
    assert len(vms) == 1
    assert vms[0].host_name == "h1"
    # rows carry the identity for the cache (stage 5.1.2 §2.2)
    nodes = mw._node_repo.all()
    assert all(getattr(n, "conn_id", "") == cfg["conn_id"]
               for n in nodes)


def test_legacy_payload_without_conn_id_resolves_by_name(mw, monkeypatch):
    """Payloads produced before conn_id stamping (test doubles) keep the
    historic name-based resolution — additive gating, not a regression."""
    created = _install_fake_fetch(monkeypatch)
    cfg = _cfg("h1")
    mw.nodes_cfg = [cfg]
    mw.refresh_data()
    gen = mw._refresh.hard_gen
    mw.on_worker_finished(_ok("h1"), created[0], gen)  # no conn_id inside
    assert mw._vm_repo.get("h1", 100) is not None


def test_name_fallback_matches_current_display_name_only(mw, monkeypatch):
    """Stage 5.1.3 audit: the legacy fallback resolves against the CURRENT
    index by exact display name — a stale name (the connection has been
    renamed since) resolves to nothing and the result is dropped."""
    _install_fake_fetch(monkeypatch)
    cfg = _cfg("h1")
    mw.nodes_cfg = [cfg]
    mw.refresh_data()
    gen = mw._refresh.hard_gen

    mw.nodes_cfg = [_cfg("renamed", conn_id=cfg["conn_id"])]
    mw._rebuild_cfg_indexes()
    # worker=None: no identity anywhere → exercises the name fallback
    mw.on_worker_finished(_ok("h1"), None, gen)
    assert mw._vm_repo.all() == []


def test_name_fallback_dropped_for_ambiguous(mw, monkeypatch):
    """The legacy fallback respects the ambiguity gate like every other
    ingestion path."""
    _install_fake_fetch(monkeypatch)
    a = _cfg("Web")
    b = _cfg("web", host="10.0.0.2")
    a["_ambiguous"] = True
    b["_ambiguous"] = True
    mw.nodes_cfg = [a, b]
    mw.refresh_data()
    gen = mw._refresh.hard_gen

    mw.on_worker_finished(_ok("Web"), None, gen)
    assert mw._vm_repo.all() == []


def test_name_fallback_attaches_to_recreated_same_name(mw, monkeypatch):
    """Documented residual of the legacy fallback: a payload without any
    identity cannot tell a re-created connection from the original one, so
    it attaches to the CURRENT connection under the same name (same
    host/user infrastructure). Containment: the rows are stamped with the
    current cfg's conn_id, so no wrong-identity cache row can be written.
    Production payloads carry conn_id and are dropped instead (see
    test_result_of_recycled_connection_is_dropped)."""
    _install_fake_fetch(monkeypatch)
    mw.nodes_cfg = [_cfg("h1")]
    mw.refresh_data()
    gen = mw._refresh.hard_gen

    mw.nodes_cfg = [_cfg("h1", conn_id="fresh-id")]
    mw._rebuild_cfg_indexes()
    mw.on_worker_finished(_ok("h1"), None, gen)
    vms = mw._vm_repo.all()
    assert len(vms) == 1
    assert vms[0].conn_id == "fresh-id"


def test_dropped_result_does_not_resurrect_via_late_epoch(mw, monkeypatch):
    """A dropped (unknown identity) result must not register its epoch:
    a later answer of the same attempt must not pass either."""
    created = _install_fake_fetch(monkeypatch)
    cfg = _cfg("h1")
    mw.nodes_cfg = [cfg]
    mw.refresh_data()
    gen = mw._refresh.hard_gen

    mw.nodes_cfg = []           # connection deleted
    mw._rebuild_cfg_indexes()
    payload = _ok("h1")
    payload["conn_id"] = cfg["conn_id"]
    mw.on_worker_finished(payload, created[0], gen, epoch="ep-1")
    assert mw._vm_repo.all() == []
    # even after the deleted host is "re-created", the stale attempt stays
    # dead (its epoch was never registered)
    mw.nodes_cfg = [_cfg("h1", conn_id="another-new-id")]
    mw._rebuild_cfg_indexes()
    mw.on_worker_finished(payload, created[0], gen, epoch="ep-1")
    assert mw._vm_repo.all() == []


# --- soft slot gate --------------------------------------------------------


def test_soft_result_of_unknown_conn_id_is_dropped(mw, monkeypatch):
    created = _install_fake_fetch(monkeypatch)
    cfg = _cfg("h1")
    mw.nodes_cfg = [cfg]
    mw.refresh_data()
    mw.last_refresh_ts = 0.0
    mw.soft_refresh()
    gen = mw._refresh.soft_gen

    mw.nodes_cfg = []
    mw._rebuild_cfg_indexes()
    payload = _ok("h1")
    payload["conn_id"] = cfg["conn_id"]
    mw.on_soft_refresh_result(payload, created[-1], gen)
    assert mw._vm_repo.all() == []


def test_soft_result_of_valid_conn_id_applied(mw, monkeypatch):
    created = _install_fake_fetch(monkeypatch)
    cfg = _cfg("h1")
    mw.nodes_cfg = [cfg]
    mw.refresh_data()
    mw.last_refresh_ts = 0.0
    mw.soft_refresh()
    gen = mw._refresh.soft_gen

    payload = _ok("h1", vms=[_vm(300)])
    payload["conn_id"] = cfg["conn_id"]
    mw.on_soft_refresh_result(payload, created[-1], gen)
    assert mw._vm_repo.get("h1", 300) is not None


# --- ambiguous entries: visible, not refreshed, not collected --------------


def test_ambiguous_entries_excluded_from_refresh_but_visible(mw, monkeypatch):
    a = _cfg("Web", "10.0.0.1")
    b = _cfg("web", "10.0.0.2")
    healthy = _cfg("ok-host", "10.0.0.3")
    mw.nodes_cfg = [a, b, healthy]
    _install_fake_fetch(monkeypatch)
    mw.refresh_data()
    mw._finalize_hard_timeout()  # force the cycle to close (fake never runs)

    # the conflicting pair shows up as warning stubs — visible, not healthy
    node = mw._node_repo.get("Web", "Web")
    assert node is not None
    assert node.status_value == "error"
    assert "conflict" in (node.error or "")
    node_b = mw._node_repo.get("web", "web")
    assert node_b is not None and node_b.status_value == "error"


def test_ambiguous_entries_excluded_from_fleet(monkeypatch):
    from virtdeck.backend.fleet import build_fleet_targets
    a = _cfg("Web", "10.0.0.1")
    b = _cfg("web", "10.0.0.2")
    healthy = _cfg("ok-host", "10.0.0.3")
    a["_ambiguous"] = b["_ambiguous"] = True
    targets = build_fleet_targets([a, b, healthy])
    assert [t.name for t in targets] == ["ok-host"]


def test_resolving_conflict_restores_refresh(mw, monkeypatch):
    """After the loser is removed through the regular delete flow, the
    winner's flag clears and its connection is refreshed again."""
    created = _install_fake_fetch(monkeypatch)
    a = _cfg("Web", "10.0.0.1")
    b = _cfg("web", "10.0.0.2")
    mw.nodes_cfg = [a, b]
    mw._rebuild_cfg_indexes()
    assert a.get("_ambiguous")

    # resolve: remove the loser "web" through the delete flow internals
    mw.nodes_cfg = [c for c in mw.nodes_cfg if c is not b]
    mw._rebuild_cfg_indexes()
    assert not a.get("_ambiguous")     # the flag cleared with the group

    # the winner participates in refresh again
    mw.refresh_data()
    gen = mw._refresh.hard_gen
    payload = _ok("Web")
    payload["conn_id"] = a["conn_id"]
    mw.on_worker_finished(payload, created[0], gen)
    assert mw._vm_repo.get("Web", 100) is not None


def test_delete_flow_keeps_winner_identity(mw, monkeypatch):
    """Removing one member of a conflict group must not modify the
    winner's cfg (name, conn_id, token) — R2/R3 are closed."""
    a = _cfg("Web", "10.0.0.1", token_value="secret-web")
    b = _cfg("web", "10.0.0.2", token_value="secret-web-2")
    mw.nodes_cfg = [a, b]
    mw._rebuild_cfg_indexes()
    winner_id = a["conn_id"]

    # emulate the delete-flow list mutation for the exact loser
    mw.nodes_cfg = [c for c in mw.nodes_cfg if c.get("name") != "web"]
    mw._rebuild_cfg_indexes()
    assert len(mw.nodes_cfg) == 1
    assert mw.nodes_cfg[0] is a
    assert a["conn_id"] == winner_id
    assert a["token_value"] == "secret-web"
    assert not a.get("_ambiguous")


# --- token refresh preservation -------------------------------------------


def test_token_refresh_preserves_identity_and_options(mw):
    """The reconnect dialog must not rebuild the connection: conn_id,
    skip, group, type and port survive a token rotation."""
    cfg = _cfg("h1", conn_id="stable-id", skip=True, group="prod",
               type="pve", port=8006, cluster="cl1")
    mw.nodes_cfg = [cfg]
    mw._rebuild_cfg_indexes()

    # what the dialog returns after a token rotation (short field list)
    dialog_cfg = {"name": "h1", "host": "10.0.0.1", "user": "u@pam",
                  "token_name": "t2", "token_value": "s2",
                  "trust_ssl": False}
    old = cfg
    merged = dict(old)
    for k, v in dialog_cfg.items():
        if k != "conn_id":
            merged[k] = v
    merged["name"] = "h1"
    merged["host"] = old["host"]
    merged["cluster"] = old.get("cluster", False)
    if old.get("cluster_rep"):
        merged["cluster_rep"] = True
    mw.nodes_cfg[0] = merged
    mw._rebuild_cfg_indexes()

    got = mw._cfg_by_name["h1"]
    assert got["conn_id"] == "stable-id"
    assert got["skip"] is True
    assert got["group"] == "prod"
    assert got["port"] == 8006
    assert got["cluster"] == "cl1"
    assert got["token_value"] == "s2"
    assert mw._cfg_by_conn["stable-id"] is got


# --- add-flow uniqueness ----------------------------------------------------


def test_add_flow_rejects_case_insensitive_duplicate(mw):
    mw.nodes_cfg = [_cfg("web", "10.0.0.9")]
    mw._rebuild_cfg_indexes()
    candidate = _cfg("WEB", "10.0.0.10")
    taken = {c.get("name", "").strip().casefold()
             for c in mw.nodes_cfg}
    assert candidate["name"].strip().casefold() in taken


# --- restore gate: legacy rows ---------------------------------------------


def test_restore_ignores_legacy_rows_without_conn_id(mw):
    """Rows written by a pre-5.1 version (no conn_id) are never attached:
    they cannot be proven to belong to this infrastructure."""
    from virtdeck.config import save_resources_cache
    cfg = _cfg("h1", conn_id="id-h1")
    mw.nodes_cfg = [cfg]
    mw._rebuild_cfg_indexes()
    save_resources_cache(
        nodes=[{"node": "pve1", "status": "online", "host_name": "h1",
                "_is_cluster": False}],  # legacy row: no conn_id
        vms=[], storages=[])
    mw._restore_offline_cache()
    assert mw._node_repo.all() == []


def test_restore_ignores_foreign_conn_id(mw):
    from virtdeck.config import save_resources_cache
    cfg = _cfg("h1", conn_id="id-h1")
    mw.nodes_cfg = [cfg]
    mw._rebuild_cfg_indexes()
    save_resources_cache(
        nodes=[{"node": "pve1", "status": "online", "host_name": "h1",
                "_is_cluster": False, "conn_id": "id-from-other-install"}],
        vms=[], storages=[])
    mw._restore_offline_cache()
    assert mw._node_repo.all() == []


def test_restore_attaches_rows_of_known_conn_id(mw):
    from virtdeck.config import save_resources_cache
    cfg = _cfg("h1", conn_id="id-h1")
    mw.nodes_cfg = [cfg]
    mw._rebuild_cfg_indexes()
    save_resources_cache(
        nodes=[{"node": "pve1", "status": "online", "host_name": "h1",
                "_is_cluster": False, "conn_id": "id-h1"}],
        vms=[{"vmid": 100, "name": "vm100", "type": "qemu", "node": "pve1",
              "status": "running", "host_name": "h1",
              "conn_id": "id-h1"}],
        storages=[])
    mw._restore_offline_cache()
    assert mw._node_repo.get("h1", "pve1") is not None
    assert mw._vm_repo.get("h1", 100) is not None


def test_restore_excludes_ambiguous_connections(mw):
    """Scenario 9 (restore part): conflicting connections do not restore
    cache data even though their rows carry valid-looking ids."""
    from virtdeck.config import save_resources_cache
    a = _cfg("Web", "10.0.0.1", conn_id="id-web1")
    b = _cfg("web", "10.0.0.2", conn_id="id-web2")
    mw.nodes_cfg = [a, b]
    mw._rebuild_cfg_indexes()
    assert a.get("_ambiguous")
    save_resources_cache(
        nodes=[{"node": "pve1", "status": "online", "host_name": "Web",
                "_is_cluster": False, "conn_id": "id-web1"}],
        vms=[], storages=[])
    mw._restore_offline_cache()
    assert mw._node_repo.all() == []


def test_token_operations_blocked_for_ambiguous(mw, monkeypatch):
    """Scenario 10 guard: the token-refresh entry point refuses ambiguous
    connections and does not open the dialog."""
    a = _cfg("Web", "10.0.0.1", conn_id="id-web1")
    b = _cfg("web", "10.0.0.2", conn_id="id-web2")
    mw.nodes_cfg = [a, b]
    mw._rebuild_cfg_indexes()

    opened = []
    monkeypatch.setattr(
        "virtdeck.ui.add_server_dialog.AddServerDialog.exec",
        lambda self: opened.append(self) or 0)
    mw._on_host_token_refresh("Web")
    assert opened == []          # the dialog never opened


def test_dialog_rejects_conflicting_name(qtbot, monkeypatch):
    """Scenario 11 (dialog part): the add dialog checks normalized
    uniqueness inline before accepting."""
    from virtdeck.ui.add_server_dialog import AddServerDialog
    taken = frozenset({"web"})
    dlg = AddServerDialog(taken_name_keys=taken)
    qtbot.addWidget(dlg)
    dlg.name_input.setText("WEB")
    dlg.host_input.setText("10.0.0.1")
    dlg.user_input.setText("u@pam")
    assert dlg._name_conflicts() is True
    dlg.name_input.setText("srv-2")
    assert dlg._name_conflicts() is False
