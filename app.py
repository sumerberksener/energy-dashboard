"""EU Energy Markets — Cross-Commodity Risk Pack.

Interactive view of the same data the CLI produces. Eight primary tiles +
a fundamentals strip + a regime cockpit + an AI desk note + per-metric tabs +
a European Markets tab covering FR / NL / BE / IT / ES on top of the primary
DE and GB views.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from analysis import stats
from analysis.signals import cross_market_tag, signal_for
from config import (
    FUNDAMENTALS_METRICS,
    METRICS,
    STALE_AFTER_DAYS,
    TOP_ROW_METRICS,
)
from data import cache as data_cache
from ui import brief as brief_ui
from ui import cards as cards_ui
from ui import charts as charts_ui
from ui import curve as curve_ui
from ui import markets as markets_ui
from ui import methodology as methodology_ui
from ui import news_panel as news_panel_ui
from ui import regime as regime_ui
from ui import wiki as wiki_ui


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
    label_parts = [f"{len(fresh)}/{n} live"]
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
    return klass, label, " | ".join(tooltip_lines)


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
        "Coal: ICE Newcastle proxy (Yahoo, fundamentals input only) · "
        "DE / GB / FR / NL / BE / IT / ES Power: ENTSO-E Transparency Platform · "
        "EU Storage: GIE AGSI+ · "
        "DE Renewable forecast: ENTSO-E (wind+solar / load) · "
        "News: IEA, EIA, Bruegel, ENTSO-E, Euractiv RSS · "
        "Clean spark/dark computed from the primaries (see Methodology). "
        "Daily granularity, multi-year lookback. "
        "Observations are rule-based and informational, not investment advice."
    )
    st.caption(
        "**Delta colours** — green = bearish power (more supply / more margin); "
        "red = bullish power (cost-push / tight)."
    )


@st.cache_data(ttl=3600, show_spinner=False)
def _ai_narrative(data_signature: str, two_pass: bool):
    from ai.narrative import generate_narrative
    from ai.news_themes import extract_themes
    from data import news as news_module

    data = data_cache.get_all_with_derived()
    try:
        headlines = news_module.fetch_headlines()
        nt = extract_themes(headlines)
        news_dict = {
            "geopolitics_summary": nt.geopolitics_summary,
            "themes": nt.themes,
            "watchlist": nt.watchlist,
        } if (nt.themes or nt.geopolitics_summary) else None
    except Exception:
        nt = None
        news_dict = None

    narrative = generate_narrative(data, two_pass=two_pass, news=news_dict)
    return narrative, nt


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
                "narrative + structured news themes from public RSS feeds. "
                "Two-pass mode runs an extract step then a narrate step grounded only "
                "in the extract — reduces hallucination. Each call is logged to "
                "`ai/logs/<date>.jsonl`. Requires `ANTHROPIC_API_KEY` in "
                "`.streamlit/secrets.toml` or environment."
            )
            return

        with st.spinner("Calling Claude..."):
            sig = "|".join(
                f"{k}:{df.index.max() if df is not None and not df.empty else 'na'}"
                for k, df in data.items()
            )
            narrative, news_themes = _ai_narrative(sig, two_pass)

        if narrative.top_takeaway:
            st.markdown(
                f"<div class='ai-takeaway'>{narrative.top_takeaway}</div>",
                unsafe_allow_html=True,
            )

        if narrative.extract:
            themes = narrative.extract.get("themes", []) or []
            flags = narrative.extract.get("risk_flags", []) or []
            cps = narrative.extract.get("carbon_policy_signal") or None
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
            if isinstance(cps, dict) and cps.get("item"):
                pol = cps.get("polarity", "")
                pol_label = (
                    "bullish EUA" if pol == "bullish-eua"
                    else "bearish EUA" if pol == "bearish-eua"
                    else "neutral"
                )
                st.markdown(
                    f"<div style='border-left: 3px solid #a6e3a1; "
                    f"padding: 8px 14px; margin: 8px 0 12px 0; "
                    f"background: rgba(166, 227, 161, 0.06); border-radius:4px;'>"
                    f"<div style='font-size:0.7rem; text-transform:uppercase; "
                    f"letter-spacing:0.06em; color:#a6e3a1; margin-bottom:4px;'>"
                    f"Carbon supply / policy signal · {cps.get('side','')} · {pol_label}"
                    f"</div>"
                    f"<div style='font-size:0.95rem; font-weight:500; color:#cdd6f4;'>"
                    f"{cps['item']}</div>"
                    f"<div style='font-size:0.78rem; color:#a6adc8; margin-top:4px;'>"
                    f"{cps.get('why_it_matters','')} · "
                    f"<em>source: {cps.get('source','')}</em></div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

        st.write(narrative.text)

        # News themes summary inline
        if news_themes is not None and news_themes.themes:
            st.markdown("**Today's themes (geopolitics + policy)**")
            for t in news_themes.themes[:5]:
                st.markdown(
                    f"- **[{t.get('tag','')} · {t.get('commodity','')} · {t.get('polarity','')}]** "
                    f"{t.get('headline','')} — {t.get('why_it_matters','')}"
                )

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


def _fundamentals_strip(data: dict) -> None:
    """Small horizontal strip showing fundamentals inputs (coal, EUR/USD, etc.)
    below the primary cards — visible but visually demoted.
    """
    if not FUNDAMENTALS_METRICS:
        return
    items = []
    for metric in FUNDAMENTALS_METRICS:
        df = data.get(metric.key)
        if df is None or df.empty:
            items.append(f"<span class='regime-label'>{metric.short_name}</span> "
                         f"<span class='regime-value muted'>—</span>")
            continue
        last = stats.latest(df)
        stale_flag = " ⚠" if stats.is_stale(df, STALE_AFTER_DAYS) else ""
        items.append(
            f"<span class='regime-label'>{metric.short_name}{stale_flag}</span> "
            f"<span class='regime-value muted'>{last:,.2f} {metric.unit}</span>"
        )
    # EUR/USD as another fundamentals input (not a registered Metric)
    fx = data.get("eurusd")
    if fx is not None and not fx.empty:
        items.append(
            f"<span class='regime-label'>EUR/USD</span> "
            f"<span class='regime-value muted'>{stats.latest(fx):.4f}</span>"
        )
    sep = "<span style='color:#45475a; margin: 0 14px'>·</span>"
    st.markdown(
        f"<div style='font-size:0.78rem; padding:8px 0; opacity:0.85;'>"
        f"<span class='regime-label' style='margin-right:10px'>Fundamentals inputs</span>"
        + sep.join(items)
        + "</div>",
        unsafe_allow_html=True,
    )


def _overview_tab(data: dict) -> None:
    """Landing tab — regime strip, cards, fundamentals, AI desk note."""
    # Cross-commodity regime strip — single horizontal cockpit summary.
    regime_ui.render(data)

    # Top row: 8 primary cards (excludes coal — that's a fundamentals input).
    n_per_row = 4
    for row_start in range(0, len(TOP_ROW_METRICS), n_per_row):
        cols = st.columns(n_per_row)
        for col, metric in zip(cols, TOP_ROW_METRICS[row_start:row_start + n_per_row]):
            with col:
                df = data.get(metric.key)
                sig = signal_for(metric.key, df) if df is not None else None
                cards_ui.render(metric, df, sig)

    # Fundamentals inputs strip (coal, EUR/USD)
    _fundamentals_strip(data)

    st.markdown("")

    # Power curve panel (DA vs indicative Cal+1 seasonality projection).
    curve_ui.render(data)

    # AI desk-note pane (numerical synthesis; news lives in its own tab).
    _ai_pane(data)


def _metric_detail_tab(data: dict) -> None:
    """Per-metric drill-down — sub-tabs for TTF, Storage, EUA, etc."""
    metric_tabs = [m.short_name for m in TOP_ROW_METRICS]
    sub_tabs = st.tabs(metric_tabs)

    for sub_tab, metric in zip(sub_tabs, TOP_ROW_METRICS):
        with sub_tab:
            df = data.get(metric.key)
            sig = signal_for(metric.key, df) if df is not None else None

            st.markdown(f"#### {metric.name}")
            st.write(metric.definition)
            st.caption(f"Source: {metric.source}")

            if df is None or df.empty:
                if metric.derived:
                    st.warning(
                        "Derived metric — requires upstream primaries. "
                        "Check ENTSO-E + AGSI+ tokens."
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


def main() -> None:
    _load_css()

    data = data_cache.get_all_with_derived()
    latest_date = max(
        (df.index.max() for df in data.values() if df is not None and not df.empty),
        default=None,
    )

    _header(latest_date, data)

    # Top-level navigation: 6 tabs covering the whole tool surface.
    tabs = st.tabs([
        "Overview",
        "News & Geopolitics",
        "European Markets",
        "Per-Metric Detail",
        "Methodology",
        "How to use (Wiki)",
    ])

    with tabs[0]:
        _overview_tab(data)
    with tabs[1]:
        news_panel_ui.render()
    with tabs[2]:
        markets_ui.render()
    with tabs[3]:
        _metric_detail_tab(data)
    with tabs[4]:
        methodology_ui.render()
    with tabs[5]:
        wiki_ui.render()

    # Sidebar — always visible across all tabs.
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
