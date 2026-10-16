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

    def jobs(self) -> tuple[list[PbsJob], list[str]]:
        """All scheduled jobs with per-kind failure bookkeeping.

        Returns ``(jobs, failed_kinds)`` (audit 6.3.2b D10): a kind that
        cannot be read (e.g. missing permissions on one job type) is
        reported in ``failed_kinds`` instead of being silently dropped —
        the UI must be able to tell "no jobs" from "partly unreadable".
        When *no* kind can be read, the read failed as a whole and the
        last error is raised rather than faked as an empty list.
        """
        out: list[PbsJob] = []
        failed: list[str] = []
        last: PbsError | None = None
        for kind in ("sync", "verify", "prune"):
            try:
                raw = self._client.jobs(kind) or []
            except PbsError as exc:
                failed.append(kind)
                last = exc
                continue
            out.extend(PbsJob.from_api(kind, d) for d in raw)
        if last is not None and not out and len(failed) == 3:
            raise PbsError(
                f"could not read jobs ({', '.join(failed)}): {last}",
                last.status_code)
        return out, failed

    def run_job(self, kind: str, job_id: str) -> str:
        return self._client.run_job(kind, job_id)

    def verify_datastore(self, store: str) -> str:
        return self._client.verify_datastore(store)

    # ── task tracking (audit 6.3.3 D16) ──────────────────────────

    # Task states returned by task_status().  "unknown" is terminal
    # (stopped without a readable exit status); transient read errors
    # raise PbsError instead, so the caller's retry budget applies.
    TASK_RUNNING = "running"
    TASK_SUCCESS = "success"
    TASK_FAILED = "failed"
    TASK_UNKNOWN = "unknown"

    def task_status(self, upid: str) -> tuple[str, str]:
        """One status read for a started task; ``(state, detail)``.

        Reuses the PVE poll taxonomy (provider/_tasks.py) without
        sharing its transport.  Confirmed PBS response shape
        (``api2/node/tasks.rs``): ``status`` is 'running'|'stopped',
        stopped tasks carry ``exitstatus`` ('OK', 'Error: <msg>',
        'unknown').  A stopped task without a readable exit status is
        reported as ``unknown`` — never guessed into success or failure.
        The node is resolved via GET /nodes (PBS is single-node); a
        stale cached name is retried once with a fresh resolution.
        """
        node = self._client.node_name()
        try:
            data = self._client.task_status(node, upid)
        except PbsError as exc:
            if exc.status_code not in (400, 404):
                raise
            # stale cached node name (or unparsable UPID): re-resolve
            # once and retry — read-only, bounded
            self._client.forget_node()
            node = self._client.node_name()
            data = self._client.task_status(node, upid)
        status = data.get("status")
        if status == "running":
            return self.TASK_RUNNING, ""
        if status == "stopped":
            exitstatus = data.get("exitstatus")
            if isinstance(exitstatus, str) and exitstatus == "OK":
                return self.TASK_SUCCESS, ""
            if isinstance(exitstatus, str) and exitstatus.startswith("Error"):
                return self.TASK_FAILED, exitstatus
            # stopped without a readable exit status — outcome unknown
            return (self.TASK_UNKNOWN,
                    "task stopped but exit status is unavailable")
        raise PbsError(
            f"unexpected task status response for {upid!r} "
            f"(missing or odd 'status' field)")

    def forget_snapshot(self, snap: PbsSnapshot) -> None:
        if not snap.backup_time:
            raise PbsError("snapshot has no valid backup time")
        self._client.forget_snapshot(
            snap.store, snap.backup_type, snap.backup_id,
            int(snap.backup_time.timestamp()), ns=snap.ns)
