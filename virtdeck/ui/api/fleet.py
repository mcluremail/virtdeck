"""Fleet Health sprawl scan: sync calls off the UI thread (ui/api seam).

Module without Qt widgets (sync-contract): the function runs from the
dialog's background thread and returns ready scan results.
"""

from __future__ import annotations

import time

from ...domain.backup_coverage import Guest
from ...fleet.sprawl import DEFAULT_STALE_DAYS, fetch_snapshots, scan_sprawl
from ...plugins import create_provider


def scan_fleet_snapshots(targets, bundles: list,
                         stale_days: int = DEFAULT_STALE_DAYS,
                         on_progress=None) -> dict:
    """Collect snapshots of every guest of every target (1 request/VM).

    ``targets`` — FleetTarget-like objects (``.name``/``.cfg``),
    ``bundles`` — collected ClusterBundle. Returns
    cluster → SprawlScan | None (a cluster error is muted: the scan must
    not break the report). Uses guests from the collected reports.
    ``on_progress(done, total)`` — aggregated progress across all
    clusters (a shared guest counter).

    Honesty (P1): ages are computed against the scan's own wall clock
    (not the report's ``generated_at``), and the guest list is re-fetched
    per cluster when possible — guests created after the report must not
    silently miss the scan. Per-VM fetch failures land in
    ``SprawlScan.failed`` instead of masquerading as "no snapshots".
    """
    cfg_by_name = {t.name: t.cfg for t in targets}
    scan_list = [(b, cfg_by_name[b.report.cluster]) for b in bundles
                 if b.report.cluster in cfg_by_name]
    grand_total = sum(len(b.report.guests) for b, _c in scan_list)
    scans: dict = {}
    base = 0
    for bundle, cfg in scan_list:
        name = bundle.report.cluster

        def _cb(done, _total, base=base):
            if on_progress is not None:
                on_progress(base + done, grand_total)

        try:
            with create_provider(cfg) as provider:
                guests = _scene_guests(provider, bundle)
                fetched = fetch_snapshots(provider, guests,
                                          on_progress=_cb)
                scans[name] = scan_sprawl(
                    fetched.snapshots, guests,
                    now=int(time.time()),
                    stale_days=stale_days, failed=fetched.failed)
        except Exception:
            scans[name] = None
        base += len(bundle.report.guests)
    return scans


def _scene_guests(provider, bundle) -> list[Guest]:
    """Fresh guest list for the scan; the collected report's guests are
    the fallback (resources are an extra request per cluster)."""
    try:
        raw = provider.cluster.list_resources()
        guests = [g for g in (Guest.from_raw(r) for r in raw or [])
                  if g is not None]
        if guests:
            return guests
    except Exception:
        pass
    return list(bundle.report.guests)
