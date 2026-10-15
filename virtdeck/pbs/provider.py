"""PbsProvider — typed facade over PbsClient for PBS data (B17 stage 2).

Methods return domain models (``virtdeck.domain.pbs``); errors raise
``PbsError``. Used by plugin dispatch (``cfg["type"] == "pbs"``) and by
UI workers.
"""

from __future__ import annotations

from ..domain.pbs import PbsDatastore, PbsJob, PbsSnapshot
from .client import PbsClient, PbsError


class PbsProvider:
    """PBS data source: datastores, snapshots, jobs."""

    id = "pbs"
    name = "Proxmox Backup Server"

    def __init__(self, cfg: dict, timeout: float = 15):
        self._cfg = cfg
        self._client = PbsClient(cfg, timeout=timeout)

    @property
    def client(self) -> PbsClient:
        return self._client

    def close(self) -> None:
        """Release the underlying HTTP session."""
        self._client.close()

    # ── datastores ───────────────────────────────────────────────

    def datastores(self) -> list[PbsDatastore]:
        """All datastores with usage (config list + per-store status)."""
        cfgs = self._client.datastores()
        out: list[PbsDatastore] = []
        for d in cfgs:
            name = d.get("store", d.get("name", ""))
            if not name:
                continue
            try:
                status = self._client.datastore_status(name)
            except PbsError:
                status = None  # unreadable — not the same as zero (D1)
            out.append(PbsDatastore.build(d, status))
        return out

    def namespaces(self, store: str, parent: str = "") -> list[str]:
        """Namespace names below ``parent`` (excluding parent itself)."""
        items = self._client.namespaces(store, parent=parent)
        out: list[str] = []
        for d in items:
            name = d.get("ns", d.get("name", ""))
            if name and name not in out:
                out.append(name)
        return out

    # ── snapshots ────────────────────────────────────────────────

    def snapshots(self, store: str, ns: str = "") -> list[PbsSnapshot]:
        raw = self._client.snapshots(store, ns=ns) or []
        return [PbsSnapshot.from_api(store, d) for d in raw]

    # ── jobs ─────────────────────────────────────────────────────

    def jobs(self) -> list[PbsJob]:
        out: list[PbsJob] = []
        for kind in ("sync", "verify", "prune"):
            try:
                raw = self._client.jobs(kind) or []
            except PbsError:
                continue
            out.extend(PbsJob.from_api(kind, d) for d in raw)
        return out

    def run_job(self, kind: str, job_id: str) -> str:
        return self._client.run_job(kind, job_id)

    def verify_datastore(self, store: str) -> str:
        return self._client.verify_datastore(store)

    def forget_snapshot(self, snap: PbsSnapshot) -> None:
        if not snap.backup_time:
            raise PbsError("snapshot has no valid backup time")
        self._client.forget_snapshot(
            snap.store, snap.backup_type, snap.backup_id,
            int(snap.backup_time.timestamp()), ns=snap.ns)
