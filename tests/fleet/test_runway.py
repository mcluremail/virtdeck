"""M4.3: storage runway — прогноз по дырявому rrddata.

Каждый кейс — одно правило: дыры отбрасываются, окно ограничивает,
CI появляется только на плотном ряде, наклон <= 0 — «не кончится»,
unknown total — «no-capacity».
"""

from __future__ import annotations

import pytest

from virtdeck.fleet.runway import (
    NO_CAPACITY,
    NO_DATA,
    NO_TREND,
    OK,
    SPARSE,
    estimate_runway,
)

GIB = 1 << 30
T0 = 1727827200


def series(hours: int, *, used0: int = 5 * GIB, per_hour: int = GIB // 24,
           total: int | None = 10 * GIB, gap_at: int | None = None,
           total_at: dict[int, int] | None = None,
           noise: dict[int, int] | None = None) -> list[dict]:
    rows = []
    for i in range(hours):
        used = None if i == gap_at else used0 + i * per_hour
        if used is not None and noise and i in noise:
            used += noise[i]
        rows.append({"time": T0 + i * 3600,
                     "total": (total_at or {}).get(i, total),
                     "used": used})
    return rows


def test_rising_series_point_estimate():
    est = estimate_runway(series(48), node="pve01", storage="local")
    assert est.quality == OK
    used_last = 5 * GIB + 47 * (GIB // 24)
    expected = (10 * GIB - used_last) / GIB  # темп = 1 GiB/день
    assert est.days_left == pytest.approx(expected, rel=1e-6)
    assert est.points_used == 48
    assert est.total_bytes == 10 * GIB
    assert est.used_bytes == used_last


def test_noise_gives_ci_containing_estimate():
    noise = {i: (GIB // 16 if i % 2 else -GIB // 16) for i in range(48)}
    est = estimate_runway(series(48, noise=noise))
    assert est.quality == OK
    assert est.days_left_low < est.days_left < est.days_left_high


def test_falling_series_never_fills():
    est = estimate_runway(series(48, per_hour=-(10 * GIB // 24)))
    assert est.quality == NO_TREND
    assert est.days_left is None


def test_constant_series_no_trend():
    est = estimate_runway(series(30, per_hour=0))
    assert est.quality == NO_TREND


def test_gaps_dropped():
    est = estimate_runway(series(48, gap_at=5))
    assert est.points_used == 47
    assert est.used_bytes == 5 * GIB + 47 * (GIB // 24)


def test_all_gaps_no_data():
    rows = [{"time": T0 + i * 3600, "used": None, "total": 10 * GIB}
            for i in range(48)]
    est = estimate_runway(rows)
    assert est.quality == NO_DATA
    assert est.days_left is None and est.slope_bytes_per_day is None


def test_window_limits_points():
    est = estimate_runway(series(60), window_days=1)
    # последним 24 часам соответствуют 25 точек (включительно)
    assert est.points_used == 25


def test_sparse_few_points_no_ci():
    est = estimate_runway(series(5))
    assert est.quality == SPARSE
    assert est.days_left is not None
    assert est.days_left_low is None and est.days_left_high is None


def test_no_capacity():
    est = estimate_runway(series(48, total=None))
    assert est.quality == NO_CAPACITY
    assert est.slope_bytes_per_day is not None
    assert est.days_left is None


def test_total_from_newest_known_point():
    # total вырос до 20 GiB начиная с точки 10 — берётся самая свежая
    est = estimate_runway(series(48, total_at={i: 20 * GIB
                                               for i in range(10, 48)}))
    assert est.total_bytes == 20 * GIB
    assert est.quality == OK


def test_single_point_no_data():
    est = estimate_runway(series(1))
    assert est.quality == NO_DATA


def test_two_points_sparse():
    est = estimate_runway(series(2))
    assert est.quality == SPARSE
    assert est.days_left is not None
