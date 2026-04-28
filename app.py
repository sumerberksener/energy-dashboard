"""EU Energy Markets — Morning Brief.

A 5-minute morning briefing for an energy trader: today's prints on the five
most-watched EU energy metrics, 5-year history, and rule-based observations.
"""
from __future__ import annotations

import streamlit as st

from analysis.signals import signal_for
from config import METRICS, METRICS_BY_KEY
from data import cache as data_cache
from ui import brief as brief_ui
from ui import cards as cards_ui
from ui import charts as charts_ui


st.set_page_config(
    page_title="EU Energy — Morning Brief",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _header(latest_date) -> None:
    left, right = st.columns([5, 1])
    with left:
        st.title("⚡ EU Energy Markets — Morning Brief")
        if latest_date is not None:
            st.caption(f"As of {latest_date:%A, %d %B %Y}")
    with right:
        st.write("")
        if st.button("🔄 Refresh", width="stretch"):
            data_cache.clear_cache()
            st.rerun()


def _footer() -> None:
    st.markdown("---")
    st.caption(
        "**Sources** — TTF & Brent: Yahoo Finance / stooq · "
        "EUA: stooq / KraneShares KRBN proxy · "
        "DE Power: ENTSO-E Transparency Platform · "
        "EU Storage: GIE AGSI+. "
        "Daily granularity, 5-year lookback. "
        "Observations are rule-based and informational, not investment advice."
    )


def main() -> None:
    data = data_cache.get_all()
    latest_date = max(
        (df.index.max() for df in data.values() if df is not None and not df.empty),
        default=None,
    )

    _header(latest_date)

    # Top row: 5 cards.
    cols = st.columns(5)
    for col, metric in zip(cols, METRICS):
        with col:
            df = data[metric.key]
            sig = signal_for(metric.key, df)
            cards_ui.render(metric, df, sig)

    st.markdown("")

    # Body: one tab per metric.
    tabs = st.tabs([m.short_name for m in METRICS])
    for tab, metric in zip(tabs, METRICS):
        with tab:
            df = data[metric.key]
            sig = signal_for(metric.key, df)

            st.markdown(f"#### {metric.name}")
            st.write(metric.definition)
            st.caption(f"Source: {metric.source}")

            if df is None or df.empty:
                st.warning(
                    "No data available. Check that API tokens are set in "
                    ".streamlit/secrets.toml (or in Streamlit Cloud's Secrets UI)."
                )
                continue

            chart_col, table_col = st.columns([3, 1])
            with chart_col:
                st.plotly_chart(
                    charts_ui.five_year_chart(metric, df),
                    width="stretch",
                )
            with table_col:
                st.markdown("**Stats**")
                st.dataframe(charts_ui.stats_table(df, metric), width="stretch")

            st.markdown("**Observation**")
            st.write(sig.observation)
            if df.attrs.get("is_stale"):
                st.caption(
                    f":orange[⚠ Live fetch failed; showing cached snapshot. "
                    f"Error: {df.attrs.get('error', 'unknown')}]"
                )

    # Sidebar.
    with st.sidebar:
        brief_ui.render(data)

    _footer()


if __name__ == "__main__":
    main()
