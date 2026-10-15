"""M4.2: collect the Fleet Health report for one cluster via the provider.

Fan-out over read-only sources; each source is isolated: one failure
does not break the others — a partial collection lands in errors and
the report stays useful. Node versions and storage usage are collected
per-node (one node's failure does not sink the cluster).

Since the audit D5 fix the collector also fetches the cluster's storage
configuration (``GET /storage``): its pbs-type rows are the bindings
that scope the fleet-wide PBS evidence per cluster (``fleet.pbs_scope``)
— collected in the same update cycle, one extra request per cluster.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..domain.fleet import (
    ClusterFleetReport,
    CollectError,
    build_cluster_report,
)
from .pbs_scope import PbsBinding, bindings_from_storage_configs

# /cluster/tasks fetch limit: PVE keeps thousands of rows; pulling them
# all is wasteful, but the cap must be surfaced (tasks_truncated) —
# a guest whose last successful backup fell out of the window must not
# be reported as "never backed up" without a caveat.
TASK_HISTORY_LIMIT = 200


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


@dataclass(frozen=True)
class ClusterCollection:
    """Result of ``collect_cluster``: the report + PBS storage bindings.

    ``pbs_bindings is None`` — the storage configuration could not be
    collected (the scope is undetermined); an empty tuple means the
    cluster simply has no pbs-type storages (a determined, empty scope).
    """

    report: ClusterFleetReport
    pbs_bindings: tuple[PbsBinding, ...] | None = None
    pbs_binding_problems: tuple[str, ...] = ()


def collect_pbs_bindings(provider, *, name: str) \
        -> tuple[tuple[PbsBinding, ...] | None, tuple[str, ...],
                 CollectError | None]:
    """``GET /storage`` → pbs-type storage bindings (isolated source).

    Never raises. Full /storage rows may contain secrets (password) —
    nothing is logged here; problem messages carry only storage ids.
    """
    try:
        configs = provider.cluster.list_storage_configs() or []
    except Exception as exc:
        return None, (), CollectError(cluster=name,
                                      source="pbs_storage_config",
                                      message=str(exc))
    bindings, problems = bindings_from_storage_configs(configs)
    return tuple(bindings), tuple(problems), None


def collect_cluster(
    provider,
    *,
    name: str,
    pbs_last_backups: Mapping[tuple[str, str], int] | None = None,
    now: int | None = None,
    pbs_bindings_needed: bool = True,
) -> ClusterCollection:
    """Collect a ClusterFleetReport for one provider (cluster).

    ``pbs_last_backups`` is a ready, pre-scoped ``{(backup-type,
    backup-id): ts}`` mapping (from the PBS client via
    ``last_pbs_backup_times``); iterating over PBS configs and scoping
    the fleet-wide evidence is the caller's job (``fleet.pbs_scope``).
    ``pbs_bindings_needed=False`` skips the ``GET /storage`` request —
    the fleet worker passes False when no PBS servers are configured at
    all (no wasted request; the scope stays "ok").
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
                         lambda: provider.tasks.list_cluster(
                             limit=TASK_HISTORY_LIMIT))
    if err:
        errors.append(err)
    tasks_truncated = tasks is not None \
        and len(tasks) >= TASK_HISTORY_LIMIT

    if pbs_bindings_needed:
        pbs_bindings, binding_problems, err = collect_pbs_bindings(
            provider, name=name)
        if err:
            errors.append(err)
    else:
        pbs_bindings, binding_problems = None, ()

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

    report = build_cluster_report(
        cluster=name,
        generated_at=generated_at,
        resources=resources,
        backup_jobs=jobs,
        tasks=tasks,
        node_versions=node_versions,
        storage_usage=storage_rows,
        pbs_last_backups=pbs_last_backups,
        tasks_truncated=tasks_truncated,
        errors=errors,
    )
    return ClusterCollection(report=report, pbs_bindings=pbs_bindings,
                             pbs_binding_problems=binding_problems)


def collect_fleet(providers: Mapping[str, object],
                  pbs_last_backups: Mapping[tuple[str, str], int]
                  | None = None,
                  now: int | None = None) -> Sequence[ClusterFleetReport]:
    """Collect reports for all clusters (sequentially; M4.5 parallelizes)."""
    return [
        collect_cluster(provider, name=name, pbs_last_backups=pbs_last_backups,
                        now=now).report
        for name, provider in providers.items()
    ]
