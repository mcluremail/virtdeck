"""M4.3: version drift — nodes lagging behind the cluster's PVE leader.

Input is ``node_versions`` from ClusterFleetReport (node → pveversion
raw). Lag level relative to the newest node in the cluster:
``ok`` (equal) → ``patch`` (behind a patch) → ``minor`` → ``major``;
unparseable versions yield ``unknown`` and are not hidden (they cannot
be compared — that alone is a signal). The risk this report closes
(B24): incompatibility in future cross-cluster operations.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..domain.compat import PveVersion, parse_pve_version

# Severity order; unknown between minor and patch — flags earlier than
# a small lag, but later than a real version break.
_SEVERITY = {"ok": 0, "patch": 1, "unknown": 2, "minor": 3, "major": 4}


@dataclass(frozen=True)
class NodeDrift:
    node: str
    version: str
    """pveversion raw, as in the collection report."""
    level: str
    """'ok' | 'patch' | 'unknown' | 'minor' | 'major'."""
    newest_node: str
    newest_version: str


def _level(own: PveVersion, newest: PveVersion) -> str:
    if own == newest:
        return "ok"
    if own.major != newest.major:
        return "major"
    if own.minor != newest.minor:
        return "minor"
    return "patch"


def detect_drift(node_versions: Mapping[str, str]) -> tuple[NodeDrift, ...]:
    """How far each node lags behind the newest in the cluster."""
    parsed: dict[str, PveVersion] = {}
    for node, raw in node_versions.items():
        version = parse_pve_version(raw)
        if version is not None:
            parsed[node] = version
    if not parsed:
        return tuple(
            NodeDrift(node=node, version=raw, level="unknown",
                      newest_node="", newest_version="")
            for node, raw in sorted(node_versions.items())
        )
    newest_node, newest_version = max(
        parsed.items(), key=lambda item: item[1].as_tuple())
    rows = [
        NodeDrift(
            node=node,
            version=node_versions.get(node, ""),
            level="unknown" if node not in parsed
            else _level(parsed[node], newest_version),
            newest_node=newest_node,
            newest_version=node_versions.get(newest_node, ""),
        )
        for node in node_versions
    ]
    rows.sort(key=lambda r: (-_SEVERITY[r.level], r.node))
    return tuple(rows)
