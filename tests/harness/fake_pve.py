"""M4.0: FakePveApi — in-memory PVE-кластер для тестов Fleet Health.

Состояние кластера собирается fluent-методами (сценарий), запросы
обслуживает `handle(method, path, params)` — PVE API2 JSON-конверт
(`{"data": ...}`). Пути — без префикса `/api2/json`. `api.calls` пишет
каждый запрос (для утверждений о fan-out). `api.fail` имитирует частичный
сбой (path-префикс → (status, message)) — фундамент семантики partial
failure («данные от HH:MM»).
"""

from __future__ import annotations


def _pve_manager_version(major: int, minor: int, patch: int) -> str:
    return f"pve-manager/{major}.{minor}.{patch}/a1b2c3d4e5f6g7h8"


class FakePveApi:
    """Сценарий одного независимого PVE-кластера."""

    def __init__(self, name: str = "fake1"):
        self.name = name
        self.calls: list[tuple[str, str, dict]] = []
        # path-префикс → (status, message): имитация частичного сбоя.
        self.fail: dict[str, tuple[int, str]] = {}

        self.nodes: dict[str, dict] = {}          # node → {version, status}
        self.qemu: dict[str, list[dict]] = {}     # node → [guest dicts]
        self.lxc: dict[str, list[dict]] = {}
        self.backup_jobs: list[dict] = []
        self.storage_cfg: list[dict] = []         # /cluster/storage
        self.storage_usage: dict[tuple[str, str], dict] = {}
        self.node_rrddata: dict[str, list[dict]] = {}
        self.storage_rrddata: dict[tuple[str, str], list[dict]] = {}
        self.snapshots: dict[tuple[str, int], list[dict]] = {}
        self.tasks: list[dict] = []
        self._resources: list[dict] | None = None  # override /cluster/resources
        self._job_seq = 0

    # ── Сценарий ────────────────────────────────────────────────────

    def add_node(self, node: str, major: int = 8, minor: int = 2,
                 patch: int = 4, status: dict | None = None) -> FakePveApi:
        version = _pve_manager_version(major, minor, patch)
        self.nodes[node] = {
            "version": version,
            "status": status if status is not None else {
                "pveversion": version, "uptime": 86400,
                "cpu": 0.1, "memory": {"used": 4 << 30, "total": 16 << 30},
                "kversion": "Linux 6.8",
            },
        }
        self.qemu.setdefault(node, [])
        self.lxc.setdefault(node, [])
        return self

    def add_qemu(self, node: str, vmid: int, name: str,
                 status: str = "running", template: bool = False,
                 pool: str = "", **extra) -> FakePveApi:
        vm = {"vmid": vmid, "name": name, "status": status,
              "template": 1 if template else 0, "pool": pool,
              "node": node, "maxmem": 2 << 30, "maxcpu": 2}
        vm.update(extra)
        self.qemu[node].append(vm)
        return self

    def add_lxc(self, node: str, vmid: int, name: str,
                status: str = "running", pool: str = "",
                **extra) -> FakePveApi:
        ct = {"vmid": vmid, "name": name, "status": status, "pool": pool,
              "node": node, "maxmem": 512 << 20, "maxcpu": 1}
        ct.update(extra)
        self.lxc[node].append(ct)
        return self

    def add_backup_job(self, *, job_id: str | None = None, storage: str = "pbs1",
                       schedule: str = "daily", enabled: int = 1,
                       all_vms: bool = False, vmid: str = "",
                       exclude: str = "", pool: str = "",
                       mailnotification: str = "always") -> FakePveApi:
        """Джоб из GET /cluster/backup: all:1 / vmid[] / pool / exclude."""
        self._job_seq += 1
        job = {"id": job_id or f"job-{self._job_seq:03d}",
               "enabled": enabled, "schedule": schedule, "storage": storage,
               "mode": "snapshot", "compress": "zstd",
               "mailnotification": mailnotification}
        if all_vms:
            job["all"] = 1
        if vmid:
            job["vmid"] = vmid
        if exclude:
            job["exclude"] = exclude
        if pool:
            job["pool"] = pool
        self.backup_jobs.append(job)
        return self

    def add_storage(self, store: str, stype: str = "dir",
                    content: str = "images,rootdir", nodes: str = "",
                    shared: bool = False) -> FakePveApi:
        self.storage_cfg.append({"storage": store, "type": stype,
                                 "content": content, "nodes": nodes,
                                 "shared": 1 if shared else 0, "enable": 1})
        return self

    def set_storage_usage(self, node: str, store: str, total: int,
                          used: int) -> FakePveApi:
        self.storage_usage[(node, store)] = {
            "storage": store, "node": node, "type": "dir", "content":
            "images,rootdir", "total": total, "used": used, "avail":
            max(0, total - used), "active": 1, "enabled": 1, "shared": 0}
        return self

    def set_node_rrddata(self, node: str, series: list[dict]) -> FakePveApi:
        self.node_rrddata[node] = series
        return self

    def set_storage_rrddata(self, node: str, store: str,
                            series: list[dict]) -> FakePveApi:
        self.storage_rrddata[(node, store)] = series
        return self

    def add_snapshot(self, node: str, vmid: int, name: str,
                     vm_type: str = "qemu", time: int = 1727740800,
                     description: str = "") -> FakePveApi:
        self.snapshots.setdefault((node, vmid), []).append({
            "name": name, "snaptime": time, "description": description,
            "vmstate": 0})
        return self

    def add_task(self, node: str, upid: str, task_type: str = "vzdump",
                 status: str | None = "OK", starttime: int | None = None,
                 **extra) -> FakePveApi:
        task = {"upid": upid, "node": node, "type": task_type,
                "status": status}
        if starttime is not None:
            task["starttime"] = starttime
        task.update(extra)
        self.tasks.append(task)
        return self

    def override_resources(self, entries: list[dict]) -> FakePveApi:
        """Жёсткий override /cluster/resources (иначе выводится из сцены)."""
        self._resources = entries
        return self

    # ── Обслуживание запросов ───────────────────────────────────────

    def _derived_resources(self) -> list[dict]:
        rows: list[dict] = []
        for node, meta in self.nodes.items():
            st = meta["status"]
            rows.append({"type": "node", "node": node, "status": "online",
                         "cpu": st.get("cpu", 0.0),
                         "maxcpu": 8, "mem": st.get("memory", {}).get("used", 0),
                         "maxmem": st.get("memory", {}).get("total", 1),
                         "id": f"node/{node}"})
            for vm in self.qemu[node]:
                rows.append({**vm, "type": "qemu", "id": f"qemu/{vm['vmid']}"})
            for ct in self.lxc[node]:
                rows.append({**ct, "type": "lxc", "id": f"lxc/{ct['vmid']}"})
        return rows

    def handle(self, method: str, path: str,
               params: dict | None = None) -> tuple[int, object]:
        """(method, path, params) → (status, data). path без /api2/json."""
        params = dict(params or {})
        self.calls.append((method, path, params))

        for prefix, (status, message) in self.fail.items():
            if path.lstrip("/").startswith(prefix):
                return status, {"errors": message}

        parts = [p for p in path.strip("/").split("/") if p]

        if method == "GET":
            if parts[:2] == ["cluster", "resources"]:
                return 200, self._resources if self._resources is not None \
                    else self._derived_resources()
            if parts[:2] == ["cluster", "backup"]:
                return 200, list(self.backup_jobs)
            if parts[:2] == ["cluster", "storage"]:
                return 200, list(self.storage_cfg)
            if parts[:2] == ["cluster", "tasks"]:
                return 200, list(self.tasks)
            if parts[:1] == ["nodes"] and len(parts) == 1:
                return 200, [{"node": n, "status": "online"}
                             for n in self.nodes]
            if len(parts) >= 2 and parts[0] == "nodes":
                node = parts[1]
                if node not in self.nodes:
                    return 500, {"errors": f"no such node: {node}"}
                meta = self.nodes[node]
                rest = parts[2:]
                if rest == ["version"]:
                    return 200, {"version": "8.2.4", "release": "8.2",
                                 "pveversion": meta["version"],
                                 "repoid": "a1b2c3d4"}
                if rest == ["status"]:
                    return 200, dict(meta["status"])
                if rest in (["qemu"], ["lxc"]):
                    guests = self.qemu[node] if rest[0] == "qemu" \
                        else self.lxc[node]
                    return 200, list(guests)
                if rest == ["rrddata"]:
                    return 200, list(self.node_rrddata.get(node, []))
                if rest == ["storage"]:
                    return 200, [u for (n, _s), u in self.storage_usage.items()
                                 if n == node]
                if rest == ["tasks"]:
                    return 200, [t for t in self.tasks if t["node"] == node]
                if len(rest) == 3 and rest[0] == "storage" \
                        and rest[2] == "rrddata":
                    return 200, list(self.storage_rrddata.get(
                        (node, rest[1]), []))
                if len(rest) == 2 and rest[0] == "storage":
                    usage = self.storage_usage.get((node, rest[1]))
                    if usage is None:
                        return 500, {"errors": f"no storage {rest[1]}"}
                    return 200, dict(usage)
                if len(rest) == 3 and rest[0] in ("qemu", "lxc") \
                        and rest[2] == "snapshot":
                    return 200, list(self.snapshots.get((node, int(rest[1])),
                                                        []))
                if len(rest) == 3 and rest[0] in ("qemu", "lxc") \
                        and rest[2] == "rrddata":
                    return 200, []
                if len(rest) == 2 and rest[0] in ("qemu", "lxc") \
                        and rest[1].isdigit():
                    vmid = int(rest[1])
                    for vm in self.qemu[node] + self.lxc[node]:
                        if vm["vmid"] == vmid:
                            return 200, dict(vm)
                return 404, {"errors": f"no handler: {method} {path}"}
            return 404, {"errors": f"no handler: {method} {path}"}

        return 404, {"errors": f"no handler: {method} {path}"}
