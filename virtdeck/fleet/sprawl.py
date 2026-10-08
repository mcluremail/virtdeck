"""M4.4: snapshot sprawl — forgotten old snapshots across the whole fleet.

On-demand scan (not background): one request per VM/CT
``GET /nodes/{node}/qemu|lxc/{vmid}/snapshot``; ``fetch_snapshots``
pushes them through a pool with a concurrency limit. ``scan_sprawl``
is pure aggregation: snapshots older than ``stale_days`` count as
forgotten; snapshots without a time (zombies) count as forgotten too;
the service ``current`` snapshot is excluded. Caching the last scan is
the UI's concern (M4.5).
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
    """Total user snapshots (no current; zombies count)."""
    oldest_time: int | None
    stale_names: tuple[str, ...] = field(default_factory=tuple)
    """Names of forgotten ones (older than the threshold or without a
    time), oldest first."""
    zombie_names: tuple[str, ...] = field(default_factory=tuple)
    """Snapshots without a time — age unknown."""

    @property
    def has_stale(self) -> bool:
        return bool(self.stale_names)


@dataclass(frozen=True)
class SprawlScan:
    generated_at: int
    stale_days: int
    guests: tuple[GuestSprawl, ...]
    """Only guests with snapshots, sorted: stale first, within — by the
    age of the oldest."""


def _guest_key(guest: Guest) -> tuple[str, int, str, str]:
    return (guest.node, guest.vmid, guest.name, guest.vm_type)


def scan_sprawl(snapshots_by_vmid: Mapping[int, Sequence[dict]],
                guests: Sequence[Guest], *, now: int,
                stale_days: int = DEFAULT_STALE_DAYS) -> SprawlScan:
    """Scan aggregation: guest snapshots, marking forgotten ones (see module doc)."""
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
                stale.append((0, name))  # forgotten — on top
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
    """Collect snapshots of all fleet guests (1 request per VM).

    Concurrency is limited via a thread pool; per-VM errors are muted
    (the guest simply has no snapshots — it is left out of the report).
    Returns vmid → list of snapshots (raw).
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
