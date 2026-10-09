"""Fleet Health: PBS sources → last-backup mapping for the report.

Iterates PBS configs (host configs with ``type == "pbs"``), walks every
datastore (root namespace + nested namespaces, bounded depth) and builds
the ready ``{(backup-type, backup-id): ts}`` mapping that
``collect_cluster`` accepts as ``pbs_last_backups`` (the mapping format
matches ``domain.fleet.last_pbs_backup_times``).

Isolation per source: one unreachable PBS server (or one broken
datastore) never breaks the fleet report — the failure is logged, the
mapping stays partial. Snapshots with a failed verification do not
count: a broken copy is not a successful backup.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence

from ..pbs.provider import PbsProvider

logger = logging.getLogger(__name__)

# namespaces rarely nest deeper; the walk is bounded so a pathological
# server (or a path-semantics surprise) cannot turn into an endless crawl
_MAX_NS_DEPTH = 3


def _add_snapshot(snap, out: dict[tuple[str, str], int]) -> None:
    if snap.verify == "failed":
        return  # a broken copy is not a successful backup
    if not snap.backup_id or snap.backup_time is None:
        return
    t = int(snap.backup_time.timestamp())
    key = (snap.backup_type, snap.backup_id)
    if t > out.get(key, 0):
        out[key] = t


def _collect_store(prov: PbsProvider, store: str,
                   out: dict[tuple[str, str], int]) -> None:
    """Snapshots of one datastore: root namespace, then nested ones.

    Namespace entries are treated as names relative to the parent
    (accumulated into a path for nested levels).
    """
    for snap in prov.snapshots(store):
        _add_snapshot(snap, out)
    try:
        roots = prov.namespaces(store)
    except Exception as e:
        logger.debug("Fleet Health: PBS %s namespaces: %s", store, e)
        return
    for ns in roots:
        _walk(prov, store, ns, "", out, 0)


def _walk(prov: PbsProvider, store: str, name: str, parent: str,
          out: dict[tuple[str, str], int], depth: int) -> None:
    path = f"{parent}/{name}" if parent else name
    try:
        for snap in prov.snapshots(store, ns=path):
            _add_snapshot(snap, out)
        if depth + 1 < _MAX_NS_DEPTH:
            for sub in prov.namespaces(store, parent=path):
                _walk(prov, store, sub, path, out, depth + 1)
    except Exception as e:
        logger.debug("Fleet Health: PBS %s ns '%s': %s", store, path, e)


def collect_pbs_last_backups(cfgs: Sequence[Mapping], timeout: float = 15) \
        -> dict[tuple[str, str], int]:
    """All PBS configs → ``{(backup-type, backup-id): last ts}``.

    Each server is isolated: an unreachable server (or a broken
    datastore) is logged and skipped — the mapping stays partial and the
    fleet report stays useful.
    """
    out: dict[tuple[str, str], int] = {}
    for cfg in cfgs:
        name = str(cfg.get("name") or "?")
        prov = None
        try:
            prov = PbsProvider(dict(cfg), timeout=timeout)
            for ds in prov.datastores():
                try:
                    _collect_store(prov, ds.name, out)
                except Exception as e:
                    logger.info("Fleet Health: PBS %s datastore '%s': %s",
                                name, ds.name, e)
        except Exception as e:
            logger.info("Fleet Health: PBS %s unavailable: %s", name, e)
        finally:
            if prov is not None:
                try:
                    prov.close()
                except Exception:
                    pass
    return out
