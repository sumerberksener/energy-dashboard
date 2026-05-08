"""Cross-commodity regime strip: 5 living KPIs that summarise the regime
in one horizontal bar at the top of the dashboard.

Calibrated for Cobblestone's actual book — Power, Gas, Emissions across
European markets, with explicit GB exposure and short-term focus.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from analysis import stats, weather as weather_analysis
from analysis.signals import cross_market_tag


def _cell(label: str, value: str, klass: str = "") -> str:
    return (
        f"<div class='regime-cell'>"
        f"<div class='regime-label'>{label}</div>"
        f"<div class='regime-value {klass}'>{value}</div>"
        f"</div>"
    )


def render(data: dict[str, pd.DataFrame]) -> None:
    """Render a horizontal cross-commodity regime strip."""
    cells: list[str] = []

    storage = data.get("storage")
    cs = data.get("clean_spark")
    cd = data.get("clean_dark")
    de_gb = data.get("de_gb_spread")
    rs = data.get("renewable_share")
    de = data.get("de_power")
    cal1 = data.get("de_cal1_proj")
    ttf_jkm = data.get("ttf_jkm_spread")

    # 1. Storage vs seasonal deviation
    if storage is not None and not storage.empty:
        sd = stats.seasonal_deviation_pp(storage)
        if sd is not None:
            klass = "green" if sd > 0 else ("red" if sd < 0 else "")
            cells.append(_cell("Storage vs seasonal", f"{sd:+.1f} pp", klass))
        else:
            cells.append(_cell("Storage vs seasonal", "—", "muted"))
    else:
        cells.append(_cell("Storage vs seasonal", "—", "muted"))

    # 2. Spark − Dark differential
    cs_last = stats.latest(cs) if cs is not None else None
    cd_last = stats.latest(cd) if cd is not None else None
    if cs_last is not None and cd_last is not None:
        diff = cs_last - cd_last
        klass = "green" if diff > 0 else ("red" if diff < 0 else "")
        cells.append(_cell("Spark − Dark", f"{diff:+.1f} EUR/MWh", klass))
    else:
        cells.append(_cell("Spark − Dark", "—", "muted"))

    # 3. DE − GB cross-border spread
    de_gb_last = stats.latest(de_gb) if de_gb is not None else None
    if de_gb_last is not None:
        klass = "red" if de_gb_last > 0 else ("green" if de_gb_last < 0 else "")
        side = "DE prem" if de_gb_last > 0 else ("GB prem" if de_gb_last < 0 else "parity")
        cells.append(_cell("DE − GB", f"{de_gb_last:+.1f} EUR/MWh ({side})", klass))
    else:
        cells.append(_cell("DE − GB", "—", "muted"))

    # 4. Renewable forecast share
    rs_last = stats.latest(rs) if rs is not None else None
    if rs_last is not None:
        # Higher renewables = more supply = green (bearish power)
        # vs typical share — use simple thresholds for color
        if rs_last >= 50:
            klass = "green"
        elif rs_last <= 20:
            klass = "red"
        else:
            klass = ""
        cells.append(_cell("Renewables", f"{rs_last:.0f}% of load", klass))
    else:
        cells.append(_cell("Renewables", "—", "muted"))

    # 5. DA vs implied Cal+1 (seasonality projection — NOT a market quote)
    de_last = stats.latest(de) if de is not None else None
    cal1_last = stats.latest(cal1) if cal1 is not None else None
    if de_last is not None and cal1_last is not None:
        gap = de_last - cal1_last
        # gap > 0: DA above seasonal year-ahead → backwardation regime (front strong)
        # gap < 0: DA below seasonal year-ahead → contango regime (back strong)
        klass = "red" if gap > 0 else ("green" if gap < 0 else "")
        regime = "backwardation" if gap > 0 else ("contango" if gap < 0 else "flat")
        cells.append(_cell(
            "DA − Cal+1 (model)", f"{gap:+.1f} EUR/MWh ({regime})", klass
        ))
    else:
        cells.append(_cell("DA − Cal+1 (model)", "—", "muted"))

    # 6. TTF − JKM spread — Europe-vs-Asia LNG arbitrage signal.
    # Auxiliary chip; honest about being LNG-side coverage of the gas book.
    ttf_jkm_last = stats.latest(ttf_jkm) if ttf_jkm is not None else None
    if ttf_jkm_last is not None:
        klass = "green" if ttf_jkm_last > 0 else ("red" if ttf_jkm_last < 0 else "")
        side = "TTF rich" if ttf_jkm_last > 0 else (
            "JKM rich" if ttf_jkm_last < 0 else "parity"
        )
        cells.append(_cell(
            "TTF − JKM (LNG)", f"{ttf_jkm_last:+.1f} EUR/MWh ({side})", klass
        ))
    else:
        cells.append(_cell("TTF − JKM (LNG)", "—", "muted"))

    # 7. Cross-border (Power) — Cobblestone's "Power Transportation" pillar.
    # Pick the largest-magnitude corridor of the three (DE-FR / GB-FR / NL-DE)
    # and surface its net direction + magnitude. Single chip, full triplet
    # is a tooltip if the user hovers (Streamlit's basic chip doesn't
    # support tooltips natively, so we put the triplet in the value text).
    corridors = [
        ("DE→FR", data.get("flow_de_fr")),
        ("GB→FR", data.get("flow_gb_fr")),
        ("NL→DE", data.get("flow_nl_de")),
    ]
    triplet_parts: list[str] = []
    largest_label, largest_val = None, None
    for label, df in corridors:
        v = stats.latest(df) if df is not None else None
        if v is None or pd.isna(v):
            continue
        # Convert MWh/day → GWh for chip readability.
        gwh = v / 1000.0
        triplet_parts.append(f"{label} {gwh:+.1f}")
        if largest_val is None or abs(gwh) > abs(largest_val):
            largest_label, largest_val = label, gwh
    if largest_val is not None:
        # Direction colour: green for DE/NL exporting (continental supply
        # spilling west/north), red for GB pulling in (UK premium / scarcity).
        if largest_label == "GB→FR":
            klass = "red" if largest_val < 0 else ""
        else:
            klass = "green" if largest_val > 0 else "red"
        cells.append(_cell(
            "Cross-border (Power)",
            " · ".join(triplet_parts) + " GWh",
            klass,
        ))
    else:
        cells.append(_cell("Cross-border (Power)", "—", "muted"))

    # 8. Weather (5d anomaly) — Cobblestone's "Energy Meteorologists" function.
    # Mean 5-day forward temperature anomaly at DE / FR / GB centroids.
    # Cold anomaly = red (heating-demand bullish for power & gas);
    # warm anomaly = green (bearish for thermal call); both >|2°C| = active.
    forecasts = {
        "DE": data.get("weather_de"),
        "FR": data.get("weather_fr"),
        "GB": data.get("weather_gb"),
    }
    anomaly = weather_analysis.summarise_anomaly(
        {k: v for k, v in forecasts.items() if v is not None and not v.empty}
    )
    if anomaly:
        triplet = " / ".join(f"{r} {a:+.1f}" for r, a in anomaly.items())
        # Pick dominant region by magnitude for the colour cue.
        dominant_region = max(anomaly, key=lambda r: abs(anomaly[r]))
        dominant = anomaly[dominant_region]
        klass = "red" if dominant < -1 else ("green" if dominant > 1 else "")
        cells.append(_cell(
            "Weather (5d anom)", f"{triplet} °C", klass
        ))
    else:
        cells.append(_cell("Weather (5d anom)", "—", "muted"))

    # 9. Cross-market regime tag
    tag = cross_market_tag(data)
    if tag:
        short = tag.split(":")[0]
        cells.append(_cell("Regime", short))
    else:
        cells.append(_cell("Regime", "Neutral", "muted"))

    st.markdown(
        f"<div class='regime-strip'>{''.join(cells)}</div>",
        unsafe_allow_html=True,
    )
