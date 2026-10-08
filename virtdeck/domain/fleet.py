"""Domain: Fleet Health models and pure aggregation (M4.2).

The report is assembled from independent read-only sources (resources,
backup jobs, task history, node versions, storage usage); each source
may fail separately — a partial collection is reflected in ``errors``
and ``complete=False``, the report stays useful ("data as of HH:MM" —
``generated_at`` + the error list). Coverage matching lives in
``backup_coverage``; this module only aggregates and assembles the
report.

"Last successful backup" (B24) — from two sources:
- task history (vzdump tasks): available on any cluster, no mapping;
- PBS snapshots (``client.snapshots``) — more precise, passed in as a
  ready ``{(backup-type, backup-id): ts}`` mapping.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace

from .backup_coverage import BackupJob, Coverage, Guest, compute_coverage

# PBS backup-type for PVE guest types.
_PBS_TYPE = {"qemu": "vm", "lxc": "lxc"}

_UPID_TYPE_SLOT = 5
_UPID_VMID_SLOT = 6
_UPID_START_SLOT = 4


def _upid_field(upid: str, slot: int) -> str:
    """UPID slot: UPID:<node>:<pid>:<pstart>:<starttime>:<type>:<vmid>:<user>."""
    parts = upid.split(":")
    return parts[slot] if len(parts) > slot else ""


@dataclass(frozen=True)
class GuestBackupState:
    """Backup state of one guest (across all sources)."""

    vmid: int
    task_last_ok: int | None = None
    """Epoch of the last successful vzdump task."""
    task_last_attempt: int | None = None
    """Epoch of the last vzdump task (any, including unfinished)."""
    task_last_failed: int | None = None
    """Epoch of the last failed vzdump task."""
    pbs_last_ok: int | None = None
    """Epoch of the last PBS snapshot without a failed verification."""

    @property
    def last_successful(self) -> int | None:
        values = [t for t in (self.task_last_ok, self.pbs_last_ok)
                  if t is not None]
        return max(values) if values else None

    @property
    def ever_backed_up(self) -> bool:
        return self.last_successful is not None


@dataclass(frozen=True)
class CollectError:
    """Collection error of a single source of a single cluster."""

    cluster: str
    source: str
    """'resources' | 'backup_jobs' | 'tasks' | 'version:<node>' | ..."""
    message: str


@dataclass(frozen=True)
class ClusterFleetReport:
    """Collected report for one cluster as of generated_at."""

    cluster: str
    generated_at: int
    complete: bool
    errors: tuple[CollectError, ...]
    guests: tuple[Guest, ...]
    coverage: Coverage | None
    """None — if resources or backup jobs could not be collected."""
    backup_states: Mapping[int, GuestBackupState]
    node_versions: Mapping[str, str]
    """node → pveversion raw (drift, M4.3)."""
    storage_usage: tuple[dict, ...]
    """/nodes/{node}/storage rows tagged 'node' (runway, M4.3)."""


@dataclass(frozen=True)
class FleetReport:
    """Summary over all independent clusters ("the whole fleet at a glance")."""

    generated_at: int
    """Earliest generated_at of the members — an honest "data as of HH:MM"."""
    clusters: tuple[ClusterFleetReport, ...]

    @property
    def complete(self) -> bool:
        return all(c.complete for c in self.clusters)

    @property
    def errors(self) -> tuple[CollectError, ...]:
        return tuple(e for c in self.clusters for e in c.errors)


def merge_fleet_reports(reports: Sequence[ClusterFleetReport]) -> FleetReport:
    """Merge cluster reports (collection may run in parallel)."""
    return FleetReport(
        generated_at=min((r.generated_at for r in reports), default=0),
        clusters=tuple(reports),
    )


def _task_aggregates(tasks: Sequence[dict]) -> dict[int, dict]:
    """vzdump tasks per vmid: latest ok/attempt/failed (by starttime)."""
    agg: dict[int, dict] = {}
    for row in tasks:
        upid = str(row.get("upid") or "")
        task_type = str(row.get("type") or _upid_field(upid, _UPID_TYPE_SLOT))
        if task_type != "vzdump":
            continue
        vmid = _row_vmid(row, upid)
        if vmid is None:
            continue
        starttime = _row_starttime(row, upid)
        bucket = agg.setdefault(vmid, {"vmid": vmid, "task_last_ok": None,
                                       "task_last_attempt": None,
                                       "task_last_failed": None})
        if starttime is not None \
                and (bucket["task_last_attempt"] is None
                     or starttime > bucket["task_last_attempt"]):
            bucket["task_last_attempt"] = starttime
        status = row.get("status")
        if status is None:
            continue  # task still running — attempt only
        if str(status) == "OK":
            if bucket["task_last_ok"] is None \
                    or starttime > bucket["task_last_ok"]:
                bucket["task_last_ok"] = starttime
        elif bucket["task_last_failed"] is None \
                or starttime > bucket["task_last_failed"]:
            bucket["task_last_failed"] = starttime
    return agg


def _row_vmid(row: dict, upid: str) -> int | None:
    raw = row.get("vmid")
    if raw is None:
        raw = _upid_field(upid, _UPID_VMID_SLOT)
    try:
        vmid = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return vmid if vmid > 0 else None


def _row_starttime(row: dict, upid: str) -> int | None:
    """starttime: row field is int; UPID slot is hex."""
    raw = row.get("starttime")
    if raw is not None:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    slot = _upid_field(upid, _UPID_START_SLOT)
    try:
        return int(slot, 16) if slot else None
    except (TypeError, ValueError):
        return None


def last_pbs_backup_times(snapshots: Iterable[dict]) \
        -> dict[tuple[str, str], int]:
    """(backup-type, backup-id) → time of the last backup.

    Snapshots with verify-state 'failed' are excluded: a broken copy is
    not a successful backup. Missing verification ('none', '') — the
    copy still counts (it was simply never checked).
    """
    out: dict[tuple[str, str], int] = {}
    for snap in snapshots:
        if str(snap.get("verify-state") or "") == "failed":
            continue
        key = (str(snap.get("backup-type") or ""),
               str(snap.get("backup-id") or ""))
        try:
            t = int(snap.get("backup-time") or 0)
        except (TypeError, ValueError):
            continue
        if not key[1] or t <= 0:
            continue
        if t > out.get(key, 0):
            out[key] = t
    return out


def build_backup_states(tasks: Sequence[dict], guests: Sequence[Guest],
                        pbs_times: Mapping[tuple[str, str], int]
                        ) -> dict[int, GuestBackupState]:
    """Per-guest backup state: task history + optional PBS.

    Includes every scene guest ("never backed up" is a state too). A VM
    seen in tasks but missing from resources (removed between runs) gets
    its state from tasks alone.
    """
    by_vmid = {g.vmid: g for g in guests}
    states: dict[int, GuestBackupState] = {}
    for vmid, agg in _task_aggregates(tasks).items():
        states[vmid] = GuestBackupState(**agg)
    for vmid, guest in by_vmid.items():
        pbs = pbs_times.get((_PBS_TYPE.get(guest.vm_type, guest.vm_type),
                             str(vmid)))
        base = states.get(vmid, GuestBackupState(vmid=vmid))
        states[vmid] = replace(base, pbs_last_ok=pbs)
    return states


def build_cluster_report(
    *,
    cluster: str,
    generated_at: int,
    resources: Sequence[dict] | None,
    backup_jobs: Sequence[dict] | None,
    tasks: Sequence[dict] | None = None,
    node_versions: Mapping[str, str] | None = None,
    storage_usage: Sequence[dict] | None = None,
    pbs_last_backups: Mapping[tuple[str, str], int] | None = None,
    errors: Sequence[CollectError] = (),
) -> ClusterFleetReport:
    """Assemble a cluster report from collected data (pure function).

    ``resources is None`` or ``backup_jobs is None`` (source failed) →
    coverage is not computed at all, to avoid presenting a false coverage
    report based on incomplete data.
    """
    guests: tuple[Guest, ...] = ()
    coverage: Coverage | None = None
    if resources is not None:
        guests = tuple(g for g in (Guest.from_raw(r) for r in resources)
                       if g is not None)
        if backup_jobs is not None:
            jobs = [BackupJob.from_raw(j) for j in backup_jobs]
            coverage = compute_coverage(jobs, guests)
    return ClusterFleetReport(
        cluster=cluster,
        generated_at=generated_at,
        complete=not errors,
        errors=tuple(errors),
        guests=guests,
        coverage=coverage,
        backup_states=build_backup_states(tasks or (), guests,
                                          pbs_last_backups or {}),
        node_versions=dict(node_versions or {}),
        storage_usage=tuple(storage_usage or ()),
    )
