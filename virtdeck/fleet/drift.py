"""M4.3: version drift — ноды, отстающие по версии PVE от лидера кластера.

Вход — ``node_versions`` из ClusterFleetReport (node → pveversion raw).
Уровень отставания относительно самой свежей ноды кластера:
``ok`` (равна) → ``patch`` (отстал patch) → ``minor`` → ``major``;
неразбираемые версии дают ``unknown`` и не скрываются (сравнить нельзя —
это само по себе сигнал). Риск, который закрывает отчёт (B24):
несовместимость при будущих cross-cluster операциях.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..domain.compat import PveVersion, parse_pve_version

# Порядок серьёзности; unknown между minor и patch — сигнализирует раньше
# мелкого отставания, но позже реального разрыва версий.
_SEVERITY = {"ok": 0, "patch": 1, "unknown": 2, "minor": 3, "major": 4}


@dataclass(frozen=True)
class NodeDrift:
    node: str
    version: str
    """pveversion raw, как в отчёте сбора."""
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
    """Уровень отставания каждой ноды от самой свежей в кластере."""
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
