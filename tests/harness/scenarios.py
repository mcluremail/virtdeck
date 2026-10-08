"""M4.0: reusable fake scenarios (the fleet shape for Fleet Health).

The scenario mimics the B24 data: heterogeneous nodes (PVE version
drift), qemu/lxc/template, three backup jobs covering all semantics
(all:1+exclude / pool / vmid[]), a storage with usage and an rrddata
trend, snapshots, tasks — plus a PBS with two vm/101 backups (fresh/
old) and a host group.
"""

from __future__ import annotations

from .fake_pbs import FakePbsApi
from .fake_pve import FakePveApi


def make_pve_cluster(name: str = "fake1") -> FakePveApi:
    api = FakePveApi(name)
    api.add_node("pve01", 8, 2, 4)
    api.add_node("pve02", 7, 4, 3)
    api.add_qemu("pve01", 101, "web01", pool="prod")
    api.add_qemu("pve01", 102, "db01")
    api.add_qemu("pve02", 201, "tmpl-win", template=True)
    api.add_lxc("pve02", 301, "cache01", pool="prod")
    api.add_backup_job(job_id="bz-all", all_vms=True, exclude="201",
                       storage="pbs1", schedule="02:30")
    api.add_backup_job(job_id="bz-pool", pool="prod", storage="nfs1",
                       schedule="sun 03:00")
    api.add_backup_job(job_id="bz-list", vmid="101,301", storage="local",
                       enabled=0)
    api.add_storage("local")
    api.add_storage("pbs1", stype="pbs", shared=True)
    api.set_storage_usage("pve01", "local", 100 << 30, 80 << 30)
    api.set_storage_rrddata("pve01", "local", [
        {"time": 1727700000 + i * 3600, "used": 70.0 + i, "total": 100.0}
        for i in range(5)
    ])
    api.add_snapshot("pve01", 101, "pre-upgrade", time=1727740800)
    api.add_task("pve01",
                 "UPID:pve01:00000001:00000000:00000000:vzdump:101:root@pam:",
                 starttime=1727827200)
    api.add_task("pve01",
                 "UPID:pve01:00000002:00000000:00000000:vzdump:102:root@pam:",
                 starttime=1727827300)
    api.add_task("pve02",
                 "UPID:pve02:00000003:00000000:00000000:vzdump:301:root@pam:",
                 starttime=1727827400, status="stopped: exit code 1")
    return api


def make_pbs(user: str = "root@pam", password: str = "secret") -> FakePbsApi:
    api = FakePbsApi(user, password)
    api.add_datastore("main", total=10 << 30, used=4 << 30)
    api.add_snapshot("main", backup_id=101, backup_type="vm",
                     backup_time=1727827200)
    api.add_snapshot("main", backup_id=101, backup_type="vm",
                     backup_time=1727740800)
    api.add_snapshot("main", backup_id=999, backup_type="host",
                     backup_time=1727740800)
    return api
