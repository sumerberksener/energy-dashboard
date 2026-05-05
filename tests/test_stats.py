"""Pin the stats helpers — including the absolute-vs-pct delta split for spreads
and the smoothed weekly comparison that hardens against holiday-week spikes.
"""
from __future__ import annotations

import pandas as pd
import pytest

from analysis import stats


def _frame(values: list[float]) -> pd.DataFrame:
    n = len(values)
    idx = pd.date_range(end="2026-05-05", periods=n, freq="D", name="date")
    return pd.DataFrame({"value": values}, index=idx)


def test_daily_change_pct():
    df = _frame([100.0, 110.0])
    assert stats.daily_change_pct(df) == pytest.approx(10.0)


def test_daily_change_abs():
    """Spreads use abs change because pct across zero is meaningless."""
    df = _frame([-5.0, +5.0])
    assert stats.daily_change_abs(df) == pytest.approx(10.0)
    # And confirm the pct version would be misleading (latest/prev − 1 = -2)
    assert stats.daily_change_pct(df) == pytest.approx(-200.0)


def test_change_over_pct_point_to_point():
    df = _frame([100.0] * 5 + [200.0])
    assert stats.change_over_pct(df, 5) == pytest.approx(100.0)


def test_change_over_pct_smoothed_dampens_holiday_spike():
    """Regression: with a single holiday-style negative spike, smoothed weekly
    change is much closer to the underlying trend than point-to-point.

    Series: 100s for 5 days, then a -10 spike, then 100s for 5 more days.
    Point-to-point compares latest (100) to the spike (-10) → wild number.
    Smoothed compares mean(last 5) ≈ 100 to mean(prior 5) ≈ 82 (which has the
    spike inside) → a much more reasonable ~22%.
    """
    series = [100.0] * 5 + [-10.0] + [100.0] * 5
    df = _frame(series)

    raw = stats.change_over_pct(df, 5)
    smoothed = stats.change_over_pct(df, 5, smooth_window=5)
    assert raw is not None and smoothed is not None
    assert abs(raw) > abs(smoothed) * 5, (
        f"Smoothed weekly should be much smaller than raw on a holiday spike. "
        f"Got raw={raw}, smoothed={smoothed}"
    )


def test_change_over_abs_smoothed():
    series = [10.0] * 5 + [50.0] + [10.0] * 5
    df = _frame(series)
    smoothed = stats.change_over_abs(df, 5, smooth_window=5)
    # mean(last 5) = 10, mean(prior 5) = (10+10+10+10+50)/5 = 18 → -8
    assert smoothed == pytest.approx(-8.0)


def test_is_stale():
    fresh_idx = pd.date_range(end="2026-05-05", periods=3, freq="D")
    fresh = pd.DataFrame({"value": [1.0, 2.0, 3.0]}, index=fresh_idx)
    old_idx = pd.date_range(end="2025-12-01", periods=3, freq="D")
    old = pd.DataFrame({"value": [1.0, 2.0, 3.0]}, index=old_idx)

    assert stats.is_stale(old, threshold_days=5) is True
    assert stats.is_stale(fresh, threshold_days=5) is False


def test_percentile_rank():
    df = _frame(list(range(100)))  # 0..99
    p = stats.percentile_rank(df)
    # Latest (99) is the max → 100th percentile
    assert p == pytest.approx(100.0)


def test_extension_sigma_zero_when_flat():
    df = _frame([5.0] * 100)
    out = stats.extension_sigma(df, window=50)
    # σ=0 → cannot compute → returns None per the implementation
    assert out is None
