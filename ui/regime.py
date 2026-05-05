"""Cross-commodity regime strip: 5 living KPIs that summarise the regime
in one horizontal bar at the top of the dashboard.

Calibrated for Cobblestone's actual book — Power, Gas, Emissions across
European markets, with explicit GB exposure and short-term focus.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from analysis import stats
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

    # 5. Cross-market regime tag
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
