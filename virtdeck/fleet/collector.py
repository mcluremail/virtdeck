"""M4.2: collect the Fleet Health report for one cluster via the provider.

Fan-out over read-only sources; each source is isolated: one failure
does not break the others — a partial collection lands in errors and
the report stays useful. Node versions and storage usage are collected
per-node (one node's failure does not sink the cluster).
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
    """Node pveversion: from the node status, fallback /nodes/{node}/version.

    The main FetchWorker takes pveversion from /status (fetch.py); on some
    PVE versions /version does not return pveversion — repeat its path.
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
    """Collect a ClusterFleetReport for one provider (cluster).

    ``pbs_last_backups`` is a ready ``{(backup-type, backup-id): ts}``
    mapping (from the PBS client via ``last_pbs_backup_times``); iterating
    over PBS configs is the caller's job.
    """
    generated_at = int(time.time()) if now is None else now
    errors: list[CollectError] = []

    def guarded(source: str, fn):
        try:
            return fn(), None
        except Exception as exc:  # partial source failure — not fatal
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
            # an empty string is recorded too: a node with an unknown
            # version must stay visible in drift ("Version unknown"),
            # not disappear
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
    """Collect reports for all clusters (sequentially; M4.5 parallelizes)."""
    return [
        collect_cluster(provider, name=name, pbs_last_backups=pbs_last_backups,
                        now=now)
        for name, provider in providers.items()
    ]
