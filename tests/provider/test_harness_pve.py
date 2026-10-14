"""M4.0: real provider against FakePveApi — the PVE API contract.

Checks that the path "ProxmoxProvider → proxmoxer → transport" works
against the fake without sockets and returns the scene as is: this is
API regression coverage that did not exist before Fleet Health (fan-out
across all clusters is not tested against live clusters).
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
    """M4.2 foundation: the collector hits independent clusters in parallel,
    each fake serves only its own host."""
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
    """Partial failure semantics (B24): one endpoint failing is a classified
    error, the rest of the fan-out keeps working."""
    api.fail["nodes/pve02/version"] = (500, "disk full")
    with pytest.raises(ProxmoxError):
        provider.nodes.get_version("pve02")
    assert provider.nodes.get_version("pve01")["version"] == "8.2.4"


# -- Backup job CRUD (stage 6.2.1, audit D2): the fake mirrors the real
# PVE::API2::Backup update_job semantics, so round-trips through the
# provider assert the END STATE of the job after server-side processing.


def _job(api, job_id):
    return next((j for j in api.backup_jobs if j.get("id") == job_id), None)


def test_create_pool_job_via_provider(provider, api):
    provider.cluster.create_backup_job(
        {"id": "t-pool", "pool": "prod", "storage": "pbs1",
         "schedule": "02:00"}, pve_major=7)
    job = _job(api, "t-pool")
    assert job["pool"] == "prod"
    assert "vmid" not in job and "all" not in job
    jobs = provider.cluster.list_backup_jobs()
    assert any(j["id"] == "t-pool" for j in jobs)


def test_update_comment_only_preserves_pool_selection():
    """THE D2 contract: a PUT without selection keys must not touch the
    stored selection — the old client sent vmid unconditionally."""
    api = make_pve_cluster("alpha")
    api.backup_jobs.append({"id": "job-1", "pool": "prod",
                            "storage": "pbs1", "schedule": "02:00"})
    status, _data = api.handle("PUT", "/cluster/backup/job-1",
                               {"comment": "monthly"})
    assert status == 200
    job = _job(api, "job-1")
    assert job["pool"] == "prod"
    assert job["comment"] == "monthly"
    assert "vmid" not in job


def test_update_with_vmid_deletes_pool_and_all():
    """Server-side PVE semantics the dialog must steer around: sending
    vmid deletes pool/all/exclude."""
    api = make_pve_cluster("alpha")
    api.backup_jobs.append({"id": "job-1", "pool": "prod", "all": 1,
                            "exclude": "100", "storage": "pbs1",
                            "schedule": "02:00"})
    api.handle("PUT", "/cluster/backup/job-1", {"vmid": "100,101"})
    job = _job(api, "job-1")
    assert job["vmid"] == "100,101"
    assert "pool" not in job and "all" not in job and "exclude" not in job


def test_update_with_all_deletes_vmid():
    api = make_pve_cluster("alpha")
    api.backup_jobs.append({"id": "job-1", "vmid": "100",
                            "storage": "pbs1", "schedule": "02:00"})
    api.handle("PUT", "/cluster/backup/job-1", {"all": 1})
    job = _job(api, "job-1")
    assert job["all"] == 1
    assert "vmid" not in job


def test_update_delete_param_clears_exclude_keeps_all():
    api = make_pve_cluster("alpha")
    api.backup_jobs.append({"id": "job-1", "all": 1, "exclude": "100",
                            "storage": "pbs1", "schedule": "02:00"})
    api.handle("PUT", "/cluster/backup/job-1", {"delete": "exclude"})
    job = _job(api, "job-1")
    assert job["all"] == 1
    assert "exclude" not in job


def test_update_empty_params_rejected():
    api = make_pve_cluster("alpha")
    api.backup_jobs.append({"id": "job-1", "vmid": "100",
                            "storage": "pbs1", "schedule": "02:00"})
    status, data = api.handle("PUT", "/cluster/backup/job-1", {})
    assert status == 400
    assert "no options" in str(data)


def test_vmid_word_all_rejected_everywhere():
    api = make_pve_cluster("alpha")
    api.backup_jobs.append({"id": "job-1", "vmid": "100",
                            "storage": "pbs1", "schedule": "02:00"})
    for method, path, params in (
        ("POST", "/cluster/backup", {"vmid": "all", "storage": "pbs1",
                                     "schedule": "02:00"}),
        ("PUT", "/cluster/backup/job-1", {"vmid": "all"}),
    ):
        status, data = api.handle(method, path, params)
        assert status == 400
        assert "invalid vmid 'all'" in str(data)


def test_delete_backup_job_via_provider(provider, api):
    api.backup_jobs.append({"id": "job-1", "vmid": "100",
                            "storage": "pbs1", "schedule": "02:00"})
    provider.cluster.delete_backup_job("job-1", pve_major=7)
    assert _job(api, "job-1") is None
    with pytest.raises(ProxmoxError):
        provider.cluster.delete_backup_job("job-1", pve_major=7)


def test_create_duplicate_rejected(provider, api):
    params = {"vmid": "100", "storage": "pbs1", "schedule": "02:00"}
    provider.cluster.create_backup_job(dict(params, id="dup"), pve_major=7)
    with pytest.raises(ProxmoxError):
        provider.cluster.create_backup_job(dict(params, id="dup"),
                                           pve_major=7)


def test_pve8_jobs_path_uses_same_store(provider, api):
    status, _ = api.handle("POST", "/cluster/jobs",
                           {"type": "vzdump", "id": "t-jobs",
                            "pool": "prod", "storage": "pbs1",
                            "schedule": "02:00"})
    assert status == 200
    assert _job(api, "t-jobs")["pool"] == "prod"
    status, _ = api.handle("POST", "/cluster/jobs",
                           {"type": "scleanup", "id": "t-clean",
                            "storage": "pbs1"})
    assert status == 400  # only vzdump jobs are modeled


def test_prune_backups_object_roundtrip(provider, api):
    """PVE 8 GET returns prune-backups as an object; the fake stores what
    the client sent — the round-trip must not collapse it."""
    policy = "keep-daily=7,keep-weekly=4"
    provider.cluster.create_backup_job(
        {"id": "t-prune", "vmid": "100", "storage": "pbs1",
         "schedule": "02:00", "prune-backups": policy}, pve_major=7)
    job = _job(api, "t-prune")
    assert job["prune-backups"] == policy
    api.handle("PUT", "/cluster/backup/t-prune",
               {"prune-backups": "keep-daily=5,keep-weekly=4,keep-monthly=6"})
    job = _job(api, "t-prune")
    assert job["prune-backups"] == "keep-daily=5,keep-weekly=4,keep-monthly=6"
    assert "keep-last" not in str(job)
