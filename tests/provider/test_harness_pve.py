"""M4.0: реальный провайдер против FakePveApi — контракт PVE API.

Проверяется, что дорога «ProxmoxProvider → proxmoxer → transport»
работает против фейка без сокетов и возвращает сцену как есть: это
покрытие API-регрессий, которого не было до Fleet Health (фан-аут по
всем кластерам живыми кластерами не тестируем).
"""

from __future__ import annotations

import pytest

from tests.harness import (
    FakePveApi,
    fake_pve_cfg,
    install_fake_pve,
)
from tests.harness.scenarios import make_pve_cluster
from virtdeck.provider import ProxmoxError, ProxmoxProvider


@pytest.fixture()
def api(monkeypatch) -> FakePveApi:
    api = make_pve_cluster("alpha")
    install_fake_pve(monkeypatch, api)
    return api


@pytest.fixture()
def provider(api):
    with ProxmoxProvider(fake_pve_cfg("alpha")) as provider:
        yield provider


def test_backup_jobs_roundtrip(provider, api):
    jobs = provider.cluster.list_backup_jobs()
    assert jobs == api.backup_jobs
    assert ("GET", "/cluster/backup", {}) in api.calls


def test_resources_fanout_shapes(provider):
    by_id = {r["id"]: r for r in provider.cluster.list_resources()}
    assert by_id["qemu/101"]["pool"] == "prod"
    assert by_id["qemu/201"]["template"] == 1
    assert by_id["lxc/301"]["name"] == "cache01"
    assert by_id["node/pve02"]["type"] == "node"


def test_node_version(provider):
    ver = provider.nodes.get_version("pve02")
    assert ver["pveversion"].startswith("pve-manager/7.4.3")


def test_guest_lists(provider):
    assert [v["vmid"] for v in provider.vms.list_qemu("pve01")] == [101, 102]
    assert [c["vmid"] for c in provider.vms.list_lxc("pve02")] == [301]


def test_snapshots(provider):
    snaps = provider.vms.list_snapshots("pve01", 101, "qemu")
    assert [s["name"] for s in snaps] == ["pre-upgrade"]


def test_storage_rrddata(provider, api):
    series = provider.rrd.get_storage_rrddata("pve01", "local",
                                              timeframe="day")
    assert len(series) == 5
    assert ("GET", "/nodes/pve01/storage/local/rrddata",
            {"timeframe": "day", "cf": "AVERAGE"}) in api.calls


def test_multi_cluster_fanout(monkeypatch):
    """Фундамент M4.2: сборщик ходит в независимые кластеры параллельно,
    каждый фейк обслуживает только «свой» host."""
    alpha = make_pve_cluster("alpha")
    beta = make_pve_cluster("beta")
    beta.add_qemu("pve01", 111, "beta-vm")
    install_fake_pve(monkeypatch, alpha, beta)

    report = {}
    for name in ("alpha", "beta"):
        with ProxmoxProvider(fake_pve_cfg(name)) as provider:
            report[name] = {
                "jobs": provider.cluster.list_backup_jobs(),
                "versions": {
                    n: provider.nodes.get_version(n)["pveversion"]
                    for n in ("pve01", "pve02")
                },
                "vms": {r["id"] for r in provider.cluster.list_resources()
                        if r["type"] in ("qemu", "lxc")},
            }

    assert "qemu/111" in report["beta"]["vms"]
    assert "qemu/111" not in report["alpha"]["vms"]
    assert report["beta"]["versions"]["pve02"].startswith("pve-manager/7.4.3")
    assert len(alpha.calls) >= 4 and len(beta.calls) >= 4


def test_partial_failure_maps_to_proxmox_error(provider, api):
    """Семантика partial failure (B24): сбой одного эндпоинта —
    классифицированная ошибка, остальной fan-out продолжает работать."""
    api.fail["nodes/pve02/version"] = (500, "disk full")
    with pytest.raises(ProxmoxError):
        provider.nodes.get_version("pve02")
    assert provider.nodes.get_version("pve01")["version"] == "8.2.4"
