"""Fleet Health sprawl-скан: sync-вызовы вне UI-потока (шов ui/api).

Модуль без Qt-виджетов (контракт sync-contract): функция запускается из
фонового потока диалога и возвращает готовые результаты скана.
"""

from __future__ import annotations

from ...fleet.sprawl import DEFAULT_STALE_DAYS, fetch_snapshots, scan_sprawl
from ...plugins import create_provider


def scan_fleet_snapshots(targets, bundles: list,
                         stale_days: int = DEFAULT_STALE_DAYS,
                         on_progress=None) -> dict:
    """Собрать снапшоты всех гостей всех таргетов (1 запрос/ВМ).

    ``targets`` — FleetTarget-подобные объекты (``.name``/``.cfg``),
    ``bundles`` — собранные ClusterBundle. Возвращает
    cluster → SprawlScan | None (ошибка кластера глушится: скан не должен
    рушить отчёт). Использует гостей из собранных отчётов.
    ``on_progress(done, total)`` — агрегированный прогресс по всем
    кластерам (общий счётчик гостей).
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
                snapshots = fetch_snapshots(provider, bundle.report.guests,
                                            on_progress=_cb)
                scans[name] = scan_sprawl(
                    snapshots, bundle.report.guests,
                    now=bundle.report.generated_at,
                    stale_days=stale_days)
        except Exception:
            scans[name] = None
        base += len(bundle.report.guests)
    return scans
