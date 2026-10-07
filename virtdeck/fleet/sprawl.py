"""M4.4: snapshot sprawl — забытые старые снапшоты по всему парку.

Скан по кнопке (не фоновый): по каждой ВМ/CT один запрос
``GET /nodes/{node}/qemu|lxc/{vmid}/snapshot``; ``fetch_snapshots``
гонит их через пул с лимитом параллелизма. ``scan_sprawl`` — чистая
агрегация: снапшоты старше ``stale_days`` считаются забытыми; снапшоты
без времени (zombie) тоже забытые; служебный ``current`` исключается.
Кэш последнего скана — забота UI (M4.5).
"""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from ..domain.backup_coverage import Guest

SECONDS_PER_DAY = 86400
DEFAULT_STALE_DAYS = 30
DEFAULT_CONCURRENCY = 8


@dataclass(frozen=True)
class GuestSprawl:
    vmid: int
    node: str
    name: str
    vm_type: str
    count: int
    """Всего пользовательских снапшотов (без current; зомби считаются)."""
    oldest_time: int | None
    stale_names: tuple[str, ...] = field(default_factory=tuple)
    """Имена забытых (старше порога или без времени), старые первыми."""
    zombie_names: tuple[str, ...] = field(default_factory=tuple)
    """Снапшоты без времени — возраст неизвестен."""

    @property
    def has_stale(self) -> bool:
        return bool(self.stale_names)


@dataclass(frozen=True)
class SprawlScan:
    generated_at: int
    stale_days: int
    guests: tuple[GuestSprawl, ...]
    """Только гости со снапшотами, отсортированы: stale первыми,
    внутри — по возрасту старейшего."""


def _guest_key(guest: Guest) -> tuple[str, int, str, str]:
    return (guest.node, guest.vmid, guest.name, guest.vm_type)


def scan_sprawl(snapshots_by_vmid: Mapping[int, Sequence[dict]],
                guests: Sequence[Guest], *, now: int,
                stale_days: int = DEFAULT_STALE_DAYS) -> SprawlScan:
    """Агрегация скана: снапшоты гостей, пометка забытых (см. докмодуль)."""
    by_vmid = {g.vmid: g for g in guests}
    stale_cutoff = now - stale_days * SECONDS_PER_DAY
    rows: list[GuestSprawl] = []
    for vmid, snaps in snapshots_by_vmid.items():
        names: list[str] = []
        oldest: int | None = None
        stale: list[tuple[int, str]] = []
        zombie: list[str] = []
        for snap in snaps:
            name = str(snap.get("name") or "")
            if not name or name == "current":
                continue
            raw_time = snap.get("snaptime")
            try:
                snaptime = int(raw_time)
            except (TypeError, ValueError):
                zombie.append(name)
                stale.append((0, name))  # забытое — наверху
                continue
            names.append(name)
            if oldest is None or snaptime < oldest:
                oldest = snaptime
            if snaptime < stale_cutoff:
                stale.append((snaptime, name))
        if not names and not zombie:
            continue
        guest = by_vmid.get(vmid)
        stale_names = tuple(n for _t, n in sorted(stale))
        rows.append(GuestSprawl(
            vmid=vmid,
            node=guest.node if guest else "",
            name=guest.name if guest else "",
            vm_type=guest.vm_type if guest else "",
            count=len(names) + len(zombie),
            oldest_time=oldest,
            stale_names=stale_names,
            zombie_names=tuple(zombie),
        ))
    rows.sort(key=lambda r: (not r.has_stale,
                             r.oldest_time if r.oldest_time is not None
                             else now + 1))
    return SprawlScan(generated_at=now, stale_days=stale_days,
                      guests=tuple(rows))


def fetch_snapshots(provider, guests: Sequence[Guest], *,
                    concurrency: int = DEFAULT_CONCURRENCY,
                    on_progress=None) -> dict[int, list[dict]]:
    """Собрать снапшоты всех гостей парка (1 запрос на ВМ).

    Лимит параллелизма через пул потоков; ошибки per-ВМ глушатся
    (гость просто без снапшотов — в отчёте не участвует). Возвращает
    vmid → список снапшотов (raw).
    """
    targets = [g for g in guests if not g.template]
    if not targets:
        return {}
    result: dict[int, list[dict]] = {}
    lock = threading.Lock()
    done = [0]

    def fetch(guest: Guest) -> None:
        try:
            snaps = provider.vms.list_snapshots(guest.node, guest.vmid,
                                                guest.vm_type)
        except Exception:
            snaps = None
        with lock:
            if snaps:
                result[guest.vmid] = list(snaps)
            done[0] += 1

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [pool.submit(fetch, g) for g in targets]
        for future in as_completed(futures):
            future.result()
            if on_progress is not None:
                with lock:
                    on_progress(done[0], len(targets))
    return result
