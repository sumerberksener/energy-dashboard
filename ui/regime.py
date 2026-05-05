"""Cross-commodity regime strip: 4–5 living KPIs that summarise the regime
in one horizontal bar at the top of the dashboard.
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

    ttf = data.get("ttf")
    sw = data.get("switching_ttf")
    cs = data.get("clean_spark")
    cd = data.get("clean_dark")
    storage = data.get("storage")

    # 1. Switching TTF
    sw_last = stats.latest(sw) if sw is not None else None
    if sw_last is not None:
        cells.append(_cell("Switching TTF", f"{sw_last:.1f} EUR/MWh"))
    else:
        cells.append(_cell("Switching TTF", "—", "muted"))

    # 2. TTF gap vs switching TTF
    ttf_last = stats.latest(ttf) if ttf is not None else None
    if ttf_last is not None and sw_last is not None:
        gap = ttf_last - sw_last
        klass = "green" if gap < 0 else ("red" if gap > 0 else "")
        cells.append(_cell("TTF − Switch TTF", f"{gap:+.1f} EUR/MWh", klass))
    else:
        cells.append(_cell("TTF − Switch TTF", "—", "muted"))

    # 3. Clean spark vs clean dark differential
    cs_last = stats.latest(cs) if cs is not None else None
    cd_last = stats.latest(cd) if cd is not None else None
    if cs_last is not None and cd_last is not None:
        diff = cs_last - cd_last
        klass = "green" if diff > 0 else ("red" if diff < 0 else "")
        cells.append(_cell("Spark − Dark", f"{diff:+.1f} EUR/MWh", klass))
    else:
        cells.append(_cell("Spark − Dark", "—", "muted"))

    # 4. Storage vs seasonal deviation
    if storage is not None and not storage.empty:
        sd = stats.seasonal_deviation_pp(storage)
        if sd is not None:
            klass = "green" if sd > 0 else ("red" if sd < 0 else "")
            cells.append(_cell("Storage vs seasonal", f"{sd:+.1f} pp", klass))
        else:
            cells.append(_cell("Storage vs seasonal", "—", "muted"))
    else:
        cells.append(_cell("Storage vs seasonal", "—", "muted"))

    # 5. Cross-market regime tag
    tag = cross_market_tag(data)
    if tag:
        # Trim to fit; keep the lead clause
        short = tag.split(":")[0]
        cells.append(_cell("Regime", short))
    else:
        cells.append(_cell("Regime", "Neutral", "muted"))

    st.markdown(
        f"<div class='regime-strip'>{''.join(cells)}</div>",
        unsafe_allow_html=True,
    )
