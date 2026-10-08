"""Domain: backup coverage matching engine (Fleet Health, M4.1).

Pure client-side matching of "backup jobs × guests" from
`GET /cluster/backup` and `GET /cluster/resources` data — no Qt, no API,
no state. This engine determines the trustworthiness of the entire
Fleet Health report, so the guest-selection semantics of a vzdump job
are fixed explicitly (following PVE::VZDump behavior):

1. Templates are never backed up — they stay out of the report (exempt),
   even if listed in the job's vmid[]. Otherwise it's a false positive
   from the first run.
2. ``all=1`` → all non-templates minus ``exclude``. ``exclude`` without
   ``all`` is ignored (vzdump does not apply it).
3. ``pool`` → all pool members on any nodes, including stopped guests
   (status does not participate in matching).
4. ``vmid`` → explicit list.
5. PVE field priority: ``all`` > ``pool`` > ``vmid`` — with a
   combination, the first one wins.
6. ``enabled=0`` job covers nobody.
7. Job overlaps are allowed: a guest may be covered by several.
8. A guest moves between pools between runs → the engine is stateless,
   the report is recomputed each time from fresh resources.

API anomalies are handled deterministically: a duplicate vmid in guests —
the first row encountered wins; garbage in the vmid/exclude list is
skipped; a job without all/pool/vmid selects nobody but remains visible
in ``by_job`` (empty set)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


def _truthy(value: object) -> bool:
    """PVE returns 0/1; also accept bool and string '0'/'1'."""
    if isinstance(value, str):
        return value.strip() not in ("", "0")
    return bool(value)


def _parse_vmid_list(value: object) -> tuple[int, ...]:
    """'101, 102' → (101, 102); None/'' → (); garbage is skipped."""
    if not value:
        return ()
    out: list[int] = []
    for part in str(value).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return tuple(out)


@dataclass(frozen=True)
class BackupJob:
    """Backup job from GET /cluster/backup (normalized)."""

    job_id: str
    enabled: bool = True
    all_vms: bool = False
    vmids: frozenset[int] = frozenset()
    exclude: frozenset[int] = frozenset()
    pool: str = ""
    schedule: str = ""
    storage: str = ""

    @classmethod
    def from_raw(cls, raw: dict) -> BackupJob:
        return cls(
            job_id=str(raw.get("id") or ""),
            enabled=_truthy(raw.get("enabled", 1)),
            all_vms=_truthy(raw.get("all", 0)),
            vmids=frozenset(_parse_vmid_list(raw.get("vmid"))),
            exclude=frozenset(_parse_vmid_list(raw.get("exclude"))),
            pool=str(raw.get("pool") or ""),
            schedule=str(raw.get("schedule") or ""),
            storage=str(raw.get("storage") or ""),
        )

    def selects(self, guest: Guest) -> bool:
        """Whether the job covers the guest (vzdump semantics, see module doc)."""
        if not self.enabled or guest.template:
            return False
        if self.all_vms:
            return guest.vmid not in self.exclude
        if self.pool:
            return guest.pool == self.pool
        return guest.vmid in self.vmids


@dataclass(frozen=True)
class Guest:
    """Guest from GET /cluster/resources (normalized)."""

    vmid: int
    name: str = ""
    node: str = ""
    vm_type: str = "qemu"  # qemu | lxc
    pool: str = ""
    template: bool = False

    @classmethod
    def from_raw(cls, raw: dict) -> Guest | None:
        """From a /cluster/resources row; None for non-guests or missing vmid."""
        gtype = raw.get("type", "")
        if gtype not in ("qemu", "lxc"):
            return None
        try:
            vmid = int(raw.get("vmid"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return cls(
            vmid=vmid,
            name=str(raw.get("name") or ""),
            node=str(raw.get("node") or ""),
            vm_type=gtype,
            pool=str(raw.get("pool") or ""),
            template=_truthy(raw.get("template", 0)),
        )


@dataclass(frozen=True)
class Coverage:
    """Matching result for one cluster.

    ``covered`` / ``uncovered`` / ``exempt`` are disjoint and cover all
    scene guests. ``by_job`` includes every enabled job, including empty
    ones (a malformed config stays visible in the report); disabled jobs
    are omitted.
    """

    covered: frozenset[int]
    uncovered: frozenset[int]
    exempt: frozenset[int]
    by_guest: dict[int, tuple[str, ...]]
    by_job: dict[str, frozenset[int]]


def compute_coverage(jobs: Sequence[BackupJob],
                     guests: Sequence[Guest]) -> Coverage:
    """Match jobs against guests (stateless; see module doc)."""
    unique: dict[int, Guest] = {}
    for guest in guests:
        unique.setdefault(guest.vmid, guest)  # duplicate vmid: first wins

    by_guest: dict[int, set[str]] = {}
    by_job: dict[str, frozenset[int]] = {}
    for job in jobs:
        if not job.enabled:
            continue
        picked: set[int] = set()
        for vmid, guest in unique.items():
            if job.selects(guest):
                picked.add(vmid)
                by_guest.setdefault(vmid, set()).add(job.job_id)
        by_job[job.job_id] = frozenset(picked)

    templates = {v for v, g in unique.items() if g.template}
    plain = set(unique) - templates
    covered = set(by_guest)
    return Coverage(
        covered=frozenset(covered),
        uncovered=frozenset(plain - covered),
        exempt=frozenset(templates),
        by_guest={vmid: tuple(sorted(ids))
                  for vmid, ids in by_guest.items()},
        by_job=by_job,
    )
