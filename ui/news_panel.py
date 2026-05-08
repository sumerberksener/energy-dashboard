"""News & Geopolitics tab — auto-fetched on page load, cached for an hour.

Doesn't require a button click. Renders today's structured news themes
(headline, tag, commodity, polarity, why-it-matters), the geopolitics
summary, the watchlist, and a faint footer with the source/model audit.

Cached at the dashboard layer so navigation between tabs is instant after
the first fetch. The expensive bit is the Claude theme-extraction call;
RSS fetching is fast.

Also surfaces a "Weather watch" block at the top — detected weather events
(cold snaps / heat domes / wind droughts / storms) with trader-facing
trading implications. Mirrors Cobblestone's named "Energy Meteorologists"
team function: a meteorologist would surface these to the desk in the
same shape — type, region, window, severity, transmission mechanism.
"""
from __future__ import annotations

import streamlit as st

from analysis import weather as weather_analysis
from data import cache as data_cache


@st.cache_data(ttl=3600, show_spinner=False)
def _load_news():
    """Fetch headlines + run Claude theme extraction. Cached 1h."""
    from ai.news_themes import extract_themes
    from data import news as news_module

    try:
        headlines = news_module.fetch_headlines()
    except Exception as e:
        return None, [], str(e)

    if headlines is None or headlines.empty:
        return None, [], "No headlines returned from any RSS feed."

    nt = extract_themes(headlines)
    return nt, headlines.to_dict(orient="records"), None


@st.cache_data(ttl=3600, show_spinner=False)
def _load_weather_events():
    """Pull regional forecasts and run rule-based event detection. Cached 1h."""
    from data import fetchers
    forecasts: dict = {}
    for label in fetchers.WEATHER_LOCATIONS:
        df = data_cache.get_weather_forecast(label)
        if df is not None and not df.empty:
            forecasts[label] = df
    if not forecasts:
        return [], "No weather forecasts available."
    events = weather_analysis.detect_weather_events(forecasts, max_events=4)
    return events, None


_SEVERITY_CHIP = {
    "severe":   ("ai-chip risk", "severe"),
    "moderate": ("ai-chip theme", "moderate"),
    "mild":     ("ai-chip", "mild"),
}

_TYPE_LABEL = {
    "cold_snap":    "Cold snap",
    "heat_dome":    "Heat dome",
    "wind_drought": "Wind drought",
    "storm":        "Storm",
}


def _render_weather_watch() -> None:
    """Render the weather-events watch list above the geopolitics block."""
    events, error = _load_weather_events()
    st.markdown("#### Weather watch — next 7 days")
    st.caption(
        "Rule-based detection from Open-Meteo forecasts at the DE / FR / GB "
        "centroids, compared to a 5-yr seasonal normal. Events are surfaced "
        "with trading implications mapped per region; the desk decides — "
        "this is meteorological pattern recognition, not a recommendation."
    )

    if error:
        st.info(error)
        st.markdown("")
        return

    if not events:
        st.success(
            "No active weather events in the next 7 days — temperatures "
            "and winds are within seasonal norms across DE / FR / GB."
        )
        st.markdown("")
        return

    for ev in events:
        chip_class, sev_label = _SEVERITY_CHIP.get(
            ev.severity, ("ai-chip", ev.severity)
        )
        type_label = _TYPE_LABEL.get(ev.type, ev.type)
        with st.container(border=True):
            cols = st.columns([3, 1])
            with cols[0]:
                st.markdown(
                    f"**{ev.headline}**  \n"
                    f"<span class='ai-chip theme'>{type_label}</span> "
                    f"<span class='ai-chip'>{ev.region}</span> "
                    f"<span class='{chip_class}'>{sev_label}</span> "
                    f"<span class='ai-chip'>{ev.magnitude_label}</span>",
                    unsafe_allow_html=True,
                )
                st.write(ev.trading_implication)
            with cols[1]:
                st.caption("Source: Open-Meteo + 5y archive")
    st.markdown("")


def _polarity_chip_class(polarity: str) -> str:
    p = (polarity or "").lower()
    if "bullish" in p:
        return "ai-chip risk"  # red — bullish power = cost-push for buyers
    if "bearish" in p:
        return "ai-chip theme"  # blue — bearish power = relief
    return "ai-chip"


def render() -> None:
    st.markdown("### News & Geopolitics — desk-relevance filter")
    st.caption(
        "Auto-fetched from public RSS feeds (IEA, EIA, Reuters, Bruegel, Euractiv, "
        "ENTSO-E) every hour. Each headline is run through Claude with a strict "
        "JSON prompt that classifies it by `tag` (policy / supply / demand / weather / "
        "geopolitics / infrastructure / macro), `commodity`, `polarity` (effect on "
        "European power prices), and a one-sentence `why it matters` with the "
        "transmission mechanism. Filter is calibrated to surface anything with a "
        "plausible link to EU power-curve risk."
    )
    st.markdown("")

    # Weather watch first — meteorological events are typically the most
    # actionable short-term driver and deserve top-of-tab placement.
    _render_weather_watch()

    with st.spinner("Fetching news + extracting themes..."):
        nt, raw_headlines, error = _load_news()

    if nt is None:
        st.warning(error or "News pipeline unavailable.")
        return

    # Geopolitics summary at the top
    if nt.geopolitics_summary:
        st.markdown(
            f"<div class='ai-takeaway'>{nt.geopolitics_summary}</div>",
            unsafe_allow_html=True,
        )

    # Themes table
    if nt.themes:
        st.markdown("#### Today's themes")
        for i, t in enumerate(nt.themes, 1):
            with st.container(border=True):
                cols = st.columns([3, 1])
                with cols[0]:
                    polarity = t.get("polarity", "neutral")
                    polarity_label = polarity.replace("-", " ")
                    st.markdown(
                        f"**{i}. {t.get('headline', '—')}**  \n"
                        f"<span class='ai-chip theme'>{t.get('tag', '')}</span> "
                        f"<span class='ai-chip'>{t.get('commodity', '')}</span> "
                        f"<span class='{_polarity_chip_class(polarity)}'>"
                        f"{polarity_label}</span> "
                        f"<span class='ai-chip'>horizon: {t.get('horizon', '')}</span>",
                        unsafe_allow_html=True,
                    )
                    st.write(t.get("why_it_matters", ""))
                with cols[1]:
                    st.caption(f"Source: {t.get('source', '')}")
                    if t.get("link"):
                        st.markdown(f"[Read source]({t['link']})")
    else:
        st.info(
            "No desk-relevant themes today — RSS sources returned items but none "
            "had a plausible link to EU power-curve risk per the filter prompt. "
            "The raw headlines are listed below for reference."
        )

    # Watchlist
    if nt.watchlist:
        st.markdown("#### Watchlist (next 1–4 weeks)")
        for w in nt.watchlist:
            st.markdown(f"- {w}")
        st.markdown("")

    # Raw headlines (always visible — useful even when AI is rate-limited)
    with st.expander(f"Raw headlines (n={len(raw_headlines)})", expanded=False):
        if not raw_headlines:
            st.write("No headlines fetched.")
        else:
            for h in raw_headlines:
                st.markdown(
                    f"- **{h.get('source', '')}** ({h.get('published_at', '')}) — "
                    f"[{h.get('title', '')}]({h.get('link', '')})"
                )
                if h.get("summary"):
                    st.caption(h["summary"][:240])

    # Audit footer
    st.markdown("---")
    if nt.source.startswith("claude"):
        st.caption(
            f"Generated by **{nt.model}** from {nt.n_headlines_in} headlines. "
            f"Prompts/responses logged to `ai/logs/<date>.jsonl`. "
            f"Versioned prompt at `ai/prompts/news_themes_v1.md`."
        )
    elif nt.source == "rule-based":
        st.caption(
            ":orange[News theme extraction unavailable — set `ANTHROPIC_API_KEY` "
            "in `.streamlit/secrets.toml` to enable Claude-driven structuring.]"
        )
    else:
        st.caption(f":orange[{nt.error}]")
