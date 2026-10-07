"""Fleet Health sprawl-скан: sync-вызовы вне UI-потока (шов ui/api).

Модуль без Qt-виджетов (контракт sync-contract): функция запускается из
фонового потока диалога и возвращает готовые результаты скана.
"""

from __future__ import annotations

from ...fleet.sprawl import DEFAULT_STALE_DAYS, fetch_snapshots, scan_sprawl
from ...plugins import create_provider


def scan_fleet_snapshots(targets, bundles: list,
                         stale_days: int = DEFAULT_STALE_DAYS) -> dict:
    """Собрать снапшоты всех гостей всех таргетов (1 запрос/ВМ).

    ``targets`` — FleetTarget-подобные объекты (``.name``/``.cfg``),
    ``bundles`` — собранные ClusterBundle. Возвращает
    cluster → SprawlScan | None (ошибка кластера глушится: скан не должен
    рушить отчёт). Использует гостей из собранных отчётов.
    """
    cfg_by_name = {t.name: t.cfg for t in targets}
    scans: dict = {}
    for bundle in bundles:
        name = bundle.report.cluster
        cfg = cfg_by_name.get(name)
        if cfg is None:
            continue
        try:
            with create_provider(cfg) as provider:
                snapshots = fetch_snapshots(provider, bundle.report.guests)
                scans[name] = scan_sprawl(
                    snapshots, bundle.report.guests,
                    now=bundle.report.generated_at,
                    stale_days=stale_days)
        except Exception:
            scans[name] = None
    return scans
