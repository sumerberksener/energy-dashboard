"""Sidebar morning-brief panel."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from analysis.signals import cross_market_tag, morning_brief


def render(data: dict[str, pd.DataFrame]) -> None:
    st.markdown("### Morning brief")
    st.write(morning_brief(data))

    tag = cross_market_tag(data)
    if tag:
        st.info(tag)

    st.markdown("---")
    st.markdown("### Data freshness")
    for key, df in data.items():
        if df is None or df.empty:
            st.markdown(f"- **{key}**: :red[no data]")
            continue
        latest = df.index.max()
        stale = df.attrs.get("is_stale", False)
        badge = ":orange[snapshot]" if stale else ":green[live]"
        st.markdown(f"- **{key}**: {latest:%Y-%m-%d} · {badge}")
