"""Power curve panel — DA price vs an indicative Cal+1 seasonality projection.

This panel is the brief's "Day-Ahead → curve" output. We don't have free
access to EEX Cal-Year settlement, so the Cal+1 line is a **seasonality-
based projection** computed from historical DA realisations, NOT a market
quote. The panel is honest about that on screen, in the tooltip, and in
the methodology tab.

When the gap (DA − Cal+1 proj) is positive, today's front prices above
the typical year-ahead realisation → backwardation regime (front strong).
Negative ⇒ contango (back strong).
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analysis import stats


def _chart(de: pd.DataFrame, cal1_proj: pd.DataFrame) -> go.Figure:
    cutoff = pd.Timestamp.now().normalize() - pd.DateOffset(years=2)
    de_recent = de[de.index >= cutoff]
    proj_recent = cal1_proj[cal1_proj.index >= cutoff]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=de_recent.index, y=de_recent["value"], mode="lines",
        name="DE DA (realised)",
        line=dict(color="#89b4fa", width=2),
        hovertemplate="%{x|%Y-%m-%d}<br>DA: %{y:.2f} EUR/MWh<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=proj_recent.index, y=proj_recent["value"], mode="lines",
        name="Cal+1 proj (seasonality model)",
        line=dict(color="#f9e2af", width=2, dash="dot"),
        hovertemplate="%{x|%Y-%m-%d}<br>Proj: %{y:.2f} EUR/MWh<extra></extra>",
    ))
    fig.update_layout(
        title="DE Power: DA vs indicative Cal+1 (model — not a market quote)",
        height=320,
        margin=dict(l=20, r=20, t=50, b=40),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(255,255,255,0.02)",
        yaxis=dict(title="EUR/MWh", gridcolor="rgba(255,255,255,0.08)"),
        legend=dict(orientation="h", y=-0.2, x=0),
        hovermode="x unified",
    )
    return fig


def render(data: dict[str, pd.DataFrame]) -> None:
    """Render the Power Curve panel — KPIs + chart in an expander."""
    de = data.get("de_power")
    cal1 = data.get("de_cal1_proj")

    if de is None or de.empty or cal1 is None or cal1.empty:
        return

    de_last = stats.latest(de)
    cal1_last = stats.latest(cal1)
    if de_last is None or cal1_last is None:
        return

    gap = de_last - cal1_last
    if gap > 1:
        regime = "Backwardation"
        regime_color = "#f38ba8"
        explanation = (
            "DA prints above the seasonal year-ahead level — front-end of the "
            "curve is rich. Markets typically signal supply tightness or "
            "elevated short-term risk in this regime."
        )
    elif gap < -1:
        regime = "Contango"
        regime_color = "#a6e3a1"
        explanation = (
            "DA prints below the seasonal year-ahead level — back of the "
            "curve carries the premium. Often signals expected tightening "
            "ahead, or current oversupply."
        )
    else:
        regime = "Flat"
        regime_color = "#cdd6f4"
        explanation = "DA and the year-ahead projection are roughly in line."

    with st.expander(
        f"Power curve indicative — DA vs Cal+1 proj  ·  "
        f"{gap:+.1f} EUR/MWh  ·  {regime}",
        expanded=True,
    ):
        col_kpi, col_explain = st.columns([1, 2])
        with col_kpi:
            st.markdown(
                f"<div style='padding:10px 16px; background:#181825; "
                f"border-radius:10px; border:1px solid rgba(137,180,250,0.18);'>"
                f"<div style='font-size:0.7rem; text-transform:uppercase; "
                f"letter-spacing:0.06em; color:#7f849c'>Today's DA</div>"
                f"<div style='font-size:1.4rem; font-weight:600;'>{de_last:,.2f} EUR/MWh</div>"
                f"<div style='font-size:0.7rem; text-transform:uppercase; "
                f"letter-spacing:0.06em; color:#7f849c; margin-top:8px;'>"
                f"Cal+1 (seasonality)</div>"
                f"<div style='font-size:1.4rem; font-weight:600; color:#f9e2af;'>"
                f"{cal1_last:,.2f} EUR/MWh</div>"
                f"<div style='font-size:0.7rem; text-transform:uppercase; "
                f"letter-spacing:0.06em; color:#7f849c; margin-top:8px;'>Spread</div>"
                f"<div style='font-size:1.4rem; font-weight:600; color:{regime_color}'>"
                f"{gap:+.2f} ({regime})</div>"
                f"</div>",
                unsafe_allow_html=True,
            )
        with col_explain:
            st.markdown(f"**{regime} regime**")
            st.write(explanation)
            st.caption(
                ":orange[**Note**: The Cal+1 line is a model-derived projection from "
                "historical DA seasonality, **not a market quote**. Free EEX Cal-Year "
                "settlement isn't accessible without a paid feed. This proxy is useful "
                "for spotting front-vs-back regime shifts but should not be used as "
                "an executable forward price. Full methodology in the Methodology tab.]"
            )

        st.plotly_chart(_chart(de, cal1), width="stretch")
