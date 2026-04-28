"""Top-row metric cards. Compact summary tile per metric."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analysis import stats
from analysis.signals import Signal
from config import Metric, PERCENTILE_HIGH, PERCENTILE_LOW


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


def render(metric: Metric, df: pd.DataFrame, signal: Signal) -> None:
    with st.container(border=True):
        st.markdown(f"**{metric.short_name}**")

        last = stats.latest(df)
        daily = stats.daily_change_pct(df)
        if last is None:
            st.markdown(":grey[No data]")
            return

        st.metric(
            label=metric.unit,
            value=f"{last:,.2f}",
            delta=f"{daily:+.2f}%" if daily is not None else None,
            label_visibility="visible",
        )

        st.plotly_chart(_sparkline(df, metric.color), width="stretch",
                        config={"displayModeBar": False})

        pct = stats.percentile_rank(df)
        chip_bg = _chip_color(pct)
        st.markdown(
            f"<div style='background:{chip_bg};color:#1e1e2e;padding:4px 8px;"
            f"border-radius:6px;font-size:0.78rem;text-align:center;"
            f"font-weight:600'>{signal.headline}</div>",
            unsafe_allow_html=True,
        )

        if df.attrs.get("is_stale"):
            st.caption(":orange[⚠ stale (showing snapshot)]")
