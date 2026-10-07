"""Domain: модели и чистая агрегация Fleet Health (M4.2).

Отчёт собирается из независимых read-only источников (resources,
backup jobs, task history, версии нод, storage usage); каждый источник
может отвалиться отдельно — частичный сбор отражается в ``errors`` и
``complete=False``, отчёт остаётся полезным («данные от HH:MM» —
``generated_at`` + перечень ошибок). Сопоставление покрытия — в
``backup_coverage``; здесь только агрегация и сборка отчёта.

«Последний успешный бэкап» (B24) — из двух источников:
- task history (vzdump-таски): есть на любом кластере, без маппинга;
- PBS-снапшоты (``client.snapshots``) — точнее, передаются готовым
  маппингом ``{(backup-type, backup-id): ts}``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace

from .backup_coverage import BackupJob, Coverage, Guest, compute_coverage

# backup-type в PBS для типов гостей PVE.
_PBS_TYPE = {"qemu": "vm", "lxc": "lxc"}

_UPID_TYPE_SLOT = 5
_UPID_VMID_SLOT = 6
_UPID_START_SLOT = 4


def _upid_field(upid: str, slot: int) -> str:
    """Слот UPID: UPID:<node>:<pid>:<pstart>:<starttime>:<type>:<vmid>:<user>."""
    parts = upid.split(":")
    return parts[slot] if len(parts) > slot else ""


@dataclass(frozen=True)
class GuestBackupState:
    """Состояние бэкапов одного гостя (по всем источникам)."""

    vmid: int
    task_last_ok: int | None = None
    """Epoch последнего успешного vzdump-таска."""
    task_last_attempt: int | None = None
    """Epoch последнего vzdump-таска (любого, включая незавершённый)."""
    task_last_failed: int | None = None
    """Epoch последнего завершившегося неудачей vzdump-таска."""
    pbs_last_ok: int | None = None
    """Epoch последнего PBS-снапшота без failed-верификации."""

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
    """Ошибка сбора одного источника одного кластера."""

    cluster: str
    source: str
    """'resources' | 'backup_jobs' | 'tasks' | 'version:<node>' | ..."""
    message: str


@dataclass(frozen=True)
class ClusterFleetReport:
    """Собранный отчёт по одному кластеру на момент generated_at."""

    cluster: str
    generated_at: int
    complete: bool
    errors: tuple[CollectError, ...]
    guests: tuple[Guest, ...]
    coverage: Coverage | None
    """None — если resources или backup jobs собрать не удалось."""
    backup_states: Mapping[int, GuestBackupState]
    node_versions: Mapping[str, str]
    """node → pveversion raw (drift, M4.3)."""
    storage_usage: tuple[dict, ...]
    """Строки /nodes/{node}/storage, помеченные 'node' (runway, M4.3)."""


@dataclass(frozen=True)
class FleetReport:
    """Сводка по всем независимым кластерам («весь парк одним взглядом»)."""

    generated_at: int
    """Самый ранний generated_at участников — честное «данные от HH:MM»."""
    clusters: tuple[ClusterFleetReport, ...]

    @property
    def complete(self) -> bool:
        return all(c.complete for c in self.clusters)

    @property
    def errors(self) -> tuple[CollectError, ...]:
        return tuple(e for c in self.clusters for e in c.errors)


def merge_fleet_reports(reports: Sequence[ClusterFleetReport]) -> FleetReport:
    """Объединить отчёты кластеров (сбор может идти параллельно)."""
    return FleetReport(
        generated_at=min((r.generated_at for r in reports), default=0),
        clusters=tuple(reports),
    )


def _task_aggregates(tasks: Sequence[dict]) -> dict[int, dict]:
    """vzdump-таски по vmid: последние ok/attempt/failed (по starttime)."""
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
            continue  # таск ещё выполняется — только attempt
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
    """starttime: поле строки — int; слот UPID — hex."""
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
    """(backup-type, backup-id) → время последнего бэкапа.

    Снапшоты с verify-state 'failed' исключаются: сломанная копия не
    считается успешным бэкапом. Отсутствие верификации ('none', '') —
    копия учитывается (её просто не проверяли).
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
    """Состояние бэкапов на гостя: task history + опционально PBS.

    Включает каждого гостя сцены (и «никогда не бэкапился» — тоже
    состояние). ВМ, виденная в тасках, но отсутствующая в resources
    (удалена между запусками), получает состояние по таскам.
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
    """Собрать отчёт кластера из собранных данных (чистая функция).

    ``resources is None`` или ``backup_jobs is None`` (источник упал) →
    coverage не считается вовсе, чтобы не предъявлять ложный отчёт о
    покрытии на неполных данных.
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
