"""M4.0: PBS-клиент против FakePbsApi — контракт ticket-аутентификации.

Логин по требованию, cookie PBSAuthCookie, ns-фильтр снапшотов (фундамент
«последний успешный бэкап» для Fleet Health), негативный сценарий
неверного секрета.
"""

from __future__ import annotations

import pytest

from tests.harness import FakePbsApi, pbs_session
from tests.harness.scenarios import make_pbs
from virtdeck.pbs.client import PbsClient, PbsError


def make_client(api: FakePbsApi, **cfg_extra) -> PbsClient:
    cfg = {"host": "fake-pbs", "user": api.user,
           "token_value": api.password, "trust_ssl": True}
    cfg.update(cfg_extra)
    return PbsClient(cfg, http=pbs_session(api))


def test_login_on_demand_and_ticket_reuse():
    api = make_pbs()
    client = make_client(api)
    first = client.snapshots("main")  # явный login не нужен
    assert len(first) == 3
    second = client.snapshots("main")
    assert len(second) == 3
    logins = [c for c in api.calls if c[1] == "/access/ticket"]
    assert len(logins) == 1  # ticket получен один раз и переиспользуется


def test_snapshot_fields_for_last_backup():
    api = make_pbs()
    client = make_client(api)
    snaps = client.snapshots("main")
    vm101 = [s for s in snaps if s["backup-id"] == "101"]
    assert {s["backup-time"] for s in vm101} == {1727827200, 1727740800}
    fresh = max(vm101, key=lambda s: s["backup-time"])
    assert fresh["backup-type"] == "vm"
    assert fresh["verify-state"] == "ok"


def test_namespaced_snapshots_filtered():
    api = make_pbs()
    api.add_snapshot("main", backup_id=55, ns="tenant-a")
    client = make_client(api)
    root = client.snapshots("main")
    tenant = client.snapshots("main", ns="tenant-a")
    assert {s["backup-id"] for s in root} == {"101", "999"}
    assert [s["backup-id"] for s in tenant] == ["55"]


def test_groups_last_backup():
    api = make_pbs()
    client = make_client(api)
    groups = client.get("/admin/datastore/main/groups")
    vm101 = next(g for g in groups if g["backup-id"] == "101")
    assert vm101["backup-type"] == "vm"
    assert vm101["last-backup"] == 1727827200  # свежий из двух


def test_bad_secret_raises_pbs_error():
    api = make_pbs(password="secret")
    client = make_client(api, token_value="wrong")
    with pytest.raises(PbsError, match="auth failed"):
        client.snapshots("main")
