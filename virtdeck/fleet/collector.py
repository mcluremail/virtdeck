"""M4.2: сбор отчёта Fleet Health по одному кластеру через провайдер.

Фан-аут по read-only источникам; каждый источник изолирован: ошибка
одного не рушит остальные — частичный сбор попадает в errors, отчёт
остаётся полезным. Версии нод и storage usage собираются per-node
(ошибка одной ноды не валит кластер).
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence

from ..domain.fleet import (
    ClusterFleetReport,
    CollectError,
    build_cluster_report,
)


def _node_version(provider, node: str) -> str:
    """pveversion ноды: из статуса ноды, фолбэк — /nodes/{node}/version.

    Основной FetchWorker берёт pveversion из /status (fetch.py); на части
    версий PVE /version не отдаёт pveversion — повторяем его путь.
    """
    try:
        st = provider.nodes.get_status(node) or {}
        pve = str(st.get("pveversion") or "")
        if pve:
            return pve
    except Exception:
        pass
    ver = provider.nodes.get_version(node) or {}
    return str(ver.get("pveversion") or ver.get("version") or "")


def collect_cluster(
    provider,
    *,
    name: str,
    pbs_last_backups: Mapping[tuple[str, str], int] | None = None,
    now: int | None = None,
) -> ClusterFleetReport:
    """Собрать ClusterFleetReport по одному провайдеру (кластеру).

    ``pbs_last_backups`` — готовый маппинг ``{(backup-type, backup-id): ts}``
    (из PBS-клиента через ``last_pbs_backup_times``); сбор по PBS-конфигам
    выполняет вызывающая сторона.
    """
    generated_at = int(time.time()) if now is None else now
    errors: list[CollectError] = []

    def guarded(source: str, fn):
        try:
            return fn(), None
        except Exception as exc:  # частичный сбой источника — не фатален
            return None, CollectError(cluster=name, source=source,
                                      message=str(exc))

    resources, err = guarded("resources", provider.cluster.list_resources)
    if err:
        errors.append(err)
    jobs, err = guarded("backup_jobs", provider.cluster.list_backup_jobs)
    if err:
        errors.append(err)
    tasks, err = guarded("tasks",
                         lambda: provider.tasks.list_cluster(limit=200))
    if err:
        errors.append(err)

    node_versions: dict[str, str] = {}
    storage_rows: list[dict] = []
    nodes: list[str] = []
    if resources is not None:
        nodes = sorted({str(r["node"]) for r in resources
                        if r.get("type") == "node" and r.get("node")})
    for node in nodes:
        ver, err = guarded(f"version:{node}",
                           lambda n=node: _node_version(provider, n))
        if err:
            errors.append(err)
        else:
            # пустая строка тоже фиксируется: узел с неизвестной версией
            # должен быть виден в drift («Version unknown»), не пропадать
            node_versions[node] = str(ver or "")
        rows, err = guarded(
            f"storage:{node}",
            lambda n=node: provider.storage.list_node_storage(n))
        if err:
            errors.append(err)
        elif rows is not None:
            storage_rows.extend({"node": node, **row} for row in rows)

    return build_cluster_report(
        cluster=name,
        generated_at=generated_at,
        resources=resources,
        backup_jobs=jobs,
        tasks=tasks,
        node_versions=node_versions,
        storage_usage=storage_rows,
        pbs_last_backups=pbs_last_backups,
        errors=errors,
    )


def collect_fleet(providers: Mapping[str, object],
                  pbs_last_backups: Mapping[tuple[str, str], int]
                  | None = None,
                  now: int | None = None) -> Sequence[ClusterFleetReport]:
    """Собрать отчёты по всем кластерам (последовательно; M4.5 распараллелит)."""
    return [
        collect_cluster(provider, name=name, pbs_last_backups=pbs_last_backups,
                        now=now)
        for name, provider in providers.items()
    ]
