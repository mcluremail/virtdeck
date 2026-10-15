"""Fleet Health: PBS evidence scoping per cluster (audit D5 fix).

Pure selection logic over the dimensional PBS evidence
(``fleet.pbs_source``) and per-cluster storage-config bindings (pbs-type
rows of ``GET /storage``). No sockets, no Qt — unit-testable.

Rules (AUDIT_2026-10-15_PBS_SCOPE.md §5, prompt stage 2):

- only sources the cluster's own pbs-type storages reference apply;
- a cluster whose storage configuration is unavailable gets NO PBS
  evidence — never the fleet-wide map as a fallback (``unavailable``);
- a binding with missing required fields is not guessed (rejected with
  a problem message; the unverified part is reported);
- when one source ``(server, datastore, namespace)`` is referenced by
  several clusters AND a ``(backup-type, backup-id)`` identifier exists
  in more than one of them, the source's evidence for exactly those
  intersecting identifiers is dropped for every cluster sharing the
  source (a snapshot cannot be attributed) — ``ambiguous``;
- other identifiers of the same shared source keep their evidence (a
  shared PBS server alone is not an error);
- evidence from independently collected sources is kept even when
  another source of the same cluster is unavailable, but the cluster
  status stays unverified where missing data could have changed the
  result.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .pbs_source import PbsEvidence, ServerKey, server_key

SCOPE_OK = "ok"
SCOPE_UNAVAILABLE = "unavailable"
SCOPE_AMBIGUOUS = "ambiguous"

GuestKey = tuple[str, str]
"""(backup-type, backup-id) — the PBS identity of a guest."""


@dataclass(frozen=True)
class PbsBinding:
    """One pbs-type storage of a cluster: where its backups live."""

    server: ServerKey
    datastore: str
    namespace: str = ""
    """Missing namespace → root namespace "" (PVE: namespace optional)."""
    storage_id: str = ""
    """/storage row id — diagnostics only, never a matching key."""

    @property
    def store_key(self) -> tuple[str, int, str]:
        return (*self.server, self.datastore)

    @property
    def source_key(self) -> tuple[str, int, str, str]:
        return (*self.server, self.datastore, self.namespace)


@dataclass(frozen=True)
class PbsScope:
    """Selected PBS evidence for one cluster."""

    flat: dict[GuestKey, int] = field(default_factory=dict)
    status: str = SCOPE_OK
    reasons: tuple[str, ...] = ()

    @property
    def verified(self) -> bool:
        return self.status == SCOPE_OK


def bindings_from_storage_configs(configs: Sequence[Mapping]) \
        -> tuple[list[PbsBinding], list[str]]:
    """pbs-type rows of ``GET /storage`` → bindings (+ problems).

    Rows of other types are ignored. A pbs row without ``server`` or
    ``datastore`` is rejected (no guessing); a missing ``namespace`` is
    the documented root namespace. Full rows may contain secrets
    (password) — problem messages carry only the storage id, never row
    contents.
    """
    bindings: list[PbsBinding] = []
    problems: list[str] = []
    for row in configs or []:
        if str(row.get("type") or "") != "pbs":
            continue
        sid = str(row.get("storage") or "?")
        server = str(row.get("server") or "").strip()
        datastore = str(row.get("datastore") or "").strip()
        if not server or not datastore:
            missing = "server" if not server else "datastore"
            problems.append(f"storage '{sid}': {missing} missing")
            continue
        try:
            skey = server_key(server, row.get("port"))
        except ValueError:
            problems.append(f"storage '{sid}': invalid server port")
            continue
        bindings.append(PbsBinding(
            server=skey, datastore=datastore,
            namespace=str(row.get("namespace") or "").strip(),
            storage_id=sid))
    return bindings, problems


def select_pbs_evidence(
    evidence: PbsEvidence | None,
    cluster_bindings: Mapping[str, Sequence[PbsBinding] | None],
    cluster_guests: Mapping[str, set[GuestKey]],
    cluster_problems: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, PbsScope]:
    """Per-cluster PBS evidence selection (pure; one call per cycle).

    ``evidence is None`` — no PBS servers configured: PBS freshness is
    simply not part of the report (status ok, no evidence). ``None``
    bindings mean the cluster's storage configuration could not be
    collected → ``unavailable``.
    """
    problems = cluster_problems or {}
    if evidence is None:
        return {name: PbsScope({}, SCOPE_OK, tuple(problems.get(name, ())))
                for name in cluster_bindings}
    # source key → clusters referencing it (valid bindings only)
    refs: dict[tuple[str, int, str, str], set[str]] = {}
    for name, bindings in cluster_bindings.items():
        for b in bindings or ():
            refs.setdefault(b.source_key, set()).add(name)
    out: dict[str, PbsScope] = {}
    for name, bindings in cluster_bindings.items():
        if bindings is None:
            reasons = ["PBS storage configuration unavailable",
                       *problems.get(name, ())]
            out[name] = PbsScope({}, SCOPE_UNAVAILABLE, tuple(reasons))
            continue
        out[name] = _scope_for(evidence, name, bindings, refs,
                               cluster_guests, problems.get(name, ()))
    return out


def _scope_for(evidence: PbsEvidence, name: str,
               bindings: Sequence[PbsBinding],
               refs: Mapping[tuple[str, int, str, str], set[str]],
               cluster_guests: Mapping[str, set[GuestKey]],
               extra_problems: Sequence[str]) -> PbsScope:
    reasons: list[str] = list(extra_problems)
    unverified = bool(extra_problems)
    guests = cluster_guests.get(name, set())

    # 1. apply evidence of collected stores matched by bindings:
    #    per guest, keep every contributing source with its ts
    contributions: dict[GuestKey, dict[tuple[str, int, str, str], int]] = {}
    for b in bindings:
        if b.store_key not in evidence.collected_stores:
            host, port = b.server
            reasons.append(f"PBS {host}:{port}/{b.datastore} unavailable")
            unverified = True
            continue
        sub = evidence.by_source.get(b.source_key, {})
        for gk, ts in sub.items():
            if gk not in guests:
                continue  # a snapshot of no current guest of this cluster
            bucket = contributions.setdefault(gk, {})
            if ts > bucket.get(b.source_key, 0):
                bucket[b.source_key] = ts

    # 2. ambiguity: identifiers intersecting across clusters that share
    #    a source — the snapshot cannot be attributed to one of them
    ambiguous: set[tuple[tuple[str, int, str, str], GuestKey]] = set()
    for gk, srcs in contributions.items():
        for src in srcs:
            for other in refs.get(src, ()):
                if other == name:
                    continue
                if gk in cluster_guests.get(other, set()):
                    ambiguous.add((src, gk))

    flat: dict[GuestKey, int] = {}
    dropped: list[GuestKey] = []
    for gk, srcs in contributions.items():
        good = [src for src in srcs if (src, gk) not in ambiguous]
        if good:
            flat[gk] = max(srcs[src] for src in good)
        else:
            dropped.append(gk)
    if ambiguous:
        # any excluded contribution means the cluster's evidence was
        # affected by ambiguity — even when another source rescued the
        # guest (the fresher unattributable time must not win)
        status = SCOPE_AMBIGUOUS
        if dropped:
            reasons.append(_ambiguous_reason(dropped))
        else:
            reasons.append(
                "shared PBS source: ambiguous snapshot times excluded")
    elif unverified:
        status = SCOPE_UNAVAILABLE
    else:
        status = SCOPE_OK
    return PbsScope(flat=flat, status=status, reasons=tuple(reasons))


def _ambiguous_reason(dropped: list[GuestKey]) -> str:
    labels = sorted(f"{t}/{v}" for t, v in dropped)
    shown = ", ".join(labels[:8])
    more = len(labels) - 8
    if more > 0:
        shown += f", … +{more} more"
    return f"shared PBS source, ambiguous guests: {shown}"
