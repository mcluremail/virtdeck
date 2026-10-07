"""Fleet Health workers (M4.5): параллельный сбор отчёта по кластерам.

Шаблон как у ClusterTasksWorker: QObject с сигналами + threading.Thread
(не QRunnable). Кластеры собираются параллельно — каждый в своём потоке;
внутри кластера источники изолированы (partial failure — в отчёте).
rrddata для runway добирается тем же потоком кластера.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from ..domain.fleet import ClusterFleetReport
from ..fleet.collector import collect_cluster
from ..fleet.runway import RunwayEstimate, estimate_runway
from ..plugins import create_provider

logger = logging.getLogger(__name__)

RUNWAY_TIMEFRAME = "month"  # rrddata: помесячное окно, часовые точки


@dataclass(frozen=True)
class FleetTarget:
    """Таргет Fleet Health: один эндпоинт = один кластер/хост.

    ``name`` — имя конфига-эндпоинта (совпадает с tree host_name у ВМ —
    от него зависят ключи перехода); ``display`` — подпись в отчёте
    (имя кластера для PVE-кластеров, имя хоста для одиночных).
    """

    name: str
    display: str
    cfg: dict


def build_fleet_targets(nodes_cfg: list[dict]) -> list[FleetTarget]:
    """Сгруппировать конфиги хостов в таргеты Fleet Health.

    Семантика как у дерева (tree_panel): члены одного PVE-кластера
    (cfg["cluster"], не False/None/"Standalone") — один таргет; эндпоинт —
    представитель кластера (cluster_rep, т.е. создатель; именно он тянет
    cluster-wide данные в FetchWorker) или первый член; подпись — имя
    кластера. Одиночные хосты — по одному таргету со своим именем.
    PBS-серверы и skip-конфиги исключаются.
    """
    clusters: dict[str, list[dict]] = {}
    standalone: list[dict] = []
    for cfg in nodes_cfg:
        if cfg.get("skip") or cfg.get("type") == "pbs":
            continue
        cl = cfg.get("cluster")
        if cl and cl not in (False, None, "Standalone"):
            clusters.setdefault(str(cl), []).append(cfg)
        elif cfg.get("name"):
            standalone.append(cfg)
    targets: list[FleetTarget] = []
    for cl_name, members in clusters.items():
        rep = next((m for m in members if m.get("cluster_rep")), members[0])
        targets.append(FleetTarget(name=str(rep.get("name") or ""),
                                   display=cl_name, cfg=rep))
    for cfg in standalone:
        targets.append(FleetTarget(name=str(cfg["name"]),
                                   display=str(cfg["name"]), cfg=cfg))
    targets.sort(key=lambda t: t.display.lower())
    return targets


@dataclass(frozen=True)
class ClusterBundle:
    """Отчёт кластера + runway-прогнозы его хранилищ."""

    report: ClusterFleetReport
    runway: tuple[RunwayEstimate, ...]
    display: str = ""
    """Подпись в UI (имя кластера); пусто — брать report.cluster."""


class FleetHealthSignals(QObject):
    cluster_done = Signal(object)   # ClusterBundle
    finished_all = Signal(list)     # list[ClusterBundle]


class FleetHealthWorker:  # not QRunnable — runs via threading.Thread
    """Собирает Fleet Health по всем таргетам параллельно."""

    def __init__(self, targets: list[FleetTarget]):
        super().__init__()
        self._targets = list(targets)
        self._signals = FleetHealthSignals()
        self.cluster_done = self._signals.cluster_done
        self.finished_all = self._signals.finished_all

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        bundles: list[ClusterBundle] = []
        lock = threading.Lock()
        threads: list[threading.Thread] = []

        def worker(target: FleetTarget) -> None:
            bundle = self._collect_one(target)
            with lock:
                bundles.append(bundle)
            self._signals.cluster_done.emit(bundle)

        for target in self._targets:
            t = threading.Thread(target=worker, args=(target,), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()
        self._signals.finished_all.emit(bundles)

    def _collect_one(self, target: FleetTarget) -> ClusterBundle:
        name = target.name
        try:
            with create_provider(target.cfg) as provider:
                report = collect_cluster(provider, name=name)
                runway = self._runway(provider, report)
        except Exception as e:  # создание провайдера — тоже источник
            logger.warning("Fleet Health: %s failed: %s", name, e)
            from ..domain.fleet import CollectError, build_cluster_report
            report = build_cluster_report(
                cluster=name, generated_at=0, resources=None,
                backup_jobs=None,
                errors=(CollectError(name, "cluster", str(e)),))
            runway = ()
        return ClusterBundle(report=report, runway=runway,
                             display=target.display)

    def _runway(self, provider, report: ClusterFleetReport) \
            -> tuple[RunwayEstimate, ...]:
        estimates: list[RunwayEstimate] = []
        for row in report.storage_usage:
            if not row.get("active"):
                continue  # неактивное хранилище не прогнозируем
            node, storage = str(row.get("node")), str(row.get("storage"))
            try:
                series = provider.rrd.get_storage_rrddata(
                    node, storage, timeframe=RUNWAY_TIMEFRAME)
            except Exception as e:
                logger.debug("Fleet Health runway %s/%s: %s",
                             node, storage, e)
                continue
            estimates.append(estimate_runway(series, node=node,
                                             storage=storage))
        return tuple(estimates)
