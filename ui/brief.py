"""Sidebar morning-brief panel."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from analysis.signals import cross_market_tag, morning_brief
from config import METRICS_BY_KEY


def render(data: dict[str, pd.DataFrame]) -> None:
    st.markdown("### Morning brief")
    st.write(morning_brief(data))

    tag = cross_market_tag(data)
    if tag:
        st.info(tag)

    st.markdown("---")
    st.markdown("### Data freshness")
    # Only show registered primary metrics — auxiliary derived series
    # (switching_ttf, de_gb_spread, eurusd, etc.) are internal helpers.
    for key, df in data.items():
        if key not in METRICS_BY_KEY:
            continue
        meta = METRICS_BY_KEY[key]
        if df is None or df.empty:
            st.markdown(f"- **{meta.short_name}**: :red[no data]")
            continue
        latest = df.index.max()
        stale = df.attrs.get("is_stale", False)
        badge = ":orange[snapshot]" if stale else ":green[live]"
        st.markdown(f"- **{meta.short_name}**: {latest:%Y-%m-%d} · {badge}")
