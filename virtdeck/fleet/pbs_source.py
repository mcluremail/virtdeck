"""Fleet Health: PBS sources → last-backup evidence with dimensions.

Iterates PBS configs (host configs with ``type == "pbs"``), walks every
datastore (root namespace + nested namespaces, bounded depth) and builds
dimensional evidence ``{(server, port, datastore, ns): {(backup-type,
backup-id): ts}}`` (audit D5 fix): the source of every snapshot is kept,
so ``fleet.pbs_scope`` can give each cluster only the evidence of the
PBS storages the cluster itself references.

Isolation per source: one unreachable PBS server (or one broken
datastore) never breaks the collection — the failure is recorded in the
evidence (``failed_servers`` / ``failed_stores``), the rest stays
usable. Snapshots with a failed verification do not count: a broken
copy is not a successful backup.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from ..pbs.client import PBS_PORT
from ..pbs.provider import PbsProvider

logger = logging.getLogger(__name__)

# namespaces rarely nest deeper; the walk is bounded so a pathological
# server (or a path-semantics surprise) cannot turn into an endless crawl
_MAX_NS_DEPTH = 3

ServerKey = tuple[str, int]
"""Normalized PBS server identity: (host, port)."""
StoreKey = tuple[str, int, str]
"""(server, port, datastore) — the unit of confirmed collection."""
SourceKey = tuple[str, int, str, str]
"""(server, port, datastore, namespace); namespace "" = root."""


def server_key(host, port=None) -> ServerKey:
    """Normalized ``(host, port)`` identity of a PBS server.

    Host: stripped and lower-cased. Port: explicit value wins, an empty
    one defaults to 8007. FQDN, short name and IP of the same machine
    are deliberately NOT equated (no DNS, no heuristics) — only literal
    equality after normalization. A non-numeric non-empty port raises
    ``ValueError`` (a broken value must not silently become the
    default).
    """
    h = str(host or "").strip().lower()
    raw = str(port if port is not None else "").strip()
    try:
        p = int(raw) if raw else PBS_PORT
    except ValueError:
        raise ValueError(f"invalid port: {port!r}") from None
    return (h, p)


def _add_snapshot(snap, ns: str,
                  out: dict[str, dict[tuple[str, str], int]]) -> None:
    if snap.verify == "failed":
        return  # a broken copy is not a successful backup
    if not snap.backup_id or snap.backup_time is None:
        return
    t = int(snap.backup_time.timestamp())
    key = (snap.backup_type, snap.backup_id)
    bucket = out.setdefault(ns, {})
    if t > bucket.get(key, 0):
        bucket[key] = t


def _collect_store(prov: PbsProvider, store: str) \
        -> dict[str, dict[tuple[str, str], int]]:
    """Snapshots of one datastore per namespace: root, then nested.

    Namespace entries are treated as names relative to the parent
    (accumulated into a path for nested levels). Root-namespace failure
    propagates (the whole store is uncollected); a nested-namespace
    failure is logged and skipped (partial, but the store stays
    collected).
    """
    out: dict[str, dict[tuple[str, str], int]] = {}
    for snap in prov.snapshots(store):
        _add_snapshot(snap, "", out)
    try:
        roots = prov.namespaces(store)
    except Exception as e:
        logger.debug("Fleet Health: PBS %s namespaces: %s", store, e)
        return out
    for ns in roots:
        _walk(prov, store, ns, "", out, 0)
    return out


def _walk(prov: PbsProvider, store: str, name: str, parent: str,
          out: dict[str, dict[tuple[str, str], int]], depth: int) -> None:
    path = f"{parent}/{name}" if parent else name
    try:
        for snap in prov.snapshots(store, ns=path):
            _add_snapshot(snap, path, out)
        if depth + 1 < _MAX_NS_DEPTH:
            for sub in prov.namespaces(store, parent=path):
                _walk(prov, store, sub, path, out, depth + 1)
    except Exception as e:
        logger.debug("Fleet Health: PBS %s ns '%s': %s", store, path, e)


@dataclass
class PbsEvidence:
    """Dimensional last-successful-snapshot evidence (audit D5 fix).

    ``by_source`` holds only sources with at least one snapshot; for a
    store in ``collected_stores`` an absent namespace key means a
    confirmed empty namespace (not missing data). Missing data is
    distinguishable: ``failed_servers`` / ``failed_stores``.
    """

    by_source: dict[SourceKey, dict[tuple[str, str], int]] = field(
        default_factory=dict)
    collected_stores: set[StoreKey] = field(default_factory=set)
    failed_stores: set[StoreKey] = field(default_factory=set)
    failed_servers: set[ServerKey] = field(default_factory=set)


def collect_pbs_last_backups(cfgs: Sequence[Mapping], timeout: float = 15) \
        -> PbsEvidence:
    """All PBS configs → dimensional evidence.

    Each server is isolated: an unreachable server (or a broken
    datastore) is logged and recorded in the evidence — the rest of the
    fleet stays usable.
    """
    ev = PbsEvidence()
    for cfg in cfgs:
        name = str(cfg.get("name") or "?")
        try:
            skey = server_key(cfg.get("host"), cfg.get("port"))
        except ValueError as e:
            logger.info("Fleet Health: PBS %s: %s", name, e)
            continue
        prov = None
        try:
            prov = PbsProvider(dict(cfg), timeout=timeout)
            for ds in prov.datastores():
                try:
                    per_ns = _collect_store(prov, ds.name)
                except Exception as e:
                    logger.info("Fleet Health: PBS %s datastore '%s': %s",
                                name, ds.name, e)
                    ev.failed_stores.add((*skey, ds.name))
                    continue
                ev.collected_stores.add((*skey, ds.name))
                for ns, sub in per_ns.items():
                    if sub:
                        ev.by_source[(*skey, ds.name, ns)] = sub
        except Exception as e:
            logger.info("Fleet Health: PBS %s unavailable: %s", name, e)
            ev.failed_servers.add(skey)
        finally:
            if prov is not None:
                try:
                    prov.close()
                except Exception:
                    pass
    return ev
