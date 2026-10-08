"""M0.5: PVE compat matrix — node versions and capabilities.

The core does not hardcode PVE versions: consumers (M4 — rrddata/version
drift, M5 — migrate/HA nuances) ask ``supports(feature)`` on the provider.
The ``PVE_FEATURES`` matrix maps known features to minimum versions;
extend it via :func:`register_feature`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PveVersion:
    major: int
    minor: int
    patch: int = 0

    def as_tuple(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)

    def __str__(self) -> str:
        return (
            f"{self.major}.{self.minor}"
            if self.patch == 0
            else f"{self.major}.{self.minor}.{self.patch}"
        )


# feature -> minimum version (major, minor). Supported matrix:
# 7.x/8.x/9.x; older than 7.x is best effort, no guarantees.
PVE_FEATURES: dict[str, tuple[int, int]] = {
    "version": (6, 2),  # GET /nodes/{node}/version
    "rrddata": (6, 0),  # GET .../rrddata — node and guest metrics
    "guest_tags": (8, 0),  # VM/container tags (API + UI)
}


def register_feature(name: str, major: int, minor: int) -> None:
    """Add a feature to the matrix (for M4/M5 and plugins)."""
    PVE_FEATURES[name] = (int(major), int(minor))


def _parse_dotted(part: str) -> PveVersion | None:
    """'8.2.4' / '8.2' / '8' / '7.4-3' (minor-patch) → PveVersion; else None."""
    nums: list[int] = []
    for c in part.split("."):
        if "-" in c:
            head, tail = c.split("-", 1)
            if not (head.isdigit() and tail.isdigit()):
                return None
            nums.append(int(head))
            nums.append(int(tail))
        elif c.isdigit():
            nums.append(int(c))
        else:
            return None
    if not 1 <= len(nums) <= 3:
        return None
    while len(nums) < 3:
        nums.append(0)
    return PveVersion(*nums)


def parse_pve_version(raw: str | None) -> PveVersion | None:
    """Parse pveversion: ``pve-manager/8.2.4/1ac2f4b`` or ``8.2.4``.

    Hash part (``1ac2f4b``) and garbage are dropped; no version → None.
    """
    if not raw:
        return None
    text = str(raw).strip()
    if "/" in text:
        for part in text.split("/"):
            v = _parse_dotted(part)
            if v is not None:
                return v
        return None
    return _parse_dotted(text)


def supports(version: PveVersion | None, feature: str) -> bool:
    """Whether the version supports the feature. Unknown version/feature →
    False (conservative: the caller falls back)."""
    min_version = PVE_FEATURES.get(feature)
    if version is None or min_version is None:
        return False
    return version.as_tuple()[:2] >= min_version
