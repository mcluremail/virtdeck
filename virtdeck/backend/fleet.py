"""Fleet Health workers (M4.5): parallel report collection across clusters.

Same pattern as ClusterTasksWorker: QObject with signals +
threading.Thread (not QRunnable). Clusters are collected in parallel —
each in its own thread; within a cluster, sources are isolated
(partial failure lands in the report). rrddata for runway is fetched
by the same cluster thread.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait as _futures_wait
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from ..domain.fleet import ClusterFleetReport
from ..fleet.collector import collect_cluster
from ..fleet.pbs_source import collect_pbs_last_backups
from ..fleet.runway import RunwayEstimate, estimate_runway
from ..plugins import create_provider

logger = logging.getLogger(__name__)

RUNWAY_TIMEFRAME = "month"  # rrddata: monthly window, hourly points

# thread cap for cluster collection: a fleet of standalone hosts must
# not spawn one thread each (each thread holds a provider + session)
MAX_COLLECT_THREADS = 8
# generous ceiling on waiting for the whole fleet: request timeouts
# (15 s) bound each thread, this only guards a pathological hang —
# on timeout the dialog gets the partial report instead of freezing
JOIN_TIMEOUT_S = 600


@dataclass(frozen=True)
class FleetTarget:
    """Fleet Health target: one endpoint = one cluster/host.

    ``name`` — the endpoint config name (matches the VM's tree host_name —
    navigation keys depend on it); ``display`` — the label in the report
    (cluster name for PVE clusters, host name for standalone).
    """

    name: str
    display: str
    cfg: dict


def build_fleet_targets(nodes_cfg: list[dict]) -> list[FleetTarget]:
    """Group host configs into Fleet Health targets.

    Same semantics as the tree (tree_panel): members of one PVE cluster
    (cfg["cluster"], not False/None/"Standalone") form one target; the
    endpoint is the cluster representative (cluster_rep, i.e. the
    creator; it is the one that pulls cluster-wide data in the
    FetchWorker) or the first member; the label is the cluster name.
    Standalone hosts get one target each, named after themselves.
    PBS servers and skip configs are excluded.
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
    """Cluster report + runway forecasts for its storages."""

    report: ClusterFleetReport
    runway: tuple[RunwayEstimate, ...]
    display: str = ""
    """Label in the UI (cluster name); empty — fall back to report.cluster."""


class FleetHealthSignals(QObject):
    cluster_done = Signal(object)   # ClusterBundle
    finished_all = Signal(list)     # list[ClusterBundle]


class FleetHealthWorker:  # not QRunnable — runs via threading.Thread
    """Collects Fleet Health across all targets in parallel.

    ``pbs_cfgs`` — optional PBS host configs: last-backup freshness is
    fetched once (per-server isolation, see ``fleet.pbs_source``) and
    shared by every cluster's report.
    """

    def __init__(self, targets: list[FleetTarget], pbs_cfgs=None):
        super().__init__()
        self._targets = list(targets)
        self._pbs_cfgs = list(pbs_cfgs or [])
        self._signals = FleetHealthSignals()
        self.cluster_done = self._signals.cluster_done
        self.finished_all = self._signals.finished_all

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        pbs_map: dict = {}
        if self._pbs_cfgs:
            try:
                pbs_map = collect_pbs_last_backups(self._pbs_cfgs)
            except Exception as e:  # PBS is an enrichment source only
                logger.warning("Fleet Health: PBS sources failed: %s", e)

        bundles: list[ClusterBundle] = []
        lock = threading.Lock()

        def job(target: FleetTarget) -> None:
            try:
                bundle = self._collect_one(target, pbs_map)
            except Exception as e:  # never leave the dialog without a signal
                logger.warning("Fleet Health: %s crashed: %s",
                               target.name, e)
                return
            with lock:
                bundles.append(bundle)
            self._signals.cluster_done.emit(bundle)

        workers = min(MAX_COLLECT_THREADS, max(1, len(self._targets)))
        executor = ThreadPoolExecutor(max_workers=workers,
                                      thread_name_prefix="fleet")
        try:
            futures = [executor.submit(job, t) for t in self._targets]
            _futures_wait(futures, timeout=JOIN_TIMEOUT_S)
        except Exception as e:
            logger.warning("Fleet Health: collection aborted: %s", e)
        finally:
            # the dialog resets on this signal no matter what happened —
            # buttons must never stay disabled forever
            executor.shutdown(wait=False, cancel_futures=True)
            self._signals.finished_all.emit(bundles)

    def _collect_one(self, target: FleetTarget,
                     pbs_map: dict | None = None) -> ClusterBundle:
        name = target.name
        try:
            with create_provider(target.cfg) as provider:
                report = collect_cluster(provider, name=name,
                                         pbs_last_backups=pbs_map or None)
                runway = self._runway(provider, report)
        except Exception as e:  # provider creation is a source too
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
        now = int(time.time())
        for row in _dedup_storage_rows(report.storage_usage):
            node, storage = str(row.get("node")), str(row.get("storage"))
            try:
                series = provider.rrd.get_storage_rrddata(
                    node, storage, timeframe=RUNWAY_TIMEFRAME)
            except Exception as e:
                logger.debug("Fleet Health runway %s/%s: %s",
                             node, storage, e)
                continue
            # the forecast itself is a source too: one degenerate series
            # must not sink the already-collected cluster report
            try:
                estimates.append(estimate_runway(series, node=node,
                                                 storage=storage, now=now))
            except Exception as e:
                logger.debug("Fleet Health runway %s/%s: %s",
                             node, storage, e)
        return tuple(estimates)


def _dedup_storage_rows(rows: list[dict]) -> list[dict]:
    """Active storage rows with shared storages forecast once.

    Shared storages (NFS/Ceph/PBS) arrive as one row per node: without
    dedup a 10-node cluster gets 10 identical forecasts and 10 rrddata
    requests for the same filesystem. The first active row of a shared
    storage wins; non-shared (local) rows stay per-node.
    """
    seen_shared: set[str] = set()
    out: list[dict] = []
    for row in rows:
        if not row.get("active"):
            continue  # inactive storage is not forecast
        if row.get("shared"):
            name = str(row.get("storage") or "")
            if name in seen_shared:
                continue
            seen_shared.add(name)
        out.append(row)
    return out
