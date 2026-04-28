"""5-year Plotly chart with 50d MA and percentile bands."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from analysis import stats
from config import Metric


def five_year_chart(metric: Metric, df: pd.DataFrame) -> go.Figure:
    s = df["value"].dropna()
    ma50 = s.rolling(50).mean()
    p10, p90 = stats.percentile_band(df, 10, 90)

    fig = go.Figure()

    fig.add_hrect(
        y0=p10, y1=p90,
        fillcolor="rgba(137, 180, 250, 0.08)", line_width=0,
        annotation_text="10–90 pctile (5y)", annotation_position="top left",
        annotation_font_size=10, annotation_font_color="#7f849c",
    )

    fig.add_trace(go.Scatter(
        x=s.index, y=s.values, mode="lines",
        name=metric.short_name,
        line=dict(color=metric.color, width=2),
        hovertemplate="%{x|%Y-%m-%d}<br>%{y:.2f} " + metric.unit + "<extra></extra>",
    ))

    fig.add_trace(go.Scatter(
        x=ma50.index, y=ma50.values, mode="lines",
        name="50-day MA",
        line=dict(color="#cdd6f4", width=1.2, dash="dot"),
        hovertemplate="%{x|%Y-%m-%d}<br>MA50: %{y:.2f}<extra></extra>",
    ))

    fig.update_layout(
        title=f"{metric.name} — 5-year history",
        height=420,
        margin=dict(l=20, r=20, t=50, b=40),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.02)",
        xaxis=dict(
            rangeslider=dict(visible=True, thickness=0.05),
            showgrid=False,
        ),
        yaxis=dict(title=metric.unit, gridcolor="rgba(255,255,255,0.08)"),
        legend=dict(orientation="h", y=-0.25, x=0),
        hovermode="x unified",
    )
    return fig


def stats_table(df: pd.DataFrame, metric: Metric) -> pd.DataFrame:
    last = stats.latest(df)
    rows = {
        "Latest": f"{last:,.2f} {metric.unit}" if last is not None else "n/a",
        "1d Δ":   _fmt(stats.daily_change_pct(df)),
        "1w Δ":   _fmt(stats.change_over_pct(df, 5)),
        "1m Δ":   _fmt(stats.change_over_pct(df, 21)),
        "1y Δ":   _fmt(stats.change_over_pct(df, 252)),
    }
    lo, hi = stats.high_low(df)
    rows["5y low"] = f"{lo:,.2f}" if lo is not None else "n/a"
    rows["5y high"] = f"{hi:,.2f}" if hi is not None else "n/a"
    p = stats.percentile_rank(df)
    rows["Pctile rank (5y)"] = f"{p:.0f}" if p is not None else "n/a"
    return pd.DataFrame(rows.items(), columns=["", "Value"]).set_index("")


def _fmt(x: float | None) -> str:
    return f"{x:+.2f}%" if x is not None else "n/a"
