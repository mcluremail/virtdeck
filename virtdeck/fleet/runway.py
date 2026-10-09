"""M4.3: storage runway — "storage runs out in ~N days" forecast.

Input is a storage rrddata series
(GET /nodes/{node}/storage/{store}/rrddata): points ``{time, used,
total}`` where used/total may be None (rrdcached holes, outages) —
naive linearity over a holey series lies (B24). Model: least squares
over the last window, 95% confidence interval on the slope (normal
approximation, only with a sufficiently dense series).

Forecast quality: ``ok`` (n >= 8, CI present) / ``sparse`` (few points —
point estimate without CI) / ``no-trend`` (slope <= 0 — never fills) /
``no-capacity`` (unknown total) / ``no-data`` (fewer than 2 points).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

SECONDS_PER_DAY = 86400.0
_Z95 = 1.96
_MIN_POINTS_FOR_CI = 8

# forecast quality
OK = "ok"
SPARSE = "sparse"
NO_TREND = "no-trend"
NO_CAPACITY = "no-capacity"
NO_DATA = "no-data"


@dataclass(frozen=True)
class RunwayEstimate:
    node: str
    storage: str
    used_bytes: int | None
    """Last known used."""
    total_bytes: int | None
    slope_bytes_per_day: float | None
    days_left: float | None
    """Point estimate; None — never fills or forecast impossible."""
    days_left_low: float | None
    """Pessimistic bound (slope at the upper CI)."""
    days_left_high: float | None
    """Optimistic bound (slope at the lower CI)."""
    points_used: int
    quality: str
    last_point_age_days: float | None = None
    """Age of the freshest series point against the caller's ``now`` —
    None when unknown; a stale series means the node was unreachable and
    the forecast silently builds on old data unless surfaced."""


def _valid_points(series: Sequence[dict]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for row in series:
        t, used = row.get("time"), row.get("used")
        try:
            points.append((float(t), float(used)))
        except (TypeError, ValueError):
            continue  # rrddata holes (None/garbage) are dropped
    points.sort()
    return points


def _fit(points: list[tuple[float, float]]) -> tuple[float, float, float]:
    """Least squares: (slope/day, intercept, slope standard error)."""
    n = len(points)
    x0 = points[0][0]
    xs = [(t - x0) / SECONDS_PER_DAY for t, _u in points]
    ys = [u for _t, u in points]
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    # identical timestamps (degenerate rrddata) → sxx == 0: no slope is
    # computable; slope 0 lands in the honest "no-trend" branch below
    slope = sxy / sxx if sxx else 0.0
    intercept = my - slope * mx
    if n < 3:
        return slope, intercept, 0.0
    sse = sum((y - (slope * x + intercept)) ** 2
              for x, y in zip(xs, ys, strict=True))
    se = math.sqrt(sse / (n - 2) / sxx) if sxx > 0 else 0.0
    return slope, intercept, se


def _days_until_full(total: float, used_now: float,
                     slope: float) -> float | None:
    if slope <= 0:
        return None
    return max(0.0, (total - used_now) / slope)


def estimate_runway(series: Sequence[dict], *, node: str = "",
                    storage: str = "", window_days: int = 30,
                    now: float | None = None) \
        -> RunwayEstimate:
    """Forecast from an rrddata series (see module doc).

    ``now`` — wall-clock epoch: when given, the estimate carries the age
    of its freshest point (``last_point_age_days``) so the UI can flag a
    forecast built on stale data.
    """
    points = _valid_points(series)

    # total — from the freshest series point where it is known and positive.
    total: float | None = None
    total_ts: float | None = None
    for row in series:
        t = row.get("time")
        try:
            ts = float(t) if t is not None else 0.0
            value = float(row.get("total"))
        except (TypeError, ValueError):
            continue
        if value > 0 and (total_ts is None or ts > total_ts):
            total, total_ts = value, ts

    used_now: float | None = points[-1][1] if points else None

    if points and window_days > 0:
        cutoff = points[-1][0] - window_days * SECONDS_PER_DAY
        points = [p for p in points if p[0] >= cutoff]

    base = dict(node=node, storage=storage, total_bytes=total,
                used_bytes=int(used_now) if used_now is not None else None)
    if now is not None and points:
        base["last_point_age_days"] = max(
            0.0, (now - points[-1][0]) / SECONDS_PER_DAY)

    if len(points) < 2:
        return RunwayEstimate(slope_bytes_per_day=None, days_left=None,
                              days_left_low=None, days_left_high=None,
                              points_used=len(points), quality=NO_DATA,
                              **base)
    slope, _intercept, se = _fit(points)
    if slope <= 0:
        return RunwayEstimate(slope_bytes_per_day=slope, days_left=None,
                              days_left_low=None, days_left_high=None,
                              points_used=len(points), quality=NO_TREND,
                              **base)
    if total is None:
        return RunwayEstimate(slope_bytes_per_day=slope, days_left=None,
                              days_left_low=None, days_left_high=None,
                              points_used=len(points), quality=NO_CAPACITY,
                              **base)
    days = _days_until_full(total, used_now, slope)
    if len(points) < _MIN_POINTS_FOR_CI:
        return RunwayEstimate(slope_bytes_per_day=slope, days_left=days,
                              days_left_low=None, days_left_high=None,
                              points_used=len(points), quality=SPARSE,
                              **base)
    # 95% CI on the slope: pessimism is the upper slope (fills sooner).
    slope_hi = slope + _Z95 * se
    slope_lo = slope - _Z95 * se
    low = _days_until_full(total, used_now, slope_hi) \
        if slope_hi > 0 else None
    high = _days_until_full(total, used_now, slope_lo) \
        if slope_lo > 0 else None
    return RunwayEstimate(slope_bytes_per_day=slope, days_left=days,
                          days_left_low=low, days_left_high=high,
                          points_used=len(points), quality=OK, **base)
