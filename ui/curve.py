"""Power curve panel — DA price vs an indicative seasonality-based curve.

This panel is the brief's "Day-Ahead → curve" output and the dashboard's
"week ahead to several years ahead" surface (the language Cobblestone's
Trading Markets page uses). We don't have free access to EEX settlement
curves, so every forward point on this panel is a **seasonality-based
projection** computed from historical DA realisations, NOT a market quote.
The panel is honest about that on screen, in the tooltip, and in the
methodology tab.

The Cal+1 line carries the existing regime read (DA vs Cal+1 spread). The
multi-tenor "Curve strip" extends that to W+1 / M+1 / Q+1 / Cal+1 / Cal+2
so the curve *shape* is visible, not just one point.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analysis import stats


# Multi-tenor strip ordering. Each tuple = (label, data-dict key, css-friendly tag).
CURVE_STRIP_TENORS: list[tuple[str, str, str]] = [
    ("DA",     "de_power",     "da"),
    ("W+1",    "de_w1_proj",   "w1"),
    ("M+1",    "de_m1_proj",   "m1"),
    ("Q+1",    "de_q1_proj",   "q1"),
    ("Cal+1",  "de_cal1_proj", "cal1"),
    ("Cal+2",  "de_cal2_proj", "cal2"),
]


def classify_curve_regime(da: float, points: list[tuple[str, float]]) -> str:
    """Classify the curve shape across the multi-tenor strip.

    `points` is the list of (label, level) tuples for the forward tenors only
    (DA excluded). Threshold is 1 EUR/MWh — anything tighter reads as flat.
    Returns one of: "Backwardated front, contango back", "Steep backwardation",
    "Backwardation", "Contango", "Steep contango", "Flat", or one of the mixed
    shapes that the desk-note sentence carries.
    """
    if not points:
        return "Flat"
    front_labels = {"W+1", "M+1"}
    back_labels = {"Cal+1", "Cal+2"}

    front_spreads = [da - lv for lab, lv in points if lab in front_labels]
    back_spreads = [da - lv for lab, lv in points if lab in back_labels]
    front = sum(front_spreads) / len(front_spreads) if front_spreads else 0.0
    back = sum(back_spreads) / len(back_spreads) if back_spreads else 0.0

    if all(da - lv > 1 for _, lv in points):
        spread_range = max(da - lv for _, lv in points) - min(da - lv for _, lv in points)
        return "Steep backwardation" if spread_range > 15 else "Backwardation"
    if all(da - lv < -1 for _, lv in points):
        spread_range = max(lv - da for _, lv in points) - min(lv - da for _, lv in points)
        return "Steep contango" if spread_range > 15 else "Contango"

    backw_front, cont_front = front > 1, front < -1
    backw_back, cont_back = back > 1, back < -1

    if backw_front and cont_back:
        return "Backwardated front, contango back"
    if cont_front and backw_back:
        return "Contango front, backwardated back"
    if backw_front:
        return "Backwardated front, flat back"
    if cont_front:
        return "Contango front, flat back"
    if backw_back:
        return "Flat front, backwardated back"
    if cont_back:
        return "Flat front, contango back"
    return "Flat"


def collect_strip_points(data: dict[str, pd.DataFrame]) -> tuple[float | None, list[tuple[str, float]]]:
    """Return (da_level, [(tenor, level), ...]) for tenors with data available.

    Pure-pandas helper used by both the UI strip and the desk-note generator
    so they stay in sync. Tenors missing from `data` (or with empty frames)
    are silently dropped — caller handles a None/empty result by skipping
    the strip render.
    """
    da_df = data.get("de_power")
    da_level = stats.latest(da_df) if da_df is not None and not da_df.empty else None

    points: list[tuple[str, float]] = []
    for label, key, _tag in CURVE_STRIP_TENORS:
        if label == "DA":
            continue
        df = data.get(key)
        if df is None or df.empty:
            continue
        lv = stats.latest(df)
        if lv is None:
            continue
        points.append((label, float(lv)))
    return da_level, points


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


def _render_strip(data: dict[str, pd.DataFrame]) -> None:
    """Multi-tenor curve strip — DA / W+1 / M+1 / Q+1 / Cal+1 / Cal+2 chips.

    Each chip shows the tenor's level and its spread vs DA. Renders inline
    on the Overview tab above the existing DA-vs-Cal+1 panel so the trader
    sees curve shape at a glance before drilling into the regime read.
    """
    da_level, points = collect_strip_points(data)
    if da_level is None or not points:
        return

    regime = classify_curve_regime(da_level, points)

    chip_html: list[str] = []
    # DA chip — the anchor.
    chip_html.append(
        "<div style='flex:1; min-width:90px; padding:8px 10px; background:#181825; "
        "border-radius:8px; border:1px solid rgba(137,180,250,0.32); text-align:center;'>"
        "<div style='font-size:0.65rem; text-transform:uppercase; letter-spacing:0.06em; "
        "color:#7f849c'>DA</div>"
        f"<div style='font-size:1.05rem; font-weight:600; color:#cdd6f4;'>{da_level:,.1f}</div>"
        "<div style='font-size:0.6rem; color:#7f849c;'>anchor</div>"
        "</div>"
    )
    for label, level in points:
        spread = da_level - level
        if abs(spread) < 1:
            color = "#cdd6f4"
        elif spread > 0:
            color = "#f9e2af"  # DA above forward → backwardated leg
        else:
            color = "#a6e3a1"  # DA below forward → contango leg
        chip_html.append(
            f"<div style='flex:1; min-width:90px; padding:8px 10px; background:#181825; "
            f"border-radius:8px; border:1px solid rgba(137,180,250,0.18); text-align:center;'>"
            f"<div style='font-size:0.65rem; text-transform:uppercase; letter-spacing:0.06em; "
            f"color:#7f849c'>{label}</div>"
            f"<div style='font-size:1.05rem; font-weight:600; color:#cdd6f4;'>{level:,.1f}</div>"
            f"<div style='font-size:0.65rem; color:{color};'>{spread:+.1f} vs DA</div>"
            f"</div>"
        )

    st.markdown(
        f"<div style='margin:6px 0 4px 0; font-size:0.78rem; color:#bac2de;'>"
        f"<b>Curve shape</b> — model-derived seasonality projections, EUR/MWh "
        f"(<i>not market quotes</i>) · <b>{regime}</b>"
        f"</div>"
        f"<div style='display:flex; gap:6px; flex-wrap:wrap; margin-bottom:14px;'>"
        f"{''.join(chip_html)}"
        f"</div>",
        unsafe_allow_html=True,
    )


def render(data: dict[str, pd.DataFrame]) -> None:
    """Render the Power Curve panel — multi-tenor strip + KPIs + chart."""
    _render_strip(data)

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
