"""ClusterAPI — cluster-level PVE endpoints.

Covers: /cluster/resources, /cluster/status, /cluster/nextid,
/cluster/ha/groups, /cluster/ha/resources, /cluster/backup, /cluster/jobs,
/cluster/config/nodes.
"""

from __future__ import annotations

from ._errors import (
    ProxmoxApiError,
    ProxmoxNotFoundError,
    ProxmoxTimeoutError,
)
from ._session import ProxmoxSession, _q


class ClusterAPI:
    """Cluster-level PVE API methods."""

    def __init__(self, session: ProxmoxSession) -> None:
        self._s = session
        # None = /cluster/jobs availability not probed yet (PVE8+ has it,
        # PVE7 does not).  Probed lazily with a harmless GET and cached for
        # the provider's lifetime.
        self._jobs_endpoint: bool | None = None

    def list_resources(self) -> list[dict]:
        """GET /cluster/resources — all nodes/vms/storages."""
        return self._s.call(self._s.proxmox.cluster.resources.get)

    def get_status(self) -> list[dict]:
        """GET /cluster/status — cluster quorum and node list."""
        return self._s.call(self._s.proxmox.cluster.status.get)

    def get_config_nodes(self) -> list[dict]:
        """GET /cluster/config/nodes — corosync node config."""
        return self._s.call(self._s.proxmox.cluster.config.nodes.get)

    def next_vmid(self) -> int:
        """GET /cluster/nextid — next free VMID."""
        result = self._s.call(self._s.proxmox.cluster.nextid.get)
        if isinstance(result, str):
            return int(result)
        if isinstance(result, dict):
            return int(result.get("data", result))
        return int(result)

    # -- Storage config (B4) --

    # NOTE: storage config CRUD lives at top-level /storage, NOT /cluster/storage
    # (verified against pve-manager PVE/API2.pm: subclass mounted at path 'storage').

    def list_storage_configs(self) -> list[dict]:
        """GET /storage — all storage definitions."""
        return self._s.call(self._s.proxmox.storage.get)

    def get_storage_config(self, storage: str) -> dict:
        """GET /storage/{storage} — single storage definition."""
        return self._s.call(self._s.proxmox.storage(_q(storage)).get)

    def create_storage(self, **params) -> object:
        """POST /storage — create a storage definition."""
        return self._s.call(self._s.proxmox.storage.post, **params)

    def update_storage(self, storage: str, **params) -> object:
        """PUT /storage/{storage} — update a storage definition."""
        return self._s.call(
            self._s.proxmox.storage(_q(storage)).put, **params
        )

    def delete_storage(self, storage: str) -> object:
        """DELETE /storage/{storage}."""
        return self._s.call(self._s.proxmox.storage(_q(storage)).delete)

    # -- Cluster join (B12a) --

    def get_join_info(self, node: str | None = None) -> dict:
        """GET /cluster/config/join — join info of this cluster."""
        if node:
            return self._s.call(self._s.proxmox.cluster.config.join.get, node=node)
        return self._s.call(self._s.proxmox.cluster.config.join.get)

    def create_cluster(self, *, clustername: str,
                       link0: str | None = None) -> object:
        """POST /cluster/config — create a new cluster on THIS node.

        pvecm create equivalent; executed on the first (sole) member. If no
        link is given, PVE defaults to the local IP address as link0.
        """
        params: dict = {"clustername": clustername}
        if link0:
            params["link0"] = link0
        return self._s.call(self._s.proxmox.cluster.config.post, **params)

    def join_cluster(self, *, hostname: str, password: str,
                     fingerprint: str | None = None, link0: str | None = None,
                     votes: int | None = None) -> object:
        """POST /cluster/config/join — join THIS node into an existing cluster.

        Executed on the joinee; blocks until the join completes (service
        restarts, minutes) — workers must use a generous timeout.
        """
        params: dict = {"hostname": hostname, "password": password}
        if fingerprint:
            params["fingerprint"] = fingerprint
        if link0:
            params["link0"] = link0
        if votes is not None:
            params["votes"] = votes
        return self._s.call(self._s.proxmox.cluster.config.join.post, **params)

    # -- HA groups --

    def list_ha_groups(self) -> list[dict]:
        """GET /cluster/ha/groups."""
        return self._s.call(self._s.proxmox.cluster.ha.groups.get)

    def list_ha_resources(self) -> list[dict]:
        """GET /cluster/ha/resources."""
        return self._s.call(self._s.proxmox.cluster.ha.resources.get)

    def add_ha_resource(self, **params) -> object:
        """POST /cluster/ha/resources."""
        return self._s.call(self._s.proxmox.cluster.ha.resources.post, **params)

    def delete_ha_resource(self, sid: str) -> object:
        """DELETE /cluster/ha/resources/{sid}."""
        return self._s.call(self._s.proxmox.cluster.ha.resources(_q(sid)).delete)

    # -- Backup / jobs --

    def list_backup_jobs(self) -> list[dict]:
        """GET /cluster/backup — backup jobs (PVE7 and PVE8 fallback)."""
        return self._s.call(self._s.proxmox.cluster.backup.get)

    def list_jobs(self) -> list[dict]:
        """GET /cluster/jobs — all scheduled jobs (PVE8+)."""
        return self._s.call(self._s.proxmox.cluster.jobs.get)

    def _jobs_data(self) -> list | None:
        """GET /cluster/jobs data, or None when the endpoint is absent.

        The availability probe is cached for the provider's lifetime:
        PVE8+ serves /cluster/jobs, PVE7 answers 404/501.  Anything else
        (auth, validation, network, timeout) propagates — a failure must
        not be mistaken for an old PVE.
        """
        if self._jobs_endpoint is False:
            return None
        try:
            data = self._s.call(self._s.proxmox.cluster.jobs.get)
            self._jobs_endpoint = True
            return data
        except ProxmoxApiError as exc:
            if exc.status_code in (404, 501):
                self._jobs_endpoint = False
                return None
            raise
        except ProxmoxNotFoundError:
            self._jobs_endpoint = False
            return None

    def _use_jobs_path(self, pve_major: int) -> bool:
        """True when writes should target /cluster/jobs (PVE8+ and present).

        On first use in this session the availability probe (a harmless
        GET) runs; afterwards the cached answer decides, so a write never
        fails over to the legacy path after a failed/timed-out request —
        the decision is made BEFORE the write is issued.
        """
        if pve_major < 8:
            return False
        if self._jobs_endpoint is None:
            self._jobs_data()
        return bool(self._jobs_endpoint)

    @staticmethod
    def _raise_ambiguous(exc: Exception, action: str) -> None:
        """Re-raise a timeout as an explicit "outcome unknown" error.

        A timed-out write may still have been applied by the server; the
        caller (UI) must offer refreshing the job list, not retrying.
        """
        raise type(exc)(
            f"{exc}; {action} may still have been applied on the server — "
            f"refresh the job list to verify"
        ) from exc

    def list_all_jobs(self, pve_major: int = 7) -> list[dict]:
        """List vzdump jobs, trying /cluster/jobs first on PVE8+.

        Falls back to /cluster/backup only when /cluster/jobs is
        provably absent (PVE7).  Other errors propagate so the UI shows
        them instead of an empty job list.
        """
        data = self._jobs_data() if pve_major >= 8 else None
        if data is not None:
            if isinstance(data, dict):
                data = data.get("data", data)
            if isinstance(data, list):
                return [j for j in data if j.get("type", "vzdump") == "vzdump"]
        data = self.list_backup_jobs()
        if isinstance(data, dict):
            data = data.get("data", data)
        return data if isinstance(data, list) else []

    def create_backup_job(self, params: dict, pve_major: int = 7) -> object:
        """POST /cluster/jobs (PVE8+) or /cluster/backup (legacy path).

        The path is decided before the request (see _use_jobs_path); a
        timed-out creation is never retried automatically — the server
        may have created the job, and a silent second POST would
        duplicate it.  Timeouts are re-raised with an explicit "outcome
        unknown" hint.
        """
        if self._use_jobs_path(pve_major):
            p = dict(params)
            p["type"] = "vzdump"
            try:
                return self._s.call(self._s.proxmox.cluster.jobs.post, **p)
            except ProxmoxTimeoutError as exc:
                self._raise_ambiguous(exc, "job creation")
        return self._s.call(self._s.proxmox.cluster.backup.post, **params)

    def update_backup_job(self, job_id: str, params: dict, pve_major: int = 7) -> object:
        """PUT /cluster/jobs/{id} (PVE8+) or /cluster/backup/{id}.

        Same policy as create: the path is decided up front, errors from
        the primary path propagate (a 404 there means the job itself is
        absent), and a timeout is re-raised as "outcome unknown".
        """
        p = {k: v for k, v in params.items() if k != "id"}
        if self._use_jobs_path(pve_major):
            pj = dict(p)
            pj["type"] = "vzdump"
            try:
                return self._s.call(
                    self._s.proxmox.cluster.jobs(_q(job_id)).put, **pj
                )
            except ProxmoxTimeoutError as exc:
                self._raise_ambiguous(exc, "the update")
        return self._s.call(self._s.proxmox.cluster.backup(_q(job_id)).put, **p)

    def delete_backup_job(self, job_id: str, pve_major: int = 7) -> object:
        """DELETE /cluster/jobs/{id} (PVE8+) or /cluster/backup/{id}.

        No automatic retry after a timeout: the server may have deleted
        the job even though the client saw no answer.  The timeout is
        re-raised with an explicit "outcome unknown" hint so the UI can
        suggest refreshing the job list instead of a blind retry.
        """
        if self._use_jobs_path(pve_major):
            try:
                return self._s.call(
                    self._s.proxmox.cluster.jobs(_q(job_id)).delete
                )
            except ProxmoxTimeoutError as exc:
                self._raise_ambiguous(exc, "the deletion")
        return self._s.call(self._s.proxmox.cluster.backup(_q(job_id)).delete)
