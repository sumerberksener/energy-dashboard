"""Methodology tab content — surfaces the per-metric definitions, the
signal logic, and the spread/switching formulas in one place.
"""
from __future__ import annotations

import streamlit as st

from config import (
    COAL_CALORIFIC_MWH_PER_T,
    COAL_EFFICIENCY,
    COAL_EMISSION_FACTOR,
    GAS_EFFICIENCY,
    GAS_EMISSION_FACTOR,
    METRICS,
    PERCENTILE_HIGH,
    PERCENTILE_LOW,
    SIGMA_EXTENDED,
    STALE_AFTER_DAYS,
    ZSCORE_OUTSIZED,
)


def render() -> None:
    st.markdown("### Cross-commodity thesis")
    st.write(
        "European power-curve risk is set by **gas tightness** (TTF level + EU storage), "
        "**carbon level** (EUA), and the **clean-spread regime** that ties them together. "
        "When the clean spark exceeds the clean dark, gas is the marginal European fuel and "
        "TTF moves transmit directly into the power curve. When dark dominates, coal+carbon "
        "shocks set the regime instead. Storage trajectory vs the 5-yr seasonal average "
        "tells you whether the gas-side risk is symmetric or skewed."
    )

    st.markdown("### Metrics tracked")
    for metric in METRICS:
        with st.expander(f"{metric.short_name} — {metric.name}", expanded=False):
            st.write(metric.definition)
            st.caption(f"Source: {metric.source} · Unit: {metric.unit}")

    st.markdown("### Plant assumptions (clean spark / clean dark / switching TTF)")
    st.markdown(
        f"- **Gas (CCGT)**: η = {GAS_EFFICIENCY:.2f}, "
        f"emission factor = {GAS_EMISSION_FACTOR} tCO₂/MWh thermal\n"
        f"- **Hard coal plant**: η = {COAL_EFFICIENCY:.2f}, "
        f"emission factor = {COAL_EMISSION_FACTOR} tCO₂/MWh thermal, "
        f"calorific value = {COAL_CALORIFIC_MWH_PER_T:.3f} MWh/t"
    )
    st.markdown("**Formulas**")
    st.code(
        "Clean Spark    = Power − Gas/η_gas − Carbon × (EF_gas / η_gas)\n"
        "Clean Dark     = Power − Coal_EUR/η_coal − Carbon × (EF_coal / η_coal)\n"
        "Switching TTF  = η_gas · ( Coal_EUR/η_coal "
        "+ (EF_coal/η_coal − EF_gas/η_gas) · EUA )\n\n"
        "Coal_EUR per MWh thermal = (Coal_USD/t / EURUSD) / 6.978",
        language="text",
    )

    st.markdown("### Indicative Cal+1 power (seasonality projection)")
    st.markdown(
        "Free daily EEX Cal-Year settlement is not accessible without a paid "
        "feed (Bloomberg, Refinitiv, ICE Endex direct). The dashboard's Cal+1 "
        "line is **a model-derived seasonality projection, not a market quote**. "
        "Method: for each historical date, find the realised DA price exactly "
        "1 year later (with a ±3-day window) and report the rolling 30-day mean "
        "of those forward realisations. The DA − Cal+1 spread reads as a "
        "front-vs-back regime indicator (backwardation vs contango). Caveats: "
        "backward-looking, mean-reverting, doesn't price in current expectations "
        "of carbon / weather / demand — a real Cal+1 quote does. Replace with "
        "EEX settlement when a paid feed is available."
    )

    st.markdown("### Rule-based signal thresholds")
    st.markdown(
        f"- **Percentile rank (5y)**: ≥ {PERCENTILE_HIGH} → 'historically high'; "
        f"≤ {PERCENTILE_LOW} → 'historically low'\n"
        f"- **Extension from 50d MA**: |σ| ≥ {SIGMA_EXTENDED} → 'extended above/below trend'\n"
        f"- **Daily-move z-score (vs 60d)**: |z| ≥ {ZSCORE_OUTSIZED} → 'outsized move'\n"
        f"- **Storage seasonal deviation**: pp difference vs same-day historical mean\n"
        f"- **Data freshness**: > {STALE_AFTER_DAYS} days old triggers a STALE flag"
    )

    st.markdown("### AI workflow")
    st.markdown(
        "Two-pass design: **(1) extract** — Claude returns strict JSON "
        "(themes, risk flags, watchlist, top takeaway) grounded in the metric "
        "snapshot. **(2) narrate** — a second Claude pass writes 3–5 sentence "
        "prose using *only* the extract JSON. Reduces hallucination; produces "
        "structured artefacts that are reusable in the dashboard. Every call is "
        "logged to `ai/logs/<date>.jsonl` with prompt SHA, full text, token usage, "
        "and latency. Falls back to a deterministic rule-based string when the "
        "API key is missing or a call fails — pipeline always emits output."
    )

    st.markdown("### Weather event detection (rule-based, not AI)")
    st.markdown(
        "The News tab's **Weather watch** is rule-based pattern recognition on "
        "Open-Meteo forecast data, compared to a 5-yr seasonal normal computed "
        "from the historical archive. Four event types fire with explicit "
        "thresholds:\n\n"
        "- **Cold snap** — 2+ consecutive days where forecast temperature anomaly "
        "is below −3 °C vs the 5-yr seasonal normal at any DE/FR/GB centroid. "
        "Severe if any day < −6 °C.\n"
        "- **Heat dome** — symmetric, 2+ consecutive days above +3 °C; severe above +6 °C.\n"
        "- **Wind drought (dunkelflaute)** — 2+ consecutive days where daily-max "
        "wind speed < 5 m/s **and** mean cloud cover > 60%. Severe if window ≥ 4 days.\n"
        "- **Storm** — any day with daily-max wind gust ≥ 28 m/s (~100 km/h, "
        "Beaufort 10+); deduped to one event per region in the 7-day window. "
        "Severe at ≥ 35 m/s.\n\n"
        "Each event carries a region-aware `trading_implication` line — what a "
        "meteorologist would flag for the desk. Mirrors Cobblestone's named "
        "**Energy Meteorologists** team function. Pure pandas/numpy in "
        "`analysis/weather.py`; not an AI pass — the AI extract pass can consume "
        "the events as additional context but doesn't generate them."
    )

    st.markdown("### Risk management framing (mirrors Cobblestone's 4 pillars)")
    st.markdown(
        "Cobblestone's Power and Gas Trading pages both close with a four-pillar "
        "Risk Management section. Below maps the four pillars onto where the "
        "dashboard surfaces an analogous control:"
    )
    st.markdown(
        "- **Disciplined Risk Framework** — *clear limits, controls, and governance.* "
        "Hard-coded percentile / σ / z thresholds in `config.py` "
        f"(PERCENTILE_HIGH={PERCENTILE_HIGH}, PERCENTILE_LOW={PERCENTILE_LOW}, "
        f"SIGMA_EXTENDED={SIGMA_EXTENDED}, ZSCORE_OUTSIZED={ZSCORE_OUTSIZED}); "
        "surfaced in the snapshot table as headlines when a series crosses one.\n"
        "- **Integrated Controls** — *risk, trading, and operations functions work "
        "closely together.* The two-pass AI workflow gates the narrate pass on the "
        "extract JSON — controls and narrative read from the same numbers.\n"
        "- **Continuous Monitoring** — *positions, exposures, and performance "
        "monitored in real time, supported by analytics and automated checks.* "
        "1-hour `@st.cache_data` TTL refreshes; `tests/test_fetchers.py` smoke-tests "
        "every live source; the regime strip is the always-on monitoring surface.\n"
        "- **Operational Reliability** — *strong back-office processes and system "
        "resilience.* Per-fetcher `_safe()` snapshot fallback + `is_stale` flag + "
        "STALE banner; soft-fail in the cron so one broken source doesn't kill the "
        "run; append-only JSONL audit log of every AI call."
    )
