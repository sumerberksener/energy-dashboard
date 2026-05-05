"""EU Energy Markets — Cross-Commodity Risk Pack.

Interactive view of the same data the CLI (scripts/generate_brief.py) produces:
eight metrics framed around the gas + carbon → power-curve thesis, a regime
strip with cross-commodity KPIs, and an on-demand AI-generated desk note
grounded in the structured snapshot.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from analysis import stats
from analysis.signals import cross_market_tag, signal_for
from config import METRICS, STALE_AFTER_DAYS
from data import cache as data_cache
from ui import brief as brief_ui
from ui import cards as cards_ui
from ui import charts as charts_ui
from ui import methodology as methodology_ui
from ui import regime as regime_ui


st.set_page_config(
    page_title="EU Energy — Cross-Commodity Risk Pack",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)


def _load_css() -> None:
    css_path = Path(__file__).parent / "ui" / "style.css"
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text()}</style>", unsafe_allow_html=True)


def _freshness_summary(data: dict) -> tuple[str, str, str]:
    """Returns (klass, label, tooltip) for the header status pill."""
    fresh, stale, missing = [], [], []
    for metric in METRICS:
        df = data.get(metric.key)
        if df is None or df.empty:
            missing.append(metric.short_name)
        elif stats.is_stale(df, STALE_AFTER_DAYS):
            d = stats.days_since_latest(df)
            stale.append(f"{metric.short_name} ({d}d old)")
        else:
            fresh.append(metric.short_name)

    n = len(METRICS)
    label_parts = []
    label_parts.append(f"{len(fresh)}/{n} live")
    if stale:
        label_parts.append(f"{len(stale)} stale")
    if missing:
        label_parts.append(f"{len(missing)} missing")
    label = " · ".join(label_parts)

    if missing:
        klass = "status-pill-red"
    elif stale:
        klass = "status-pill-amber"
    else:
        klass = "status-pill-green"

    tooltip_lines = []
    if fresh:
        tooltip_lines.append("Live: " + ", ".join(fresh))
    if stale:
        tooltip_lines.append("Stale: " + "; ".join(stale))
    if missing:
        tooltip_lines.append("Missing: " + ", ".join(missing))
    tooltip = " | ".join(tooltip_lines)
    return klass, label, tooltip


def _header(latest_date, data: dict) -> None:
    left, right = st.columns([4, 1.5])
    with left:
        st.title("EU Energy — Cross-Commodity Risk Pack")
        st.caption("Gas + Carbon → Power Curve Implications")
        if latest_date is not None:
            st.caption(f"As of {latest_date:%A, %d %B %Y}")
    with right:
        st.write("")
        klass, label, tooltip = _freshness_summary(data)
        st.markdown(
            f"<div title='{tooltip}' style='text-align:right; margin-top:8px'>"
            f"<span class='status-pill {klass}'>{label}</span></div>",
            unsafe_allow_html=True,
        )
        st.write("")
        if st.button("Refresh data", width="stretch"):
            data_cache.clear_cache()
            st.rerun()


def _footer() -> None:
    st.markdown("---")
    st.caption(
        "**Sources** — TTF & EUA: Yahoo Finance / stooq · "
        "Coal: ICE Newcastle proxy (Yahoo) · "
        "DE Power: ENTSO-E Transparency Platform · "
        "EU Storage: GIE AGSI+ · "
        "Clean spark/dark/switching TTF computed from the primaries (see Methodology). "
        "Daily granularity, 5-year lookback. "
        "Observations are rule-based and informational, not investment advice."
    )
    st.caption(
        "**Delta colours** — green = bearish power (more supply / more margin); "
        "red = bullish power (cost-push / tight)."
    )


@st.cache_data(ttl=3600, show_spinner=False)
def _ai_narrative(data_signature: str, two_pass: bool):
    from ai.narrative import generate_narrative
    data = data_cache.get_all_with_derived()
    return generate_narrative(data, two_pass=two_pass)


def _ai_pane(data: dict) -> None:
    with st.expander("AI Desk Note (Anthropic Claude)", expanded=True):
        col_btn, col_mode = st.columns([1, 1])
        with col_btn:
            generate = st.button("Generate desk note", key="gen_ai", width="stretch")
        with col_mode:
            two_pass = st.toggle("Two-pass (extract → narrate)", value=True, key="ai_two_pass")

        if not generate:
            st.caption(
                "Click to call Claude (Haiku 4.5) and produce a metrics-grounded "
                "narrative. Two-pass mode runs an extract step (themes, risk flags, "
                "top takeaway) then a narrate step using only the extract — reduces "
                "hallucination. Single-pass is one shot. Each call is logged to "
                "`ai/logs/<date>.jsonl`. Requires `ANTHROPIC_API_KEY` in "
                "`.streamlit/secrets.toml` or environment."
            )
            return

        with st.spinner("Calling Claude..."):
            sig = "|".join(
                f"{k}:{df.index.max() if df is not None and not df.empty else 'na'}"
                for k, df in data.items()
            )
            narrative = _ai_narrative(sig, two_pass)

        # Hero takeaway
        if narrative.top_takeaway:
            st.markdown(
                f"<div class='ai-takeaway'>{narrative.top_takeaway}</div>",
                unsafe_allow_html=True,
            )

        # Themes + risk flags
        if narrative.extract:
            themes = narrative.extract.get("themes", []) or []
            flags = narrative.extract.get("risk_flags", []) or []
            if themes:
                chips = "".join(
                    f"<span class='ai-chip theme'>{t}</span>" for t in themes
                )
                st.markdown(f"<div class='ai-chips'>{chips}</div>",
                            unsafe_allow_html=True)
            if flags:
                chips = "".join(
                    f"<span class='ai-chip risk'>{f}</span>" for f in flags
                )
                st.markdown(f"<div class='ai-chips'>{chips}</div>",
                            unsafe_allow_html=True)

        # Narrative body
        st.write(narrative.text)

        # Audit footer
        if narrative.source.startswith("claude"):
            mode = "two-pass" if narrative.source == "claude-two-pass" else "single-pass"
            st.caption(
                f"Model: {narrative.model} · {mode} · "
                f"narrate log: `{narrative.log_path}`"
                + (f" · extract log: `{narrative.extract_log_path}`"
                   if narrative.extract_log_path else "")
            )
        else:
            st.caption(
                f":orange[{narrative.error or 'Rule-based fallback. Set ANTHROPIC_API_KEY to enable Claude.'}]"
            )


def main() -> None:
    _load_css()

    data = data_cache.get_all_with_derived()
    latest_date = max(
        (df.index.max() for df in data.values() if df is not None and not df.empty),
        default=None,
    )

    _header(latest_date, data)

    # Cross-commodity regime strip — single horizontal cockpit summary.
    regime_ui.render(data)

    # Top row: metric cards (8 metrics fits in 2 rows of 4 nicely on wide layout)
    n_per_row = 4
    for row_start in range(0, len(METRICS), n_per_row):
        cols = st.columns(n_per_row)
        for col, metric in zip(cols, METRICS[row_start:row_start + n_per_row]):
            with col:
                df = data.get(metric.key)
                sig = signal_for(metric.key, df) if df is not None else None
                cards_ui.render(metric, df, sig)

    st.markdown("")

    # AI desk-note pane.
    _ai_pane(data)

    # Body: one tab per metric + a final Methodology tab.
    tab_labels = [m.short_name for m in METRICS] + ["Methodology"]
    tabs = st.tabs(tab_labels)

    for tab, metric in zip(tabs[:-1], METRICS):
        with tab:
            df = data.get(metric.key)
            sig = signal_for(metric.key, df) if df is not None else None

            st.markdown(f"#### {metric.name}")
            st.write(metric.definition)
            st.caption(f"Source: {metric.source}")

            if df is None or df.empty:
                if metric.derived:
                    st.warning(
                        "Derived metric — requires DE Power and EUA "
                        "(plus Coal for clean dark / switching TTF). "
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
                    f":orange[Live fetch failed; showing cached snapshot. "
                    f"Error: {df.attrs.get('error', 'unknown')}]"
                )
            if stats.is_stale(df, STALE_AFTER_DAYS):
                st.caption(
                    f":orange[STALE — last data point is "
                    f"{df.index.max():%Y-%m-%d} "
                    f"({stats.days_since_latest(df)} days old)]"
                )

    # Methodology tab (last)
    with tabs[-1]:
        methodology_ui.render()

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
