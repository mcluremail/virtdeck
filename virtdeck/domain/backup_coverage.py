"""Domain: backup coverage matching engine (Fleet Health, M4.1).

Чистое клиентское сопоставление «backup-джобы × гости» по данным
`GET /cluster/backup` и `GET /cluster/resources` — без Qt, без API,
без состояния. Именно этот движок определяет доверие ко всему отчёту
Fleet Health, поэтому семантика выбора гостей vzdump-джобом
зафиксирована явно (по поведению PVE::VZDump):

1. Шаблоны не бэкапятся никогда — они вне отчёта (exempt), даже если
   перечислены в vmid[] джоба. Иначе — false positive с первого запуска.
2. ``all=1`` → все не-шаблоны минус ``exclude``. ``exclude`` без ``all``
   игнорируется (vzdump его не применяет).
3. ``pool`` → все члены пула на любых нодах, включая остановленных
   гостей (статус в сопоставлении не участвует).
4. ``vmid`` → явный список.
5. Приоритет полей у PVE: ``all`` > ``pool`` > ``vmid`` — при комбинации
   действует первый.
6. ``enabled=0`` джоб никого не покрывает.
7. Пересечения джобов допустимы: гость может покрываться несколькими.
8. Гость мигрирует между пулами между запусками → движок stateless,
   отчёт каждый раз считается заново по свежему resources.

API-аномалии обрабатываются детерминированно: дубль vmid в guests —
побеждает первая встреченная строка; мусор в списке vmid/exclude
пропускается; джоб без all/pool/vmid никого не выбирает, но остаётся
видимым в ``by_job`` (пустое множество)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


def _truthy(value: object) -> bool:
    """PVE отдаёт 0/1; принимаем также bool и строковые '0'/'1'."""
    if isinstance(value, str):
        return value.strip() not in ("", "0")
    return bool(value)


def _parse_vmid_list(value: object) -> tuple[int, ...]:
    """'101, 102' → (101, 102); None/'' → (); мусор пропускается."""
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
    """Backup-джоб из GET /cluster/backup (нормализованный)."""

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
        """Покрывает ли джоб гостя (семантика vzdump, см. докмодуль)."""
        if not self.enabled or guest.template:
            return False
        if self.all_vms:
            return guest.vmid not in self.exclude
        if self.pool:
            return guest.pool == self.pool
        return guest.vmid in self.vmids


@dataclass(frozen=True)
class Guest:
    """Гость из GET /cluster/resources (нормализованный)."""

    vmid: int
    name: str = ""
    node: str = ""
    vm_type: str = "qemu"  # qemu | lxc
    pool: str = ""
    template: bool = False

    @classmethod
    def from_raw(cls, raw: dict) -> Guest | None:
        """Из строки /cluster/resources; None для не-гостей и без vmid."""
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
    """Результат сопоставления для одного кластера.

    ``covered`` / ``uncovered`` / ``exempt`` не пересекаются и покрывают
    все гости сцены. ``by_job`` содержит все enabled-джобы, включая
    пустые (malformed конфиг виден в отчёте); disabled-джобы опущены.
    """

    covered: frozenset[int]
    uncovered: frozenset[int]
    exempt: frozenset[int]
    by_guest: dict[int, tuple[str, ...]]
    by_job: dict[str, frozenset[int]]


def compute_coverage(jobs: Sequence[BackupJob],
                     guests: Sequence[Guest]) -> Coverage:
    """Сопоставить джобы и гостей (stateless; см. докмодуль)."""
    unique: dict[int, Guest] = {}
    for guest in guests:
        unique.setdefault(guest.vmid, guest)  # дубль vmid: первый выигрывает

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
