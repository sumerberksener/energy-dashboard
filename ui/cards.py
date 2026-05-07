"""Top-row metric cards with time-frame labels, tooltips, multi-horizon deltas,
direction-aware delta colour, and a freshness badge.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analysis import stats
from analysis.signals import Signal
from config import (
    Metric,
    PERCENTILE_HIGH,
    PERCENTILE_LOW,
    STALE_AFTER_DAYS,
)


def _sparkline(df: pd.DataFrame, color: str) -> go.Figure:
    s = df["value"].dropna().iloc[-30:]
    fig = go.Figure(
        data=[go.Scatter(x=s.index, y=s.values, mode="lines",
                         line=dict(color=color, width=2), hoverinfo="skip")]
    )
    fig.update_layout(
        height=60,
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    return fig


def _chip_color(percentile: float | None) -> str:
    if percentile is None:
        return "#6c7086"
    if percentile >= PERCENTILE_HIGH:
        return "#f38ba8"
    if percentile <= PERCENTILE_LOW:
        return "#94e2d5"
    return "#6c7086"


def _delta_color(metric: Metric) -> str:
    """Map metric semantics to st.metric delta_color.

    - "bullish-power"  → up implies higher power cost → render up as RED (`inverse`)
    - "supply-rich"    → up implies more supply / less tightness → up GREEN (`normal`)
    - "margin-rich"    → up implies more plant margin / more headroom → up GREEN (`normal`)
    """
    return "inverse" if metric.higher_is == "bullish-power" else "normal"


def _fmt_pct(x: float | None) -> str:
    return f"{x:+.2f}%" if x is not None else "—"


def _fmt_abs(x: float | None) -> str:
    return f"{x:+.2f}" if x is not None else "—"


def _delta_string(metric: Metric, df: pd.DataFrame, business_days: int) -> str:
    """Compute the appropriate delta string for the metric over a window."""
    if business_days <= 1:
        if metric.delta_unit == "abs":
            return _fmt_abs(stats.daily_change_abs(df))
        return _fmt_pct(stats.daily_change_pct(df))
    if metric.delta_unit == "abs":
        return _fmt_abs(stats.change_over_abs(df, business_days, smooth_window=5, skip_below_abs=5))
    return _fmt_pct(stats.change_over_pct(df, business_days, smooth_window=5, skip_below_abs=5))


def _horizon_strip(metric: Metric, df: pd.DataFrame) -> str:
    """1d / 1w / 1m delta chips as a single HTML string."""
    horizons = [("1d", 1), ("1w", 5), ("1m", 21)]
    chips = []
    for label, bd in horizons:
        delta = _delta_string(metric, df, bd)
        chips.append(
            f"<span style='display:inline-block;background:#313244;color:#cdd6f4;"
            f"padding:2px 8px;border-radius:5px;font-size:0.72rem;margin-right:4px;"
            f"font-variant-numeric:tabular-nums'>"
            f"<span style='color:#7f849c'>{label}</span> {delta}</span>"
        )
    return "<div style='margin-top:4px'>" + "".join(chips) + "</div>"


def render(metric: Metric, df: pd.DataFrame, signal: Signal) -> None:
    """Render a single metric card.

    Includes: tooltip (full definition), 1d delta with direction-aware colour,
    1d/1w/1m chip strip, 30-day sparkline (labelled), percentile chip, and a
    freshness badge if data is older than STALE_AFTER_DAYS.
    """
    with st.container(border=True):
        if df is None or df.empty:
            st.markdown(f"**{metric.short_name}**")
            st.caption(":grey[no data]")
            return

        last = stats.latest(df)
        if last is None:
            st.markdown(f"**{metric.short_name}**")
            st.caption(":grey[no data]")
            return

        # Daily delta — value + label
        if metric.delta_unit == "abs":
            d1 = stats.daily_change_abs(df)
            delta_value = f"{d1:+.2f} {metric.unit} (1d)" if d1 is not None else None
        else:
            d1 = stats.daily_change_pct(df)
            delta_value = f"{d1:+.2f}% (1d)" if d1 is not None else None

        help_text = f"{metric.definition}\n\nSource: {metric.source}"

        st.metric(
            label=f"{metric.short_name} ({metric.unit})",
            value=f"{last:,.2f}",
            delta=delta_value,
            delta_color=_delta_color(metric),
            help=help_text,
        )

        # Multi-horizon strip: 1d / 1w / 1m
        st.markdown(_horizon_strip(metric, df), unsafe_allow_html=True)

        # Sparkline + caption
        st.plotly_chart(_sparkline(df, metric.color), width="stretch",
                        config={"displayModeBar": False})
        st.caption("Last 30d")

        # Headline chip
        pct = stats.percentile_rank(df)
        chip_bg = _chip_color(pct)
        st.markdown(
            f"<div style='background:{chip_bg};color:#1e1e2e;padding:4px 8px;"
            f"border-radius:6px;font-size:0.75rem;text-align:center;"
            f"font-weight:600'>{signal.headline}</div>",
            unsafe_allow_html=True,
        )

        # Freshness badge
        days_old = stats.days_since_latest(df)
        if days_old is not None:
            if stats.is_stale(df, STALE_AFTER_DAYS):
                st.caption(
                    f":orange[⚠ STALE — last {df.index.max():%Y-%m-%d} ({days_old}d old)]"
                )
            elif df.attrs.get("is_stale"):
                st.caption(":orange[⚠ snapshot fallback]")
