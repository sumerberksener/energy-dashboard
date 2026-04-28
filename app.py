"""EU Energy Markets — Cross-Commodity Risk Pack.

Interactive view of the same data the CLI (scripts/generate_brief.py) produces:
seven metrics framed around the gas + carbon → power-curve thesis, plus an
on-demand AI-generated desk note grounded in the structured snapshot.
"""
from __future__ import annotations

import streamlit as st

from analysis.signals import cross_market_tag, signal_for
from config import METRICS
from data import cache as data_cache
from ui import brief as brief_ui
from ui import cards as cards_ui
from ui import charts as charts_ui


st.set_page_config(
    page_title="EU Energy — Cross-Commodity Risk Pack",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _header(latest_date) -> None:
    left, right = st.columns([5, 1])
    with left:
        st.title("⚡ EU Energy — Cross-Commodity Risk Pack")
        st.caption("Gas + Carbon → Power Curve Implications")
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
        "**Sources** — TTF & EUA: Yahoo Finance / stooq · "
        "Coal: ICE Newcastle proxy (Yahoo) · "
        "DE Power: ENTSO-E Transparency Platform · "
        "EU Storage: GIE AGSI+ · "
        "Clean spark/dark spreads computed from the primaries (see config.py). "
        "Daily granularity, 5-year lookback. "
        "Observations are rule-based and informational, not investment advice."
    )


@st.cache_data(ttl=3600, show_spinner=False)
def _ai_narrative(data_signature: str):
    """Cache the AI call by the signature of the input data."""
    from ai.narrative import generate_narrative
    data = data_cache.get_all_with_derived()
    return generate_narrative(data)


def main() -> None:
    data = data_cache.get_all_with_derived()
    latest_date = max(
        (df.index.max() for df in data.values() if df is not None and not df.empty),
        default=None,
    )

    _header(latest_date)

    # Top row: 7 cards (4 prices + 1 fundamental + 2 derived spreads).
    cols = st.columns(len(METRICS))
    for col, metric in zip(cols, METRICS):
        with col:
            df = data.get(metric.key)
            sig = signal_for(metric.key, df) if df is not None else None
            cards_ui.render(metric, df, sig)

    st.markdown("")

    # AI desk note pane.
    with st.expander("🧠 AI Desk Note (Anthropic Claude)", expanded=True):
        if st.button("Generate desk note", key="gen_ai"):
            with st.spinner("Calling Claude..."):
                signature = "|".join(
                    f"{k}:{df.index.max() if df is not None and not df.empty else 'na'}"
                    for k, df in data.items()
                )
                narrative = _ai_narrative(signature)
            st.write(narrative.text)
            if narrative.source == "claude":
                st.caption(f"Model: {narrative.model} · log: `{narrative.log_path}`")
            else:
                st.caption(
                    f":orange[Rule-based fallback. {narrative.error or 'Set ANTHROPIC_API_KEY to enable Claude.'}]"
                )
        else:
            st.caption(
                "Click to call Claude (Haiku 4.5) and produce a 3–5 sentence trader-grade "
                "narrative grounded in the metrics snapshot. Requires `ANTHROPIC_API_KEY` "
                "in `.streamlit/secrets.toml` or environment. Each call is logged to "
                "`ai/logs/<date>.jsonl`."
            )

    # Body: one tab per metric.
    tabs = st.tabs([m.short_name for m in METRICS])
    for tab, metric in zip(tabs, METRICS):
        with tab:
            df = data.get(metric.key)
            sig = signal_for(metric.key, df) if df is not None else None

            st.markdown(f"#### {metric.name}")
            st.write(metric.definition)
            st.caption(f"Source: {metric.source}")

            if df is None or df.empty:
                if metric.derived:
                    st.warning(
                        "Derived metric — requires DE Power and EUA (and Coal for clean dark). "
                        "Check that ENTSO-E and AGSI+ tokens are set."
                    )
                else:
                    st.warning(
                        "No data available. Check that API tokens are set in "
                        ".streamlit/secrets.toml (or Streamlit Cloud's Secrets UI)."
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
            st.write(sig.observation if sig else "—")
            if df.attrs.get("is_stale"):
                st.caption(
                    f":orange[⚠ Live fetch failed; showing cached snapshot. "
                    f"Error: {df.attrs.get('error', 'unknown')}]"
                )

    # Sidebar.
    with st.sidebar:
        brief_ui.render(data)
        tag = cross_market_tag(data)
        if tag:
            st.markdown("---")
            st.markdown("**Cross-market tag**")
            st.info(tag)

    _footer()


if __name__ == "__main__":
    main()
