"""Pure stats helpers used by the signals layer and the chart layer.

All functions accept a tidy DataFrame with a single 'value' column indexed by
date (as produced by data/fetchers.py). They return scalars or Series; they
never mutate the input.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _series(df: pd.DataFrame) -> pd.Series:
    return df["value"].dropna()


def latest(df: pd.DataFrame) -> float | None:
    s = _series(df)
    return float(s.iloc[-1]) if len(s) else None


def daily_change_pct(df: pd.DataFrame) -> float | None:
    s = _series(df)
    if len(s) < 2:
        return None
    return float((s.iloc[-1] / s.iloc[-2] - 1) * 100)


def change_over_pct(
    df: pd.DataFrame,
    business_days: int,
    *,
    smooth_window: int | None = None,
) -> float | None:
    """Pct change over `business_days`. With smoothing, compares trailing means.

    Without `smooth_window`, this is point-to-point: latest vs latest−N. That's
    fragile for series with single-day holiday spikes (e.g. DE Power around
    public holidays where day-ahead prints can be deeply negative). Pass
    `smooth_window=N` to compare the N-day trailing mean today vs the N-day
    trailing mean N business days ago — much more robust.
    """
    s = _series(df)
    if len(s) <= business_days:
        return None
    if smooth_window is None or smooth_window <= 1:
        return float((s.iloc[-1] / s.iloc[-1 - business_days] - 1) * 100)
    if len(s) < business_days + smooth_window:
        return None
    recent = s.iloc[-smooth_window:].mean()
    prior = s.iloc[-business_days - smooth_window:-business_days].mean()
    if prior == 0 or not pd.notna(prior):
        return None
    return float((recent / prior - 1) * 100)


def daily_change_abs(df: pd.DataFrame) -> float | None:
    """Absolute change vs prior row, in the metric's native units.

    Used for spreads (clean spark / clean dark) where pct change across a
    sign flip or near-zero denominator is mathematically meaningless.
    """
    s = _series(df)
    if len(s) < 2:
        return None
    return float(s.iloc[-1] - s.iloc[-2])


def change_over_abs(
    df: pd.DataFrame,
    business_days: int,
    *,
    smooth_window: int | None = None,
) -> float | None:
    """Absolute change over `business_days`. With smoothing, compares trailing means."""
    s = _series(df)
    if len(s) <= business_days:
        return None
    if smooth_window is None or smooth_window <= 1:
        return float(s.iloc[-1] - s.iloc[-1 - business_days])
    if len(s) < business_days + smooth_window:
        return None
    recent = s.iloc[-smooth_window:].mean()
    prior = s.iloc[-business_days - smooth_window:-business_days].mean()
    if not pd.notna(prior):
        return None
    return float(recent - prior)


def days_since_latest(df: pd.DataFrame, ref: pd.Timestamp | None = None) -> int | None:
    """Calendar days between `ref` (default today UTC) and the latest data row."""
    s = _series(df)
    if not len(s):
        return None
    ref = (ref or pd.Timestamp.now(tz="UTC")).tz_localize(None).normalize()
    last = pd.Timestamp(s.index.max()).normalize()
    return int((ref - last).days)


def is_stale(df: pd.DataFrame, threshold_days: int) -> bool:
    """True if latest data is older than `threshold_days`."""
    d = days_since_latest(df)
    return d is not None and d > threshold_days


def percentile_rank(df: pd.DataFrame) -> float | None:
    """Where does the latest value sit in the historical distribution? 0–100."""
    s = _series(df)
    if len(s) < 30:
        return None
    last = s.iloc[-1]
    return float((s <= last).mean() * 100)


def rolling_ma(df: pd.DataFrame, window: int) -> pd.Series:
    return _series(df).rolling(window).mean()


def percentile_band(df: pd.DataFrame, low: float = 10, high: float = 90) -> tuple[float, float]:
    s = _series(df)
    return float(np.percentile(s, low)), float(np.percentile(s, high))


def extension_sigma(df: pd.DataFrame, window: int = 50) -> float | None:
    """How many σ is the latest value above/below its `window`-day moving average?"""
    s = _series(df)
    if len(s) < window + 1:
        return None
    ma = s.rolling(window).mean().iloc[-1]
    sd = s.rolling(window).std().iloc[-1]
    if not np.isfinite(sd) or sd == 0:
        return None
    return float((s.iloc[-1] - ma) / sd)


def daily_move_zscore(df: pd.DataFrame, window: int = 60) -> float | None:
    """z-score of today's pct return vs the trailing `window`-day return distribution."""
    s = _series(df)
    if len(s) < window + 2:
        return None
    rets = s.pct_change().dropna()
    last = rets.iloc[-1]
    history = rets.iloc[-(window + 1):-1]
    sd = history.std()
    if not np.isfinite(sd) or sd == 0:
        return None
    return float((last - history.mean()) / sd)


def high_low(df: pd.DataFrame) -> tuple[float | None, float | None]:
    s = _series(df)
    if not len(s):
        return None, None
    return float(s.min()), float(s.max())


def seasonal_deviation_pp(df: pd.DataFrame) -> float | None:
    """For storage % full: current value minus same-day-of-year average.

    Returns the deviation in percentage points (since storage is already a %).
    """
    s = _series(df)
    if len(s) < 30:
        return None
    today = s.index[-1]
    same_day = s[(s.index.month == today.month) & (s.index.day == today.day)]
    if len(same_day) < 2:
        # Not enough years yet — relax to a ±3-day window.
        same_day = s[
            (abs((s.index - today).days) <= 3)
            | ((s.index.month == today.month) & (abs(s.index.day - today.day) <= 3))
        ]
    same_day_excl_today = same_day[same_day.index != today]
    if not len(same_day_excl_today):
        return None
    return float(s.iloc[-1] - same_day_excl_today.mean())
