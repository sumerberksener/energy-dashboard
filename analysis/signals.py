"""Rule-based observations.

Phase 1 is deliberately rule-based — the README's roadmap tees up ML/NLP
successors. The trader-facing language is calibrated to be informative
without making predictions.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from analysis import stats
from config import (
    METRICS_BY_KEY,
    PERCENTILE_HIGH,
    PERCENTILE_LOW,
    SIGMA_EXTENDED,
    ZSCORE_OUTSIZED,
)


@dataclass
class Signal:
    metric_key: str
    headline: str          # 1-line tag, e.g. "Historically high"
    observation: str       # 2-3 sentence trader-facing observation
    severity: float        # |intensity| used to rank for the morning brief


def _fmt_pct(x: float | None) -> str:
    return f"{x:+.2f}%" if x is not None else "n/a"


def _percentile_label(p: float | None) -> tuple[str | None, float]:
    if p is None:
        return None, 0.0
    if p >= PERCENTILE_HIGH:
        return f"{p:.0f}th-percentile of 5-yr range — historically high", abs(p - 50)
    if p <= PERCENTILE_LOW:
        return f"{p:.0f}th-percentile of 5-yr range — historically low", abs(p - 50)
    return None, abs(p - 50)


def _extension_label(ext: float | None) -> tuple[str | None, float]:
    if ext is None:
        return None, 0.0
    if abs(ext) >= SIGMA_EXTENDED:
        side = "above" if ext > 0 else "below"
        return f"extended {abs(ext):.1f}σ {side} the 50d trend", abs(ext)
    return None, abs(ext)


def _move_label(z: float | None, change_pct: float | None) -> tuple[str | None, float]:
    if z is None or change_pct is None:
        return None, 0.0
    if abs(z) >= ZSCORE_OUTSIZED:
        return f"outsized daily move ({_fmt_pct(change_pct)}, {abs(z):.1f}σ)", abs(z)
    return None, abs(z)


def signal_for(metric_key: str, df: pd.DataFrame) -> Signal:
    """Generate a single Signal for one metric."""
    metric = METRICS_BY_KEY[metric_key]

    if df is None or df.empty:
        return Signal(metric_key, "No data", "Live data unavailable; please retry.", 0.0)

    pct_rank = stats.percentile_rank(df)
    ext = stats.extension_sigma(df, window=50)
    z = stats.daily_move_zscore(df)
    daily = stats.daily_change_pct(df)
    last = stats.latest(df)

    pct_text, pct_sev = _percentile_label(pct_rank)
    ext_text, ext_sev = _extension_label(ext)
    move_text, move_sev = _move_label(z, daily)

    # Storage gets a seasonal-deviation overlay (which is more informative than
    # a raw percentile for a strongly-seasonal series).
    seasonal_text = None
    seasonal_sev = 0.0
    if metric_key == "storage":
        dev = stats.seasonal_deviation_pp(df)
        if dev is not None:
            side = "above" if dev > 0 else "below"
            seasonal_text = f"{abs(dev):.1f} pp {side} the 5-yr seasonal average"
            seasonal_sev = abs(dev)

    # Pick the most striking headline.
    candidates = [
        (pct_text, pct_sev),
        (ext_text, ext_sev),
        (move_text, move_sev),
        (seasonal_text, seasonal_sev),
    ]
    candidates = [(t, s) for t, s in candidates if t]
    if candidates:
        headline, severity = max(candidates, key=lambda x: x[1])
    else:
        headline, severity = "Within typical range", 0.0

    bits: list[str] = []
    if pct_rank is not None:
        bits.append(f"{metric.short_name} prints at {last:,.2f} {metric.unit} ({pct_rank:.0f}th-pctile of 5y).")
    if ext_text:
        bits.append(f"Value is {ext_text}.")
    if move_text:
        bits.append(f"Yesterday's print was an {move_text}.")
    if seasonal_text:
        bits.append(f"Storage runs {seasonal_text}.")

    if not bits:
        bits.append(f"{metric.short_name} is trading in line with recent ranges.")

    observation = " ".join(bits)

    # Cross-metric tag could go here in future; left as-is for clarity.

    return Signal(metric_key, headline, observation, severity)


def morning_brief(data: dict[str, pd.DataFrame]) -> str:
    """Build a 3-sentence paragraph from the most-extreme signals across all 5."""
    signals = [signal_for(k, df) for k, df in data.items()]
    signals = [s for s in signals if s.headline not in ("No data", "Within typical range")]
    signals.sort(key=lambda s: s.severity, reverse=True)
    top = signals[:3]

    if not top:
        return (
            "Markets are quiet this morning — all tracked metrics sit within "
            "typical recent ranges. No standout signals."
        )

    intro = "Today's standouts:"
    parts = []
    for s in top:
        m = METRICS_BY_KEY[s.metric_key]
        parts.append(f"{m.short_name} — {s.headline.lower()}")
    return intro + " " + "; ".join(parts) + "."


def cross_market_tag(data: dict[str, pd.DataFrame]) -> str | None:
    """Tight-market / well-supplied tag from TTF percentile + storage seasonal deviation."""
    ttf = data.get("ttf")
    storage = data.get("storage")
    if ttf is None or storage is None or ttf.empty or storage.empty:
        return None
    p_ttf = stats.percentile_rank(ttf)
    dev = stats.seasonal_deviation_pp(storage)
    if p_ttf is None or dev is None:
        return None
    if p_ttf >= 75 and dev <= -3:
        return "Tight market: TTF rich vs history while storage runs below seasonal."
    if p_ttf <= 25 and dev >= 3:
        return "Well-supplied: TTF soft vs history with storage above seasonal."
    return None
